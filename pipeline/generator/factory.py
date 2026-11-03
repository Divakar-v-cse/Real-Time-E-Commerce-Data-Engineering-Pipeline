"""Synthetic e-commerce source-system factory.

Produces a coherent relational dataset (customers -> orders -> items ->
payments -> shipments -> returns) with realistic distributions, seasonality,
repeat-purchase behaviour and a controlled share of data-quality defects.
"""
from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

from . import catalog

CURRENCY_BY_COUNTRY = {
    "United States": "USD", "Canada": "USD", "United Kingdom": "GBP", "Germany": "EUR",
    "France": "EUR", "Spain": "EUR", "Netherlands": "EUR", "India": "INR",
    "Australia": "AUD", "Japan": "JPY", "Singapore": "USD", "Brazil": "BRL",
    "Mexico": "USD", "United Arab Emirates": "AED", "South Africa": "USD", "Saudi Arabia": "AED",
}

# Defect injection rates (fraction of records).
DQ_RATES = {
    "duplicate_order": 0.012,
    "null_customer": 0.004,
    "negative_price": 0.003,
    "future_timestamp": 0.002,
    "missing_payment_status": 0.005,
    "orphan_product": 0.003,
    "total_mismatch": 0.008,
    "late_arriving": 0.015,
}


@dataclass
class Customer:
    customer_id: str
    email: str
    full_name: str
    country: str
    city: str
    region: str
    segment: str
    acquisition_channel: str
    signup_date: str
    date_of_birth_year: int
    loyalty_propensity: float  # internal field, not exported


