"""Idempotent warehouse sink for the streaming layer + gold aggregate maintenance.

The batch loader (``warehouse.load``) bulk-loads the historical CSV extract; this
module is the incremental path used by the micro-batch stream processor.  Every
write is an ``INSERT ... ON CONFLICT`` so re-processing a batch (at-least-once
delivery) never duplicates facts.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Iterable

from sqlalchemy import text

from common.db import fetch_one, get_engine

GOLD_DDL = """
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.sales_daily (
    sales_date            DATE PRIMARY KEY,
    orders                INTEGER NOT NULL DEFAULT 0,
    completed_orders      INTEGER NOT NULL DEFAULT 0,
    cancelled_orders      INTEGER NOT NULL DEFAULT 0,
    returned_orders       INTEGER NOT NULL DEFAULT 0,
    units_sold            INTEGER NOT NULL DEFAULT 0,
    gross_revenue         NUMERIC(16, 2) NOT NULL DEFAULT 0,
    discount_amount       NUMERIC(16, 2) NOT NULL DEFAULT 0,
    shipping_revenue      NUMERIC(16, 2) NOT NULL DEFAULT 0,
    net_revenue           NUMERIC(16, 2) NOT NULL DEFAULT 0,
    active_customers      INTEGER NOT NULL DEFAULT 0,
    new_customers         INTEGER NOT NULL DEFAULT 0,
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics.pipeline_watermark (
    pipeline_name  TEXT PRIMARY KEY,
    watermark_ts   TIMESTAMPTZ NOT NULL,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.stream_events (
    event_id      BIGSERIAL PRIMARY KEY,
    topic         TEXT NOT NULL,
    partition     INTEGER NOT NULL,
    offset_no     BIGINT NOT NULL,
    event_key     TEXT,
    event_ts      TIMESTAMPTZ,
    ingest_ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
    layer         TEXT NOT NULL,
    status        TEXT NOT NULL,
    reason        TEXT,
    UNIQUE (topic, partition, offset_no)
);
CREATE INDEX IF NOT EXISTS idx_stream_events_time ON ops.stream_events (ingest_ts DESC);
"""


def ensure_gold_layer() -> None:
    with get_engine().begin() as conn:
        for statement in _split(GOLD_DDL):
            conn.execute(text(statement))


def _split(sql: str) -> Iterable[str]:
    for chunk in sql.split(";"):
        chunk = chunk.strip()
        if chunk:
            yield chunk


def _date_key(ts: datetime) -> int:
    return int(ts.strftime("%Y%m%d"))


def _as_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


UPSERT_ORDER = """
INSERT INTO warehouse.fact_orders (
    order_id, customer_sk, date_key, payment_method_sk, status, channel, currency,
    country, region, item_count, subtotal, discount_total, shipping_total, order_total,
    is_completed, is_cancelled, is_returned, order_ts
) VALUES (
    :order_id, :customer_sk, :date_key, :payment_method_sk, :status, :channel, :currency,
    :country, :region, :item_count, :subtotal, :discount_total, :shipping_total, :order_total,
    :is_completed, :is_cancelled, :is_returned, :order_ts
)
ON CONFLICT (order_id) DO UPDATE SET
    status = EXCLUDED.status,
    order_total = EXCLUDED.order_total,
    subtotal = EXCLUDED.subtotal,
    discount_total = EXCLUDED.discount_total,
    shipping_total = EXCLUDED.shipping_total,
    item_count = EXCLUDED.item_count,
    is_completed = EXCLUDED.is_completed,
    is_cancelled = EXCLUDED.is_cancelled,
    is_returned = EXCLUDED.is_returned,
    ingested_at = now()
"""


def upsert_order(conn, order: dict[str, Any]) -> str:
    ts = _as_dt(order.get("order_ts"))
    if ts is None:
        return "rejected"
    customer_sk = conn.execute(
        text(
            "SELECT customer_sk FROM warehouse.dim_customer "
            "WHERE customer_id = :cid AND is_current ORDER BY customer_sk DESC LIMIT 1"
        ),
        {"cid": order.get("customer_id")},
    ).scalar()
    method_sk = conn.execute(
        text("SELECT payment_method_sk FROM warehouse.dim_payment_method WHERE method_name = :m"),
        {"m": order.get("payment_method")},
    ).scalar()
    status = str(order.get("status") or "pending")
    conn.execute(
        text(UPSERT_ORDER),
        {
            "order_id": order["order_id"],
            "customer_sk": customer_sk,
            "date_key": _date_key(ts),
            "payment_method_sk": method_sk,
            "status": status,
            "channel": order.get("channel"),
            "currency": order.get("currency"),
            "country": order.get("country"),
            "region": order.get("region"),
            "item_count": int(order.get("item_count") or 0),
            "subtotal": float(order.get("subtotal") or 0),
            "discount_total": float(order.get("discount_total") or 0),
            "shipping_total": float(order.get("shipping_total") or 0),
            "order_total": float(order.get("order_total") or 0),
            "is_completed": status == "completed",
            "is_cancelled": status == "cancelled",
            "is_returned": status == "returned",
            "order_ts": ts,
        },
    )
    return "upserted"


def upsert_order_items(conn, order_id: str, items: list[dict[str, Any]]) -> int:
    written = 0
    for index, item in enumerate(items):
        product_sk = conn.execute(
            text("SELECT product_sk FROM warehouse.dim_product WHERE product_id = :pid"),
            {"pid": item.get("product_id")},
        ).scalar()
        if product_sk is None:
            continue
        qty = int(item.get("quantity") or 0)
        price = float(item.get("unit_price") or 0)
        disc = min(max(float(item.get("discount_pct") or 0), 0.0), 1.0)
        line_total = round(qty * price * (1 - disc), 2)
        cost = item.get("unit_cost")
        unit_cost = float(cost) if cost not in (None, "") else None
        conn.execute(
            text(
                """
                INSERT INTO warehouse.fact_order_items (
                    order_item_id, order_id, product_sk, quantity, unit_price,
                    discount_pct, line_total, unit_cost, gross_profit
                ) VALUES (
                    :iid, :oid, :psk, :qty, :price, :disc, :total, :cost, :profit
                )
                ON CONFLICT (order_item_id) DO NOTHING
                """
            ),
            {
                "iid": item.get("order_item_id") or f"{order_id}-{index + 1:02d}",
                "oid": order_id,
                "psk": product_sk,
                "qty": qty,
                "price": price,
                "disc": disc,
                "total": line_total,
                "cost": unit_cost,
                "profit": round(line_total - (unit_cost or 0) * qty, 2) if unit_cost else None,
            },
        )
        written += 1
    return written


def upsert_payment(conn, payment: dict[str, Any]) -> bool:
    method_sk = conn.execute(
        text("SELECT payment_method_sk FROM warehouse.dim_payment_method WHERE method_name = :m"),
        {"m": payment.get("payment_method")},
    ).scalar()
    result = conn.execute(
        text(
            """
            INSERT INTO warehouse.fact_payments (
                payment_id, order_id, payment_method_sk, status, amount,
                currency, failure_reason, gateway, paid_at
            ) VALUES (
                :pid, :oid, :msk, :status, :amount, :currency, :reason, :gateway, :paid_at
            )
            ON CONFLICT (payment_id) DO UPDATE SET
                status = EXCLUDED.status,
                amount = EXCLUDED.amount,
                failure_reason = EXCLUDED.failure_reason,
                paid_at = EXCLUDED.paid_at
            """
        ),
        {
            "pid": payment.get("payment_id"),
            "oid": payment.get("order_id"),
            "msk": method_sk,
            "status": payment.get("payment_status") or payment.get("status"),
            "amount": float(payment.get("amount") or 0),
            "currency": payment.get("currency"),
            "reason": payment.get("failure_reason"),
            "gateway": payment.get("gateway"),
            "paid_at": _as_dt(payment.get("paid_at")),
        },
    )
    return bool(result.rowcount)


def upsert_shipment(conn, shipment: dict[str, Any]) -> bool:
    shipped = _as_dt(shipment.get("shipped_at"))
    delivered = _as_dt(shipment.get("delivered_at"))
    processing_hours = None
    if shipped and delivered:
        processing_hours = round((delivered - shipped).total_seconds() / 3600, 2)
    result = conn.execute(
        text(
            """
            INSERT INTO warehouse.fact_shipments (
                shipment_id, order_id, carrier, status, shipped_at, delivered_at,
                transit_days, shipping_cost, processing_hours
            ) VALUES (
                :sid, :oid, :carrier, :status, :shipped, :delivered,
                :transit, :cost, :hours
            )
            ON CONFLICT (shipment_id) DO UPDATE SET
                status = EXCLUDED.status,
                delivered_at = EXCLUDED.delivered_at,
                processing_hours = EXCLUDED.processing_hours
            """
        ),
        {
            "sid": shipment.get("shipment_id"),
            "oid": shipment.get("order_id"),
            "carrier": shipment.get("carrier"),
            "status": shipment.get("shipment_status") or shipment.get("status"),
            "shipped": shipped,
            "delivered": delivered,
            "transit": int(shipment.get("transit_days") or 0) or None,
            "cost": float(shipment.get("shipping_cost") or 0),
            "hours": processing_hours,
        },
    )
    return bool(result.rowcount)


def upsert_return(conn, ret: dict[str, Any]) -> bool:
    result = conn.execute(
        text(
            """
            INSERT INTO warehouse.fact_returns (
                return_id, order_id, reason, refund_amount, refund_status
            ) VALUES (:rid, :oid, :reason, :amount, :status)
            ON CONFLICT (return_id) DO NOTHING
            """
        ),
        {
            "rid": ret.get("return_id"),
            "oid": ret.get("order_id"),
            "reason": ret.get("reason"),
            "amount": float(ret.get("refund_amount") or 0),
            "status": ret.get("refund_status"),
        },
    )
    return bool(result.rowcount)


REFRESH_GOLD = """
INSERT INTO analytics.sales_daily (
    sales_date, orders, completed_orders, cancelled_orders, returned_orders, units_sold,
    gross_revenue, discount_amount, shipping_revenue, net_revenue,
    active_customers, new_customers, updated_at
)
SELECT
    d.date_actual,
    COUNT(*)                                                        AS orders,
    COUNT(*) FILTER (WHERE f.is_completed)                          AS completed_orders,
    COUNT(*) FILTER (WHERE f.is_cancelled)                          AS cancelled_orders,
    COUNT(*) FILTER (WHERE f.is_returned)                           AS returned_orders,
    COALESCE(SUM(f.item_count), 0)                                  AS units_sold,
    COALESCE(SUM(f.subtotal), 0)                                    AS gross_revenue,
    COALESCE(SUM(f.discount_total), 0)                              AS discount_amount,
    COALESCE(SUM(f.shipping_total), 0)                              AS shipping_revenue,
    COALESCE(SUM(f.order_total), 0)                                 AS net_revenue,
    COUNT(DISTINCT f.customer_sk)                                   AS active_customers,
    COUNT(DISTINCT f.customer_sk) FILTER (
        WHERE f.date_key = c.first_date_key
    )                                                               AS new_customers,
    now()
FROM warehouse.fact_orders f
JOIN warehouse.dim_date d ON d.date_key = f.date_key
JOIN (
    SELECT customer_sk, MIN(date_key) AS first_date_key
    FROM warehouse.fact_orders
    GROUP BY customer_sk
) c ON c.customer_sk = f.customer_sk
WHERE d.date_actual BETWEEN :start_date AND :end_date
GROUP BY d.date_actual
ON CONFLICT (sales_date) DO UPDATE SET
    orders = EXCLUDED.orders,
    completed_orders = EXCLUDED.completed_orders,
    cancelled_orders = EXCLUDED.cancelled_orders,
    returned_orders = EXCLUDED.returned_orders,
    units_sold = EXCLUDED.units_sold,
    gross_revenue = EXCLUDED.gross_revenue,
    discount_amount = EXCLUDED.discount_amount,
    shipping_revenue = EXCLUDED.shipping_revenue,
    net_revenue = EXCLUDED.net_revenue,
    active_customers = EXCLUDED.active_customers,
    new_customers = EXCLUDED.new_customers,
    updated_at = now()
"""


def refresh_gold(dates: Iterable[date]) -> int:
    dates = sorted(set(dates))
    if not dates:
        return 0
    with get_engine().begin() as conn:
        conn.execute(
            text(REFRESH_GOLD),
            {"start_date": min(dates), "end_date": max(dates)},
        )
    return len(dates)


def backfill_gold() -> int:
    """Rebuild every gold day from the full fact table (batch counterpart of the stream sink).

    The streaming job only refreshes the dates it touches, so a fresh warehouse
    load leaves most days missing from ``analytics.sales_daily``.  This performs
    one deterministic full refresh so the gold layer always reconciles 1:1 with
    the warehouse for the whole history.
    """
    ensure_gold_layer()
    row = fetch_one(
        "SELECT MIN(dd.date_actual) AS lo, MAX(dd.date_actual) AS hi "
        "FROM warehouse.fact_orders fo JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key"
    ) or {}
    lo, hi = row.get("lo"), row.get("hi")
    if not lo or not hi:
        return 0
    with get_engine().begin() as conn:
        result = conn.execute(text(REFRESH_GOLD), {"start_date": lo, "end_date": hi})
    return int(result.rowcount or 0)


def set_watermark(name: str, ts: datetime) -> None:
    with get_engine().begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO analytics.pipeline_watermark (pipeline_name, watermark_ts)
                VALUES (:n, :ts)
                ON CONFLICT (pipeline_name) DO UPDATE SET
                    watermark_ts = GREATEST(analytics.pipeline_watermark.watermark_ts, EXCLUDED.watermark_ts),
                    updated_at = now()
                """
            ),
            {"n": name, "ts": ts},
        )


def record_event(
    conn,
    topic: str,
    partition: int,
    offset: int,
    key: str | None,
    event_ts: datetime | None,
    layer: str,
    status: str,
    reason: str | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO ops.stream_events
                (topic, partition, offset_no, event_key, event_ts, layer, status, reason)
            VALUES (:topic, :part, :off, :key, :ts, :layer, :status, :reason)
            ON CONFLICT (topic, partition, offset_no) DO NOTHING
            """
        ),
        {
            "topic": topic,
            "part": partition,
            "off": offset,
            "key": key,
            "ts": event_ts,
            "layer": layer,
            "status": status,
            "reason": reason,
        },
    )
