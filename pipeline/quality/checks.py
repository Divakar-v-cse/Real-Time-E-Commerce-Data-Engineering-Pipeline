"""Data-quality checks executed across the lakehouse layers and the warehouse.

Every check is a small function that returns a :class:`CheckResult`.  Results are
written to ``ops.data_quality_results`` (one row per check per run) and the run is
scored 0-100 by weighting each check by its severity, so a single critical
failure drags the score down faster than a cosmetic warning.

Check catalogue (matches the project specification)
---------------------------------------------------
warehouse:  missing_values, duplicate_records, invalid_order_totals,
            negative_prices, invalid_customer_ids, incorrect_timestamps,
            referential_integrity, data_freshness
lake:       bronze_event_integrity, bronze_missing_values, silver_duplicates,
            silver_negative_values
gold:       gold_reconciliation, gold_freshness
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from common.db import execute, fetch_all, fetch_one
from common.settings import LAKE_DIR, settings

FRESHNESS_WARN_HOURS = 24.0
FRESHNESS_FAIL_HOURS = 72.0


@dataclass
class CheckResult:
    check_name: str
    layer: str
    table_name: str
    severity: str
    records_checked: int
    records_failed: int
    details: str
    status: str = ""

    def __post_init__(self) -> None:
        if not self.status:
            self.status = "failed" if self.records_failed > 0 else "passed"

    @property
    def failure_rate(self) -> float:
        if not self.records_checked:
            return 0.0
        return round(self.records_failed / self.records_checked * 100, 4)

    def as_row(self) -> dict[str, Any]:
        return {
            "check_name": self.check_name,
            "layer": self.layer,
            "table_name": self.table_name,
            "severity": self.severity,
            "status": self.status,
            "records_checked": self.records_checked,
            "records_failed": self.records_failed,
            "failure_rate": self.failure_rate,
            "details": self.details,
        }


def _scalar(sql: str, params: dict[str, Any] | None = None) -> int:
    row = fetch_one(sql, params)
    if not row:
        return 0
    value = next(iter(row.values()))
    return int(value or 0)


# --------------------------------------------------------------------------
# Warehouse checks
# --------------------------------------------------------------------------
def check_missing_values() -> list[CheckResult]:
    total = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.fact_orders
        WHERE order_id IS NULL OR order_ts IS NULL OR date_key IS NULL
           OR status IS NULL OR order_total IS NULL OR customer_sk IS NULL
        """
    )
    results = [
        CheckResult(
            "missing_values", "warehouse", "warehouse.fact_orders", "critical", total, failed,
            f"{failed} order rows have NULL in a mandatory column (order_id, order_ts, date_key, status, order_total, customer_sk).",
        )
    ]
    cust_total = _scalar("SELECT COUNT(*) FROM warehouse.dim_customer WHERE is_current")
    cust_failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.dim_customer
        WHERE is_current AND (email IS NULL OR full_name IS NULL OR region IS NULL OR country IS NULL)
        """
    )
    results.append(
        CheckResult(
            "missing_values", "warehouse", "warehouse.dim_customer", "warning", cust_total, cust_failed,
            f"{cust_failed} current customer rows are missing email / name / region / country.",
        )
    )
    prod_total = _scalar("SELECT COUNT(*) FROM warehouse.dim_product")
    prod_failed = _scalar(
        "SELECT COUNT(*) FROM warehouse.dim_product WHERE product_name IS NULL OR category IS NULL OR unit_price IS NULL"
    )
    results.append(
        CheckResult(
            "missing_values", "warehouse", "warehouse.dim_product", "warning", prod_total, prod_failed,
            f"{prod_failed} product rows are missing name / category / price.",
        )
    )
    return results


def check_duplicates() -> list[CheckResult]:
    total = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    failed = _scalar(
        """
        SELECT COALESCE(SUM(c - 1), 0) FROM (
            SELECT COUNT(*) AS c FROM warehouse.fact_orders GROUP BY order_id HAVING COUNT(*) > 1
        ) d
        """
    )
    items_total = _scalar("SELECT COUNT(*) FROM warehouse.fact_order_items")
    items_failed = _scalar(
        """
        SELECT COALESCE(SUM(c - 1), 0) FROM (
            SELECT COUNT(*) AS c FROM warehouse.fact_order_items GROUP BY order_item_id HAVING COUNT(*) > 1
        ) d
        """
    )
    return [
        CheckResult(
            "duplicate_records", "warehouse", "warehouse.fact_orders", "critical", total, failed,
            f"{failed} duplicate order_id rows found in fact_orders (business key must be unique).",
        ),
        CheckResult(
            "duplicate_records", "warehouse", "warehouse.fact_order_items", "critical", items_total, items_failed,
            f"{items_failed} duplicate order_item_id rows found in fact_order_items.",
        ),
    ]


def check_order_totals() -> list[CheckResult]:
    total = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.fact_orders
        WHERE ABS(order_total - (subtotal - discount_total + shipping_total)) > 0.02
        """
    )
    quarantined = _scalar(
        "SELECT COUNT(*) FROM ops.rejected_records WHERE reason = 'invalid_order_total'"
    )
    return [
        CheckResult(
            "invalid_order_totals", "warehouse", "warehouse.fact_orders", "critical", total, failed,
            "Rows where order_total != subtotal - discount_total + shipping_total (tolerance 0.02). "
            f"{quarantined} source rows that broke this identity were quarantined at load time.",
        )
    ]