class Factory:
    """Stateful generator: one instance owns the master data + RNG."""

    def __init__(self, seed: int = 42, n_customers: int = 25_000, n_products: int = 900):
        self.rng = random.Random(seed)
        self.products = catalog.build_products(self.rng, n_products)
        self.customers = self._build_customers(n_customers)
        self._product_pool = self._weighted_product_pool()
        self.dq_counts: dict[str, int] = {k: 0 for k in DQ_RATES}

    # ------------------------------------------------------------------ #
    # Master data
    # ------------------------------------------------------------------ #
    def _build_customers(self, n: int) -> list[Customer]:
        rng = self.rng
        today = datetime.now(timezone.utc).date()
        out: list[Customer] = []
        firsts = ("Aarav", "Sofia", "Liam", "Mia", "Noah", "Ananya", "Lucas", "Emma", "Arjun",
                  "Olivia", "Mateo", "Ava", "Ethan", "Zara", "Kabir", "Chloe", "Diego", "Ishaan",
                  "Hannah", "Rohan", "Elena", "Marco", "Priya", "Jonas", "Amara", "Wei", "Sara")
        lasts = ("Sharma", "Rossi", "Johnson", "Silva", "Kim", "Patel", "Muller", "Garcia", "Okafor",
                 "Nguyen", "Andersen", "Costa", "Khan", "Fischer", "Lopez", "Iyer", "Dubois", "Wang")
        segments = [("Consumer", 0.78), ("SMB", 0.15), ("Enterprise", 0.07)]

        for i in range(n):
            region = catalog.weighted_choice(rng, catalog.region_weights())
            country = catalog.country_for_region(rng, region)
            city = catalog.city_for_country(rng, country)
            first, last = rng.choice(firsts), rng.choice(lasts)
            signup = today - timedelta(days=rng.randint(0, 900))
            out.append(
                Customer(
                    customer_id=f"C{i + 1:06d}",
                    email=f"{first.lower()}.{last.lower()}{i}@example.com",
                    full_name=f"{first} {last}",
                    country=country,
                    city=city,
                    region=region,
                    segment=catalog.weighted_choice(rng, segments),
                    acquisition_channel=catalog.weighted_choice(rng, list(catalog.ACQUISITION_CHANNELS)),
                    signup_date=signup.isoformat(),
                    date_of_birth_year=rng.randint(1955, 2005),
                    loyalty_propensity=round(rng.paretovariate(1.9), 4),
                )
            )
        return out

    def _weighted_product_pool(self) -> list[Any]:
        """Expand products by popularity so hero SKUs appear far more often."""
        pool: list[Any] = []
        for p in self.products:
            if not p.is_active:
                continue
            pool.extend([p] * max(1, min(30, int(round(p.popularity * 4)))))
        return pool

    # ------------------------------------------------------------------ #
    # Seasonality
    # ------------------------------------------------------------------ #
    @staticmethod
    def seasonal_multiplier(day: datetime, start: datetime) -> float:
        """Growth trend x weekly x annual seasonality x promo spikes."""
        progress = max(0.0, min(1.0, (day - start).days / 540))
        growth = 0.55 + 1.05 * progress                      # 0.55x -> 1.60x

        weekday = day.weekday()
        weekly = {0: 1.02, 1: 0.97, 2: 0.95, 3: 1.01, 4: 1.12, 5: 1.18, 6: 1.08}[weekday]

        month = day.month
        annual = {1: 0.88, 2: 0.86, 3: 0.95, 4: 0.97, 5: 1.0, 6: 0.98,
                  7: 0.96, 8: 0.97, 9: 1.03, 10: 1.06, 11: 1.28, 12: 1.34}[month]

        promo = 1.0
        if month == 11 and 22 <= day.day <= 30:              # Black Friday / Cyber Monday
            promo = 2.35
        elif month == 12 and 10 <= day.day <= 20:            # holiday shipping cut-off
            promo = 1.45
        elif month in (6, 7) and 8 <= day.day <= 12:         # mid-year sale
            promo = 1.55
        elif day.day <= 3:                                   # start-of-month payday
            promo = 1.12
        return growth * weekly * annual * promo

    # ------------------------------------------------------------------ #
    # Transactions
    # ------------------------------------------------------------------ #
    def _pick_customer(self) -> Customer:
        # 62% of orders come from the ~18% most loyal customers (repeat buyers).
        if self.rng.random() < 0.62:
            idx = int(len(self.customers) * (self.rng.random() ** 2.2))
            return self.customers[idx]
        return self.customers[self.rng.randrange(len(self.customers))]

    def make_order(self, order_ts: datetime, sequence: int) -> dict[str, Any]:
        rng = self.rng
        customer = self._pick_customer()
        n_items = catalog.weighted_choice(
            rng, [("1", 0.52), ("2", 0.27), ("3", 0.13), ("4", 0.06), ("5", 0.02)]
        )
        n_items = int(n_items)

        items: list[dict[str, Any]] = []
        used: set[str] = set()
        for _ in range(n_items):
            product = rng.choice(self._product_pool)
            if product.product_id in used and rng.random() < 0.7:
                continue
            used.add(product.product_id)
            qty = rng.choices([1, 2, 3, 4], weights=[0.74, 0.17, 0.06, 0.03])[0]
            # Discounts are deeper during promo windows and on fashion/home.
            base_disc = 0.0
            if rng.random() < 0.42:
                base_disc = round(rng.choice([0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40]), 2)
            if order_ts.month == 11 and order_ts.day >= 22:
                base_disc = min(0.55, base_disc + 0.15)
            items.append(
                {
                    "product_id": product.product_id,
                    "product_name": product.product_name,
                    "category": product.category,
                    "subcategory": product.subcategory,
                    "quantity": qty,
                    "unit_price": product.unit_price,
                    "discount_pct": round(base_disc, 2),
                    "unit_cost": product.unit_cost,
                }
            )
        if not items:
            product = rng.choice(self._product_pool)
            items.append({"product_id": product.product_id, "product_name": product.product_name,
                          "category": product.category, "subcategory": product.subcategory,
                          "quantity": 1, "unit_price": product.unit_price,
                          "discount_pct": 0.0, "unit_cost": product.unit_cost})

        subtotal = round(sum(i["quantity"] * i["unit_price"] for i in items), 2)
        discount_total = round(sum(i["quantity"] * i["unit_price"] * i["discount_pct"] for i in items), 2)
        net = subtotal - discount_total
        shipping = 0.0 if net >= 75 else 6.99
        total = round(net + shipping, 2)

        order_id = f"O{order_ts:%Y%m%d}{sequence:07d}"
        payment_method = catalog.weighted_choice(rng, list(catalog.PAYMENT_METHODS))
        success_rate = catalog.PAYMENT_SUCCESS_RATE[payment_method]

        roll = rng.random()
        if roll < success_rate:
            payment_status = "success"
        elif roll < success_rate + (1 - success_rate) * 0.72:
            payment_status = "failed"
        else:
            payment_status = "pending"

        if payment_status == "failed":
            status = "cancelled" if rng.random() < 0.82 else "pending"
        elif payment_status == "pending":
            status = "pending"
        else:
            status = catalog.weighted_choice(
                rng, [("completed", 0.895), ("processing", 0.036), ("cancelled", 0.029), ("returned", 0.040)]
            )

        currency = CURRENCY_BY_COUNTRY.get(customer.country, "USD")
        return {
            "order_id": order_id,
            "customer_id": customer.customer_id,
            "order_ts": order_ts.replace(tzinfo=timezone.utc).isoformat(),
            "status": status,
            "channel": catalog.weighted_choice(rng, list(catalog.ORDER_CHANNELS)),
            "currency": currency,
            "country": customer.country,
            "region": customer.region,
            "city": customer.city,
            "subtotal": subtotal,
            "discount_total": discount_total,
            "shipping_total": shipping,
            "order_total": total,
            "item_count": len(items),
            "payment_method": payment_method,
            "payment_status": payment_status,
            "customer_segment": customer.segment,
            "_items": items,
            "_payment_roll": roll,
            "_success_rate": success_rate,
            "_customer": customer,
        }

    def build_payment(self, order: dict[str, Any]) -> dict[str, Any]:
        rng = self.rng
        status = order["payment_status"]
        reason = None
        if status == "failed":
            reason = catalog.weighted_choice(rng, list(catalog.FAILURE_REASONS))
        paid_at = None
        if status == "success":
            paid_at = (datetime.fromisoformat(order["order_ts"]) +
                       timedelta(seconds=rng.randint(20, 900))).isoformat()
        return {
            "payment_id": f"PAY-{order['order_id'][-11:]}",
            "order_id": order["order_id"],
            "payment_method": order["payment_method"],
            "payment_status": status,
            "amount": order["order_total"],
            "currency": order["currency"],
            "paid_at": paid_at,
            "failure_reason": reason,
            "gateway": rng.choice(["stripe", "adyen", "razorpay", "paypal_gw"]),
        }

    def build_shipment(self, order: dict[str, Any]) -> dict[str, Any] | None:
        rng = self.rng
        if order["status"] in ("pending", "cancelled"):
            return None
        order_ts = datetime.fromisoformat(order["order_ts"])
        ship_delay_h = rng.randint(3, 60) if order["region"] in ("Asia Pacific",) else rng.randint(6, 72)
        shipped_at = order_ts + timedelta(hours=ship_delay_h)
        transit_days = {"North America": rng.randint(2, 6), "Europe": rng.randint(2, 7),
                        "Asia Pacific": rng.randint(1, 5), "Latin America": rng.randint(4, 11),
                        "Middle East & Africa": rng.randint(3, 9)}[order["region"]]
        delivered_at = shipped_at + timedelta(days=transit_days, hours=rng.randint(0, 20))

        now = datetime.now(timezone.utc)
        if order["status"] == "returned":
            ship_status = "returned"
        elif delivered_at > now:
            ship_status = "in_transit"
        else:
            ship_status = "delivered" if rng.random() > 0.035 else "exception"

        return {
            "shipment_id": f"SHP-{order['order_id'][-9:]}",
            "order_id": order["order_id"],
            "carrier": catalog.weighted_choice(rng, list(catalog.CARRIERS)),
            "tracking_number": f"TRK{uuid.uuid4().hex[:14].upper()}",
            "shipment_status": ship_status,
            "shipped_at": shipped_at.isoformat(),
            "delivered_at": delivered_at.isoformat() if ship_status in ("delivered", "returned") else None,
            "transit_days": transit_days,
            "shipping_cost": round(rng.uniform(2.4, 14.5), 2),
        }

    def build_return(self, order: dict[str, Any], shipment: dict[str, Any] | None) -> dict[str, Any] | None:
        rng = self.rng
        if order["status"] != "returned":
            return None
        items = order.get("_items") or []
        category = items[0]["category"] if items else None
        cat_return = next((c.return_rate for c in catalog.CATEGORIES if c.name == category), 0.06)
        refund_ratio = 1.0 if rng.random() > 0.18 else round(rng.uniform(0.3, 0.9), 2)
        requested = datetime.fromisoformat(order["order_ts"]) + timedelta(days=rng.randint(2, 21))
        return {
            "return_id": f"RET-{order['order_id'][-9:]}",
            "order_id": order["order_id"],
            "return_ts": requested.isoformat(),
            "reason": catalog.weighted_choice(rng, list(catalog.RETURN_REASONS)),
            "refund_amount": round(order["order_total"] * refund_ratio, 2),
            "refund_status": rng.choices(["refunded", "pending", "rejected"], weights=[0.86, 0.11, 0.03])[0],
            "category_return_rate_baseline": cat_return,
        }

    # ------------------------------------------------------------------ #
    # Defect injection
    # ------------------------------------------------------------------ #
    def inject_defects(self, order: dict[str, Any], items: list[dict[str, Any]],
                       dq_log: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Mutate a small share of records so the pipeline has something to clean."""
        rng = self.rng
        oid = order["order_id"]

        def log(issue: str, table: str, pk: str) -> None:
            self.dq_counts[issue] += 1
            dq_log.append({"issue_type": issue, "table": table, "record_key": pk})

        if rng.random() < DQ_RATES["null_customer"]:
            order["customer_id"] = None
            log("null_customer", "orders", oid)

        if rng.random() < DQ_RATES["future_timestamp"]:
            order["order_ts"] = (datetime.now(timezone.utc) + timedelta(days=rng.randint(3, 40))).isoformat()
            log("future_timestamp", "orders", oid)

        if rng.random() < DQ_RATES["missing_payment_status"]:
            order["payment_status"] = None
            log("missing_payment_status", "orders", oid)

        if items and rng.random() < DQ_RATES["negative_price"]:
            items[0]["unit_price"] = -abs(float(items[0]["unit_price"])) if items[0]["unit_price"] else -12.99
            log("negative_price", "order_items", oid)

        if items and rng.random() < DQ_RATES["orphan_product"]:
            items[0]["product_id"] = "P99999"
            log("orphan_product", "order_items", oid)

        if rng.random() < DQ_RATES["total_mismatch"]:
            order["order_total"] = round(float(order["order_total"]) * rng.uniform(0.55, 0.92), 2)
            log("total_mismatch", "orders", oid)

        return order, items

    def iter_orders(self, start: datetime, days: int, target_orders: int) -> Iterator[tuple[dict, list[dict], list[dict]]]:
        """Yield (order, items, dq_log) spread across the period."""
        rng = self.rng
        total_weight = sum(self.seasonal_multiplier(start + timedelta(days=d), start) for d in range(days))
        per_weight = target_orders / total_weight
        seq = 0
        dq_log: list[dict[str, Any]] = []

        for d in range(days):
            day = start + timedelta(days=d)
            n_today = int(round(per_weight * self.seasonal_multiplier(day, start)))
            # Intraday curve: two peaks (lunch, evening).
            for _ in range(n_today):
                hour = rng.choices(
                    [7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23],
                    weights=[2, 3, 5, 6, 7, 9, 8, 7, 7, 7, 8, 10, 13, 15, 13, 9, 4],
                )[0]
                order_ts = day.replace(hour=hour, minute=rng.randint(0, 59), second=rng.randint(0, 59))
                if order_ts > datetime.now(timezone.utc) - timedelta(hours=2):
                    continue
                seq += 1
                order = self.make_order(order_ts, seq)
                items = order.pop("_items")
                for k in ("_payment_roll", "_success_rate", "_customer"):
                    order.pop(k, None)

                per_order_log: list[dict[str, Any]] = []
                order, items = self.inject_defects(order, items, per_order_log)

                item_rows = []
                for n, item in enumerate(items, start=1):
                    item_rows.append({
                        "order_item_id": f"{order['order_id']}-{n}",
                        "order_id": order["order_id"],
                        "product_id": item["product_id"],
                        "quantity": item["quantity"],
                        "unit_price": item["unit_price"],
                        "discount_pct": item["discount_pct"],
                        "line_total": round(item["quantity"] * item["unit_price"] * (1 - item["discount_pct"]), 2),
                        "unit_cost": item["unit_cost"],
                    })

                dq_log.extend(per_order_log)
                yield order, item_rows, per_order_log
