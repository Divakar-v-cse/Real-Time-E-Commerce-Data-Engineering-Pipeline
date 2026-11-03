"""Batch ELT: CSV extracts -> staging -> star schema (PostgreSQL).

This is the batch twin of the streaming path:
  * bronze equivalent : `staging.raw_*` (verbatim load, everything TEXT)
  * silver equivalent : typed / de-duplicated / rule-filtered inserts
  * gold equivalent   : conformed dimensions and facts in `warehouse`

Every stage writes an ``ops.pipeline_runs`` row so the UI can show real
pipeline telemetry instead of hard-coded status.
"""
from __future__ import annotations

import csv
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from common.db import fetch_all, get_engine
from common.logging import configure_logging
import logging

from common.settings import RAW_DIR, PROJECT_ROOT
from warehouse.stream_sink import backfill_gold

log = logging.getLogger("warehouse.load")

DDL_PATH = PROJECT_ROOT / "warehouse" / "ddl_postgres.sql"

STAGING_TABLES: dict[str, str] = {
    "customers": "staging.raw_customers",
    "products": "staging.raw_products",
    "orders": "staging.raw_orders",
    "order_items": "staging.raw_order_items",
    "payments": "staging.raw_payments",
    "shipments": "staging.raw_shipments",
    "returns": "staging.raw_returns",
}

VALID_STATUSES = ("completed", "pending", "processing", "cancelled", "returned")


# --------------------------------------------------------------------------- #
# run tracking
# --------------------------------------------------------------------------- #
def start_run(pipeline_name: str, run_type: str = "batch", details: dict | None = None) -> int:
    with get_engine().begin() as conn:
        row = conn.execute(
            text(
                """INSERT INTO ops.pipeline_runs (pipeline_name, run_type, status, details)
                   VALUES (:name, :rtype, 'running', CAST(:details AS JSONB))
                   RETURNING run_id"""
            ),
            {"name": pipeline_name, "rtype": run_type, "details": json.dumps(details or {})},
        ).first()
    return int(row[0])


def finish_run(run_id: int, status: str, records_in: int = 0, records_out: int = 0,
               records_rejected: int = 0, error: str | None = None,
               details: dict | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """UPDATE ops.pipeline_runs
                      SET status = :status,
                          finished_at = now(),
                          duration_seconds = EXTRACT(EPOCH FROM (now() - started_at)),
                          records_in = :rin,
                          records_out = :rout,
                          records_rejected = :rej,
                          error_message = :err,
                          details = COALESCE(CAST(:details AS JSONB), details)
                    WHERE run_id = :rid"""
            ),
            {"status": status, "rin": records_in, "rout": records_out, "rej": records_rejected,
             "err": error, "details": json.dumps(details) if details else None, "rid": run_id},
        )


def record_metric(name: str, value: float, unit: str, labels: dict | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text("""INSERT INTO ops.pipeline_metrics (metric_name, metric_value, unit, labels)
                    VALUES (:n, :v, :u, CAST(:l AS JSONB))"""),
            {"n": name, "v": value, "u": unit, "l": json.dumps(labels or {})},
        )


# --------------------------------------------------------------------------- #
# DDL
# --------------------------------------------------------------------------- #
def apply_ddl() -> None:
    sql = DDL_PATH.read_text(encoding="utf-8")
    with get_engine().begin() as conn:
        conn.exec_driver_sql(sql)
    log.info("warehouse DDL applied")


# --------------------------------------------------------------------------- #
# staging load (COPY)
# --------------------------------------------------------------------------- #
def _copy_csv(conn, table: str, path: Path, columns: list[str]) -> int:
    if not path.exists():
        log.warning("missing extract, skipping", extra={"extra_fields": {"path": str(path)}})
        return 0
    buffer = io.StringIO()
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        idx = [header.index(c) for c in columns if c in header]
        wanted = [c for c in columns if c in header]
        for row in reader:
            buffer.write("\t".join(
                (row[i] if i < len(row) else "").replace("\t", " ").replace("\n", " ") for i in idx
            ) + "\n")
    buffer.seek(0)
    cols = ", ".join(wanted)
    conn.cursor().copy_expert(f"COPY {table} ({cols}) FROM STDIN", buffer)
    return sum(1 for _ in buffer.getvalue().splitlines())