def check_quarantine() -> list[CheckResult]:
    """Every distinct source order must be either in the warehouse or in the reject ledger."""
    source = _scalar(
        "SELECT COUNT(DISTINCT order_id) FROM staging.raw_orders WHERE COALESCE(order_id, '') <> ''"
    )
    accepted = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    rejected = _scalar("SELECT COUNT(*) FROM ops.rejected_records")
    failed = abs(source - (accepted + rejected))
    reasons = fetch_all(
        "SELECT reason, COUNT(*) AS n FROM ops.rejected_records GROUP BY reason ORDER BY n DESC"
    )
    breakdown = ", ".join(f"{r['reason']}={r['n']}" for r in reasons) or "no rejects"
    return [
        CheckResult(
            "quarantine_reconciliation", "warehouse", "ops.rejected_records", "critical", source, failed,
            f"{source} distinct source orders = {accepted} accepted + {rejected} quarantined; "
            f"unaccounted rows: {failed}. Reasons: {breakdown}.",
        )
    ]


def check_negative_values() -> list[CheckResult]:
    total = _scalar("SELECT COUNT(*) FROM warehouse.fact_order_items")
    failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.fact_order_items
        WHERE unit_price < 0 OR line_total < 0 OR quantity <= 0
           OR discount_pct < 0 OR discount_pct > 1
        """
    )
    orders_total = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    orders_failed = _scalar(
        "SELECT COUNT(*) FROM warehouse.fact_orders WHERE order_total < 0 OR subtotal < 0"
    )
    prod_total = _scalar("SELECT COUNT(*) FROM warehouse.dim_product")
    prod_failed = _scalar("SELECT COUNT(*) FROM warehouse.dim_product WHERE unit_price < 0 OR unit_cost < 0")
    return [
        CheckResult(
            "negative_prices", "warehouse", "warehouse.fact_order_items", "critical", total, failed,
            "Line items with a negative price / total, non-positive quantity, or discount outside [0,1].",
        ),
        CheckResult(
            "negative_prices", "warehouse", "warehouse.fact_orders", "critical", orders_total, orders_failed,
            "Orders with a negative total or subtotal.",
        ),
        CheckResult(
            "negative_prices", "warehouse", "warehouse.dim_product", "warning", prod_total, prod_failed,
            "Products with a negative price or cost.",
        ),
    ]


def check_customer_ids() -> list[CheckResult]:
    total = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.fact_orders fo
        LEFT JOIN warehouse.dim_customer dc ON dc.customer_sk = fo.customer_sk
        WHERE fo.customer_sk IS NULL OR dc.customer_sk IS NULL
        """
    )
    key_total = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    key_failed = _scalar(
        "SELECT COUNT(*) FROM warehouse.fact_orders WHERE order_id !~ '^O[0-9]{15}$'"
    )
    return [
        CheckResult(
            "invalid_customer_ids", "warehouse", "warehouse.fact_orders", "critical", total, failed,
            "Orders whose customer_sk does not resolve to a dim_customer row.",
        ),
        CheckResult(
            "invalid_customer_ids", "warehouse", "warehouse.fact_orders", "warning", key_total, key_failed,
            "Orders whose order_id does not match the O + YYYYMMDD + 7 digits pattern.",
        ),
    ]


