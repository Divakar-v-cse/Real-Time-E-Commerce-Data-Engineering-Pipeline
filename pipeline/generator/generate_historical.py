"""Generate the historical e-commerce dataset (source-system extracts).

Usage
-----
    python -m pipeline.generator.generate_historical --orders 120000 --days 540
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .factory import DQ_RATES, Factory

ORDER_FIELDS = ["order_id", "customer_id", "order_ts", "status", "channel", "currency",
                "country", "region", "city", "subtotal", "discount_total",
                "shipping_total", "order_total", "item_count", "payment_method", "payment_status"]
ITEM_FIELDS = ["order_item_id", "order_id", "product_id", "quantity", "unit_price",
               "discount_pct", "line_total", "unit_cost"]
PAYMENT_FIELDS = ["payment_id", "order_id", "payment_method", "payment_status", "amount",
                  "currency", "paid_at", "failure_reason", "gateway"]
SHIPMENT_FIELDS = ["shipment_id", "order_id", "carrier", "tracking_number", "shipment_status",
                   "shipped_at", "delivered_at", "transit_days", "shipping_cost"]
RETURN_FIELDS = ["return_id", "order_id", "return_ts", "reason", "refund_amount",
                 "refund_status", "category_return_rate_baseline"]


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate synthetic e-commerce history")
    ap.add_argument("--orders", type=int, default=120_000)
    ap.add_argument("--days", type=int, default=540)
    ap.add_argument("--customers", type=int, default=25_000)
    ap.add_argument("--products", type=int, default=900)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="data/raw")
    args = ap.parse_args()

    started = time.time()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    factory = Factory(seed=args.seed, n_customers=args.customers, n_products=args.products)
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=args.days)

    # ---------------- master data ---------------- #
    with (out / "customers.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "email", "full_name", "country", "city", "region",
                    "segment", "acquisition_channel", "signup_date", "date_of_birth_year"])
        for c in factory.customers:
            w.writerow([c.customer_id, c.email, c.full_name, c.country, c.city, c.region,
                        c.segment, c.acquisition_channel, c.signup_date, c.date_of_birth_year])

    with (out / "products.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["product_id", "sku", "product_name", "category", "subcategory", "brand",
                    "unit_price", "unit_cost", "weight_kg", "is_active", "launched_at"])
        for p in factory.products:
            w.writerow([p.product_id, p.sku, p.product_name, p.category, p.subcategory, p.brand,
                        p.unit_price, p.unit_cost, p.weight_kg, p.is_active, p.launched_at])

    # ---------------- transactions ---------------- #
    dq_log: list[dict] = []
    rng = random.Random(args.seed + 1)
    n_orders = n_items = n_payments = n_shipments = n_returns = 0

    with (out / "orders.csv").open("w", newline="", encoding="utf-8") as fo, \
         (out / "order_items.csv").open("w", newline="", encoding="utf-8") as fi, \
         (out / "payments.csv").open("w", newline="", encoding="utf-8") as fp, \
         (out / "shipments.csv").open("w", newline="", encoding="utf-8") as fs, \
         (out / "returns.csv").open("w", newline="", encoding="utf-8") as fr:

        wo, wi, wp, ws, wr = (csv.DictWriter(f, fieldnames=x) for f, x in
                              ((fo, ORDER_FIELDS), (fi, ITEM_FIELDS), (fp, PAYMENT_FIELDS),
                               (fs, SHIPMENT_FIELDS), (fr, RETURN_FIELDS)))
        for w in (wo, wi, wp, ws, wr):
            w.writeheader()

        for order, items, _log in factory.iter_orders(start, args.days, args.orders):
            wo.writerow({k: order.get(k) for k in ORDER_FIELDS})
            n_orders += 1

            # duplicate order rows (same business key, different ingestion copy)
            if rng.random() < DQ_RATES["duplicate_order"]:
                wo.writerow({k: order.get(k) for k in ORDER_FIELDS})
                factory.dq_counts["duplicate_order"] += 1
                dq_log.append({"issue_type": "duplicate_order", "table": "orders",
                               "record_key": order["order_id"]})
                n_orders += 1

            for row in items:
                wi.writerow(row)
                n_items += 1

            payment = factory.build_payment(order)
            if payment["payment_status"] is None:
                payment["payment_status"] = order.get("payment_status") or ""
            wp.writerow(payment)
            n_payments += 1

            shipment = factory.build_shipment(order)
            if shipment:
                ws.writerow({k: shipment.get(k) for k in SHIPMENT_FIELDS})
                n_shipments += 1

            ret = factory.build_return(order, shipment)
            if ret:
                wr.writerow({k: ret.get(k) for k in RETURN_FIELDS})
                n_returns += 1

    # ---------------- defect log + manifest ---------------- #
    with (out / "_dq_injected.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["issue_type", "table", "record_key"])
        w.writeheader()
        w.writerows(dq_log)

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_start": start.date().isoformat(),
        "window_end": end.date().isoformat(),
        "days": args.days,
        "seed": args.seed,
        "rows": {
            "customers": len(factory.customers),
            "products": len(factory.products),
            "orders": n_orders,
            "order_items": n_items,
            "payments": n_payments,
            "shipments": n_shipments,
            "returns": n_returns,
        },
        "injected_defects": factory.dq_counts,
        "defect_rate_pct": round(sum(factory.dq_counts.values()) / max(1, n_orders) * 100, 3),
        "elapsed_seconds": round(time.time() - started, 1),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