def load_staging(raw_dir: Path = RAW_DIR) -> dict[str, int]:
    started = time.time()
    run_id = start_run("batch_staging_load", "batch")
    counts: dict[str, int] = {}
    try:
        raw = get_engine().raw_connection()
        try:
            cur = raw.cursor()
            for table in STAGING_TABLES.values():
                cur.execute(f"TRUNCATE {table}")
            raw.commit()

            for name, table in STAGING_TABLES.items():
                path = raw_dir / f"{name}.csv"
                if not path.exists():
                    counts[name] = 0
                    continue
                with path.open("r", encoding="utf-8", newline="") as f:
                    reader = csv.reader(f)
                    header = next(reader)
                counts[name] = _copy_csv(raw, table, path, header)
                raw.commit()
        finally:
            raw.close()

        finish_run(run_id, "success", records_in=sum(counts.values()),
                   records_out=sum(counts.values()),
                   details={"tables": counts, "elapsed_s": round(time.time() - started, 1)})
        log.info("staging loaded", extra={"extra_fields": {"counts": counts}})
        return counts
    except Exception as exc:
        finish_run(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
        raise


# --------------------------------------------------------------------------- #
# dimensional load
# --------------------------------------------------------------------------- #
def load_dim_customer_scd2() -> int:
    """SCD2 load: close changed versions, insert new current versions."""
    sql = """
    WITH src AS (
        SELECT DISTINCT ON (customer_id)
               customer_id, email, full_name, country, city, region, segment,
               acquisition_channel, signup_date, date_of_birth_year
          FROM staging.raw_customers
         WHERE COALESCE(customer_id, '') <> ''
         ORDER BY customer_id, row_id DESC
    ), hashed AS (
        SELECT *,
               md5(concat_ws('|', region, segment, acquisition_channel, city, country)) AS row_hash
          FROM src
    ), closed AS (
        UPDATE warehouse.dim_customer d
           SET valid_to = now(), is_current = FALSE
          FROM hashed h
         WHERE d.customer_id = h.customer_id
           AND d.is_current
           AND d.row_hash <> h.row_hash
        RETURNING d.customer_id
    )
    INSERT INTO warehouse.dim_customer
        (customer_id, email, full_name, country, city, region, segment,
         acquisition_channel, signup_date, birth_year, row_hash, valid_from, is_current)
    SELECT h.customer_id, h.email, h.full_name, h.country, h.city, h.region, h.segment,
           h.acquisition_channel,
           NULLIF(h.signup_date, '')::date,
           NULLIF(h.date_of_birth_year, '')::int,
           h.row_hash, now(), TRUE
      FROM hashed h
     WHERE NOT EXISTS (
           SELECT 1 FROM warehouse.dim_customer d
            WHERE d.customer_id = h.customer_id
              AND d.is_current
              AND d.row_hash = h.row_hash)
    """
    with get_engine().begin() as conn:
        inserted = conn.execute(text(sql)).rowcount or 0
    return inserted


def load_dim_product() -> int:
    sql = """
    WITH src AS (
        SELECT DISTINCT ON (product_id) *
          FROM staging.raw_products
         WHERE COALESCE(product_id, '') <> ''
         ORDER BY product_id, row_id DESC
    )
    INSERT INTO warehouse.dim_product
        (product_id, sku, product_name, category, subcategory, brand,
         unit_price, unit_cost, is_active, launched_at)
    SELECT src.product_id, src.sku, src.product_name, src.category, src.subcategory, src.brand,
           NULLIF(src.unit_price, '')::numeric(12,2),
           NULLIF(src.unit_cost, '')::numeric(12,2),
           COALESCE(NULLIF(src.is_active, '')::boolean, TRUE),
           NULLIF(src.launched_at, '')::date
      FROM src
    ON CONFLICT (product_id) DO UPDATE
       SET product_name = EXCLUDED.product_name,
           category = EXCLUDED.category,
           subcategory = EXCLUDED.subcategory,
           unit_price = EXCLUDED.unit_price,
           unit_cost = EXCLUDED.unit_cost,
           is_active = EXCLUDED.is_active
    """
    with get_engine().begin() as conn:
        return conn.execute(text(sql)).rowcount or 0


def reject_breakdown() -> dict[str, int]:
    """Count quarantined source rows by the business rule they violated."""
    rows = fetch_all(
        "SELECT reason, count(*) AS n FROM ops.rejected_records GROUP BY reason ORDER BY n DESC"
    )
    return {r["reason"]: int(r["n"]) for r in rows}


def load_fact_orders(run_id: int | None = None) -> tuple[int, int, int]:
    """Load conformed orders, quarantining every row that fails a business rule.

    Returns ``(accepted, rejected, raw)``.  Rejected rows are *not* discarded:
    they are written to ``ops.rejected_records`` with the rule that failed, so
    the warehouse holds only valid orders while the audit trail stays complete.
    """
    stats: dict[str, int] = {}
    with get_engine().begin() as conn:
        base = conn.execute(text("SELECT count(*) FROM staging.raw_orders")).scalar_one()
        stats["raw"] = int(base)

        conn.execute(text("TRUNCATE warehouse.fact_order_items, warehouse.fact_payments, "
                          "warehouse.fact_shipments, warehouse.fact_returns, "
                          "warehouse.fact_orders RESTART IDENTITY CASCADE"))
        conn.execute(text("TRUNCATE ops.rejected_records RESTART IDENTITY"))

        # One classification pass: ``reject_reason`` NULL means the row is valid.
        classified = """
        WITH dedup AS (
            SELECT DISTINCT ON (order_id) *
              FROM staging.raw_orders
             WHERE COALESCE(order_id, '') <> ''
             ORDER BY order_id, row_id DESC
        ), typed AS (
            SELECT d.*,
                   NULLIF(d.order_ts, '')::timestamptz AS ts,
                   NULLIF(d.order_total, '')::numeric(14,2) AS total,
                   NULLIF(d.subtotal, '')::numeric(14,2) AS sub,
                   NULLIF(d.discount_total, '')::numeric(14,2) AS disc,
                   NULLIF(d.shipping_total, '')::numeric(14,2) AS ship,
                   NULLIF(d.item_count, '')::int AS items
              FROM dedup d
        ), joined AS (
            SELECT t.*, c.customer_sk, pm.payment_method_sk,
                   TO_CHAR(t.ts, 'YYYYMMDD')::int AS date_key
              FROM typed t
              LEFT JOIN warehouse.dim_customer c
                ON c.customer_id = t.customer_id AND c.is_current
              LEFT JOIN warehouse.dim_payment_method pm
                ON pm.method_name = t.payment_method
        ), classified AS (
            SELECT j.*,
                   CASE
                     WHEN COALESCE(j.customer_id, '') = '' THEN 'missing_customer_id'
                     WHEN j.ts IS NULL OR COALESCE(j.order_ts, '') !~ '^\\d{4}-\\d{2}-\\d{2}'
                          THEN 'invalid_timestamp'
                     WHEN j.ts > now() + interval '1 day' THEN 'future_timestamp'
                     WHEN NOT (j.status = ANY(:statuses)) THEN 'invalid_status'
                     WHEN j.total IS NULL THEN 'missing_total'
                     WHEN j.total < 0 THEN 'negative_total'
                     WHEN j.customer_sk IS NULL THEN 'unknown_customer'
                     WHEN ABS(j.total - (COALESCE(j.sub, 0) - COALESCE(j.disc, 0)
                                         + COALESCE(j.ship, 0))) > 0.02
                          THEN 'invalid_order_total'
                     ELSE NULL
                   END AS reject_reason
              FROM joined j
        )
        """

        rejected = conn.execute(text(classified + """
        INSERT INTO ops.rejected_records (source_table, business_key, reason, payload, run_id)
        SELECT 'staging.raw_orders', order_id, reject_reason,
               jsonb_build_object(
                   'order_total', total, 'subtotal', sub, 'discount_total', disc,
                   'shipping_total', ship, 'status', status, 'order_ts', order_ts,
                   'customer_id', customer_id
               ),
               :run_id
          FROM classified
         WHERE reject_reason IS NOT NULL
        """), {"statuses": list(VALID_STATUSES), "run_id": run_id}).rowcount or 0
        stats["rejected"] = int(rejected)

        accepted = conn.execute(text(classified + """
        INSERT INTO warehouse.fact_orders
            (order_id, customer_sk, date_key, payment_method_sk, status, channel, currency,
             country, region, item_count, subtotal, discount_total, shipping_total, order_total,
             is_completed, is_cancelled, is_returned, order_ts, ingested_at)
        SELECT order_id, customer_sk, date_key, payment_method_sk, status, channel, currency,
               country, region, COALESCE(items, 0), COALESCE(sub, 0), COALESCE(disc, 0),
               COALESCE(ship, 0), total,
               status = 'completed', status = 'cancelled', status = 'returned',
               ts, now()
          FROM classified
         WHERE reject_reason IS NULL
        ON CONFLICT (order_id) DO NOTHING
        """), {"statuses": list(VALID_STATUSES), "run_id": run_id}).rowcount or 0
        stats["accepted"] = int(accepted)

    return stats["accepted"], stats["rejected"], stats["raw"] - stats["accepted"]


def load_fact_items() -> tuple[int, int]:
    sql = """
    WITH dedup AS (
        SELECT DISTINCT ON (order_item_id) *
          FROM staging.raw_order_items
         WHERE COALESCE(order_item_id, '') <> ''
         ORDER BY order_item_id, row_id DESC
    )
    INSERT INTO warehouse.fact_order_items
        (order_item_id, order_id, product_sk, quantity, unit_price, discount_pct,
         line_total, unit_cost, gross_profit)
    SELECT s.order_item_id, s.order_id, p.product_sk,
           NULLIF(s.quantity, '')::int,
           NULLIF(s.unit_price, '')::numeric(12,2),
           LEAST(GREATEST(COALESCE(NULLIF(s.discount_pct, '')::numeric, 0), 0), 1),
           ROUND(NULLIF(s.quantity, '')::numeric * NULLIF(s.unit_price, '')::numeric
                 * (1 - LEAST(GREATEST(COALESCE(NULLIF(s.discount_pct, '')::numeric, 0), 0), 1)), 2),
           NULLIF(s.unit_cost, '')::numeric(12,2),
           ROUND(NULLIF(s.quantity, '')::numeric *
                 (NULLIF(s.unit_price, '')::numeric
                  * (1 - LEAST(GREATEST(COALESCE(NULLIF(s.discount_pct, '')::numeric, 0), 0), 1))
                  - COALESCE(NULLIF(s.unit_cost, '')::numeric, 0)), 2)
      FROM dedup s
      JOIN warehouse.fact_orders o ON o.order_id = s.order_id
      JOIN warehouse.dim_product p ON p.product_id = s.product_id
     WHERE NULLIF(s.quantity, '')::int > 0
       AND NULLIF(s.unit_price, '')::numeric >= 0
    ON CONFLICT (order_item_id) DO NOTHING
    """
    with get_engine().begin() as conn:
        raw = conn.execute(text("SELECT count(DISTINCT order_item_id) FROM staging.raw_order_items")).scalar_one()
        ok = conn.execute(text(sql)).rowcount or 0
    return ok, int(raw) - ok


def load_fact_payments() -> int:
    sql = """
    WITH dedup AS (
        SELECT DISTINCT ON (payment_id) *
          FROM staging.raw_payments
         WHERE COALESCE(payment_id, '') <> ''
         ORDER BY payment_id, row_id DESC
    )
    INSERT INTO warehouse.fact_payments
        (payment_id, order_id, payment_method_sk, status, amount, currency,
         failure_reason, gateway, paid_at)
    SELECT p.payment_id, p.order_id, pm.payment_method_sk, p.payment_status,
           NULLIF(p.amount, '')::numeric(14,2), p.currency, p.failure_reason, p.gateway,
           NULLIF(p.paid_at, '')::timestamptz
      FROM dedup p
      JOIN warehouse.fact_orders o ON o.order_id = p.order_id
      LEFT JOIN warehouse.dim_payment_method pm ON pm.method_name = p.payment_method
    ON CONFLICT (payment_id) DO NOTHING
    """
    with get_engine().begin() as conn:
        return conn.execute(text(sql)).rowcount or 0


def load_fact_shipments() -> int:
    sql = """
    WITH dedup AS (
        SELECT DISTINCT ON (shipment_id) *
          FROM staging.raw_shipments
         WHERE COALESCE(shipment_id, '') <> ''
         ORDER BY shipment_id, row_id DESC
    )
    INSERT INTO warehouse.fact_shipments
        (shipment_id, order_id, carrier, status, shipped_at, delivered_at,
         transit_days, shipping_cost, processing_hours)
    SELECT s.shipment_id, s.order_id, s.carrier, s.shipment_status,
           NULLIF(s.shipped_at, '')::timestamptz,
           NULLIF(s.delivered_at, '')::timestamptz,
           NULLIF(s.transit_days, '')::int,
           NULLIF(s.shipping_cost, '')::numeric(10,2),
           ROUND(EXTRACT(EPOCH FROM (NULLIF(s.shipped_at, '')::timestamptz - o.order_ts)) / 3600.0, 2)
      FROM dedup s
      JOIN warehouse.fact_orders o ON o.order_id = s.order_id
    ON CONFLICT (shipment_id) DO NOTHING
    """
    with get_engine().begin() as conn:
        return conn.execute(text(sql)).rowcount or 0


def load_fact_returns() -> int:
    sql = """
    WITH dedup AS (
        SELECT DISTINCT ON (return_id) *
          FROM staging.raw_returns
         WHERE COALESCE(return_id, '') <> ''
         ORDER BY return_id, row_id DESC
    )
    INSERT INTO warehouse.fact_returns
        (return_id, order_id, reason, refund_amount, refund_status, return_ts)
    SELECT r.return_id, r.order_id, r.reason,
           NULLIF(r.refund_amount, '')::numeric(14,2), r.refund_status,
           NULLIF(r.return_ts, '')::timestamptz
      FROM dedup r
      JOIN warehouse.fact_orders o ON o.order_id = r.order_id
    ON CONFLICT (return_id) DO NOTHING
    """
    with get_engine().begin() as conn:
        return conn.execute(text(sql)).rowcount or 0


# --------------------------------------------------------------------------- #
# orchestration entrypoint
# --------------------------------------------------------------------------- #
def run_batch(raw_dir: Path = RAW_DIR, rebuild: bool = False) -> dict[str, Any]:
    configure_logging()
    t0 = time.time()
    if rebuild:
        apply_ddl()
    staging = load_staging(raw_dir)

    run_id = start_run("warehouse_dimensional_load", "batch", {"raw_dir": str(raw_dir)})
    try:
        dim_customers = load_dim_customer_scd2()
        dim_products = load_dim_product()
        accepted, rejected, _ = load_fact_orders(run_id)
        items, items_rejected = load_fact_items()
        payments = load_fact_payments()
        shipments = load_fact_shipments()
        returns = load_fact_returns()
        gold_days = backfill_gold()
        result = {
            "run_id": run_id,
            "staging_rows": staging,
            "dim_customer_versions": dim_customers,
            "dim_product_rows": dim_products,
            "fact_orders": accepted,
            "fact_orders_rejected": rejected,
            "fact_order_items": items,
            "fact_order_items_rejected": items_rejected,
            "fact_payments": payments,
            "fact_shipments": shipments,
            "fact_returns": returns,
            "gold_days_refreshed": gold_days,
            "reject_reasons": reject_breakdown(),
            "elapsed_seconds": round(time.time() - t0, 1),
        }
        finish_run(run_id, "success", records_in=sum(staging.values()),
                   records_out=accepted + items, records_rejected=rejected + items_rejected,
                   details=result)
        record_metric("warehouse_orders_loaded", accepted, "records")
        return result
    except Exception as exc:
        finish_run(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true", help="drop and recreate all schemas")
    ap.add_argument("--raw-dir", default=str(RAW_DIR))
    args = ap.parse_args()
    print(json.dumps(run_batch(Path(args.raw_dir), rebuild=args.rebuild), indent=2))