def check_timestamps() -> list[CheckResult]:
    total = _scalar("SELECT COUNT(*) FROM warehouse.fact_orders")
    failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.fact_orders fo
        JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key
        WHERE fo.order_ts::date <> dd.date_actual
           OR fo.order_ts > now() + interval '1 day'
           OR fo.order_ts < TIMESTAMP '2020-01-01'
        """
    )
    pay_total = _scalar("SELECT COUNT(*) FROM warehouse.fact_payments")
    pay_failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.fact_payments p
        JOIN warehouse.fact_orders o ON o.order_id = p.order_id
        WHERE p.paid_at IS NOT NULL AND p.paid_at < o.order_ts - interval '1 minute'
        """
    )
    ship_total = _scalar("SELECT COUNT(*) FROM warehouse.fact_shipments")
    ship_failed = _scalar(
        """
        SELECT COUNT(*) FROM warehouse.fact_shipments
        WHERE (delivered_at IS NOT NULL AND shipped_at IS NOT NULL AND delivered_at < shipped_at)
           OR processing_hours < 0
        """
    )
    return [
        CheckResult(
            "incorrect_timestamps", "warehouse", "warehouse.fact_orders", "critical", total, failed,
            "Order timestamps not aligned with dim_date, in the future, or before 2020.",
        ),
        CheckResult(
            "incorrect_timestamps", "warehouse", "warehouse.fact_payments", "warning", pay_total, pay_failed,
            "Payments recorded before the corresponding order was placed.",
        ),
        CheckResult(
            "incorrect_timestamps", "warehouse", "warehouse.fact_shipments", "warning", ship_total, ship_failed,
            "Shipments delivered before they were shipped, or negative processing time.",
        ),
    ]


def check_referential_integrity() -> list[CheckResult]:
    specs = [
        ("warehouse.fact_order_items", "product_sk", "warehouse.dim_product", "product_sk", "critical"),
        ("warehouse.fact_order_items", "order_id", "warehouse.fact_orders", "order_id", "critical"),
        ("warehouse.fact_payments", "order_id", "warehouse.fact_orders", "order_id", "critical"),
        ("warehouse.fact_payments", "payment_method_sk", "warehouse.dim_payment_method", "payment_method_sk", "warning"),
        ("warehouse.fact_shipments", "order_id", "warehouse.fact_orders", "order_id", "critical"),
        ("warehouse.fact_returns", "order_id", "warehouse.fact_orders", "order_id", "critical"),
    ]
    results: list[CheckResult] = []
    for child, fk, parent, pk, severity in specs:
        where = f"c.{fk} IS NULL OR p.{pk} IS NULL" if fk != "order_id" else "c.order_id IS NULL OR p.order_id IS NULL"
        total = _scalar(f"SELECT COUNT(*) FROM {child}")
        failed = _scalar(
            f"SELECT COUNT(*) FROM {child} c LEFT JOIN {parent} p ON p.{pk} = c.{fk} WHERE {where}"
        )
        results.append(
            CheckResult(
                "referential_integrity", "warehouse", child, severity, total, failed,
                f"{failed} rows in {child} reference a missing {parent}.{pk} (FK {fk}).",
            )
        )
    return results


def check_freshness() -> list[CheckResult]:
    row = fetch_one(
        """
        SELECT MAX(order_ts) AS latest,
               EXTRACT(EPOCH FROM (now() - MAX(order_ts))) / 3600.0 AS lag_hours
        FROM warehouse.fact_orders
        """
    ) or {}
    lag = float(row.get("lag_hours") or 0)
    latest = row.get("latest")
    status = "passed" if lag <= FRESHNESS_WARN_HOURS else "failed"
    return [
        CheckResult(
            "data_freshness", "warehouse", "warehouse.fact_orders",
            "critical" if lag > FRESHNESS_FAIL_HOURS else "warning",
            1, 0 if status == "passed" else 1,
            f"Latest warehouse order at {latest}; lag {lag:.1f}h (warn > {FRESHNESS_WARN_HOURS:.0f}h, fail > {FRESHNESS_FAIL_HOURS:.0f}h).",
            status=status,
        )
    ]


# --------------------------------------------------------------------------
# Lake (bronze / silver) checks
# --------------------------------------------------------------------------
def _lake_files(layer: str) -> list[Path]:
    base = LAKE_DIR / layer
    if not base.exists():
        return []
    return sorted(base.rglob("*.parquet"))


def _read_layer(layer: str):
    import pandas as pd  # imported lazily so the API does not need it

    files = _lake_files(layer)
    if not files:
        return None, 0
    frames = []
    for f in files:
        frame = pd.read_parquet(f)
        # Older partitions pre-date the ``_kafka_topic`` column; recover the topic
        # from the hive-style path ``<layer>/<topic>/dt=YYYY-MM-DD/part-*.parquet``.
        if "_kafka_topic" not in frame.columns:
            frame["_kafka_topic"] = f.parent.parent.name
        frames.append(frame)
    return pd.concat(frames, ignore_index=True), len(files)


# Envelope contract per topic: a shipment event legitimately has no ``event_id``.
_TOPIC_KEYS: dict[str, tuple[str, ...]] = {
    "ecom.orders.raw": ("event_id", "event_type", "order_id", "order_ts"),
    "ecom.payments.raw": ("payment_id", "order_id", "payment_status"),
    "ecom.shipments.raw": ("shipment_id", "order_id", "shipment_status"),
    "ecom.returns.raw": ("return_id", "order_id", "reason"),
}


def check_bronze() -> list[CheckResult]:
    df, file_count = _read_layer("bronze")
    if df is None:
        return [CheckResult("bronze_event_integrity", "bronze", "s3://lake/bronze", "warning", 0, 0,
                            "No bronze partitions found yet.", status="passed")]
    total = int(len(df))
    missing = 0
    per_topic = []
    for topic, keys in _TOPIC_KEYS.items():
        sub = df[df["_kafka_topic"] == topic] if "_kafka_topic" in df.columns else df
        if sub.empty:
            continue
        required = [c for c in keys if c in sub.columns]
        absent = [c for c in keys if c not in sub.columns]
        gaps = sum(int(sub[c].isna().sum()) for c in required)
        # A column that is entirely absent counts every row in that partition as a violation.
        gaps += len(sub) * len(absent)
        missing += gaps
        per_topic.append(f"{topic}={len(sub)} rows/{gaps} gaps")
    dup = 0
    key_cols = [c for c in ("_kafka_topic", "_kafka_partition", "_kafka_offset") if c in df.columns]
    if len(key_cols) == 3:
        dup = int(df.duplicated(subset=key_cols).sum())
    return [
        CheckResult("bronze_missing_values", "bronze", "s3://lake/bronze", "critical", total, missing,
                    f"{file_count} bronze partitions, {total} raw events; missing envelope values per topic: "
                    + ", ".join(per_topic) + ".",
                    status="failed" if missing else "passed"),
        CheckResult("bronze_duplicates", "bronze", "s3://lake/bronze", "warning", total, dup,
                    f"{dup} duplicate (topic, partition, offset) triples in bronze "
                    "(at-least-once replay of the same Kafka offset)."),
    ]


def check_silver() -> list[CheckResult]:
    df, file_count = _read_layer("silver")
    if df is None:
        return [CheckResult("silver_duplicates", "silver", "s3://lake/silver", "warning", 0, 0,
                            "No silver partitions found yet.", status="passed")]
    total = int(len(df))
    dup = int(df.duplicated(subset=["order_id"]).sum()) if "order_id" in df.columns else 0
    neg = 0
    for col in ("order_total", "subtotal"):
        if col in df.columns:
            neg += int((df[col].fillna(0) < 0).sum())
    return [
        CheckResult("silver_duplicates", "silver", "s3://lake/silver", "critical", total, dup,
                    f"{file_count} silver partitions, {total} validated records; {dup} duplicate order_id values.",
                    status="failed" if dup else "passed"),
        CheckResult("silver_negative_values", "silver", "s3://lake/silver", "critical", total, neg,
                    f"{neg} silver records with a negative monetary value."),
    ]


# --------------------------------------------------------------------------
# Gold reconciliation
# --------------------------------------------------------------------------
def check_gold() -> list[CheckResult]:
    """Reconcile the gold layer against the warehouse, day by day.

    A gold day may fail for two distinct reasons, both counted separately so the
    message is actionable: the day is **missing** from the gold table (the
    streaming job only refreshes the days it touches), or the day exists but its
    revenue does not match ``SUM(fact_orders.order_total)``.
    """
    row = fetch_one(
        """
        WITH f AS (
            SELECT dd.date_actual AS d,
                   SUM(fo.order_total) AS revenue,
                   SUM(fo.subtotal) AS gross,
                   COUNT(*) AS orders
            FROM warehouse.fact_orders fo
            JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key
            GROUP BY dd.date_actual
        )
        SELECT COUNT(*) AS checked,
               COUNT(*) FILTER (WHERE s.sales_date IS NULL) AS missing,
               COUNT(*) FILTER (
                    WHERE s.sales_date IS NOT NULL
                      AND (ABS(COALESCE(s.net_revenue, 0) - f.revenue) > 1.0
                           OR ABS(COALESCE(s.gross_revenue, 0) - f.gross) > 1.0
                           OR COALESCE(s.orders, 0) <> f.orders)
               ) AS mismatched
        FROM f
        LEFT JOIN analytics.sales_daily s ON s.sales_date = f.d
        """
    ) or {}
    checked = int(row.get("checked") or 0)
    missing = int(row.get("missing") or 0)
    mismatched = int(row.get("mismatched") or 0)
    failed = missing + mismatched

    gold_row = fetch_one(
        "SELECT MAX(sales_date) AS latest_day, COUNT(*) AS n, MAX(updated_at) AS updated "
        "FROM analytics.sales_daily"
    ) or {}
    fact_row = fetch_one(
        "SELECT MAX(dd.date_actual) AS latest_day FROM warehouse.fact_orders fo "
        "JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key"
    ) or {}
    gold_latest = gold_row.get("latest_day")
    fact_latest = fact_row.get("latest_day")
    stale = 1 if (fact_latest and gold_latest and gold_latest < fact_latest) else 0
    return [
        CheckResult("gold_reconciliation", "gold", "analytics.sales_daily", "critical", checked, failed,
                    f"{checked} fact days reconciled to analytics.sales_daily: {missing} missing, "
                    f"{mismatched} with revenue/order-count drift > 1.00.",
                    status="failed" if failed else "passed"),
        CheckResult("gold_freshness", "gold", "analytics.sales_daily", "warning", 1, stale,
                    f"{int(gold_row.get('n') or 0)} gold day rows; latest gold day {gold_latest}, "
                    f"latest fact day {fact_latest} (last refresh {gold_row.get('updated')}).",
                    status="failed" if stale else "passed"),
    ]


CHECK_GROUPS: dict[str, Callable[[], list[CheckResult]]] = {
    "warehouse": lambda: (
        check_missing_values()
        + check_duplicates()
        + check_order_totals()
        + check_negative_values()
        + check_customer_ids()
        + check_timestamps()
         + check_referential_integrity()
        + check_quarantine()
        + check_freshness()
    ),
    "lake": lambda: check_bronze() + check_silver(),
    "gold": check_gold,
}


def run_checks(groups: list[str] | None = None) -> dict[str, Any]:
    """Execute the selected check groups and persist results."""
    selected = groups or ["warehouse", "lake", "gold"]
    run_at = datetime.now(timezone.utc)
    results: list[CheckResult] = []
    for group in selected:
        fn = CHECK_GROUPS.get(group)
        if fn:
            try:
                results.extend(fn())
            except Exception as exc:  # a broken check must not abort the suite
                results.append(
                    CheckResult(f"{group}_check_error", group, "-", "warning", 0, 1,
                                f"Check group {group} raised {type(exc).__name__}: {exc}", status="failed")
                )
    if not results:
        return {"run_at": run_at.isoformat(), "checks": [], "score": 100.0}

    payload = [r.as_row() for r in results]
    execute(
        """
        INSERT INTO ops.data_quality_results
            (check_name, layer, table_name, severity, status, records_checked, records_failed, failure_rate, details, run_at)
        SELECT x.check_name, x.layer, x.table_name, x.severity, x.status,
               x.records_checked, x.records_failed, x.failure_rate, x.details, :run_at
        FROM jsonb_to_recordset(CAST(:payload AS jsonb)) AS x(
            check_name TEXT, layer TEXT, table_name TEXT, severity TEXT, status TEXT,
            records_checked BIGINT, records_failed BIGINT, failure_rate NUMERIC, details TEXT
        )
        """,
        {"payload": json.dumps(payload), "run_at": run_at},
    )
    score = score_results(results)
    return {
        "run_at": run_at.isoformat(),
        "score": score,
        "checks": payload,
        "passed": sum(1 for r in results if r.status == "passed"),
        "failed": sum(1 for r in results if r.status == "failed"),
    }


def score_results(results: list[CheckResult]) -> float:
    weight_sum = 0.0
    weighted = 0.0
    for r in results:
        weight = 2.0 if r.severity == "critical" else 1.0
        weight_sum += weight
        frac = min(1.0, (r.records_failed / r.records_checked) if r.records_checked else (1.0 if r.status == "failed" else 0.0))
        weighted += weight * (1.0 - frac)
    return round(weighted / weight_sum * 100, 2) if weight_sum else 100.0


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Run data-quality checks")
    parser.add_argument("--groups", default="warehouse,lake,gold")
    args = parser.parse_args()
    groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    out = run_checks(groups)
    print(json.dumps({k: v for k, v in out.items() if k != "checks"}, indent=2))
    for row in out["checks"]:
        print(f"  [{row['status']:6s}] {row['layer']:9s} {row['check_name']:26s} {row['records_failed']}/{row['records_checked']} failed")


if __name__ == "__main__":
    main()

