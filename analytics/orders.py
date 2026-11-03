"""Order analytics: status mix, fulfilment performance, funnel and payment failures."""
from __future__ import annotations

from typing import Any

from analytics.base import SCOPE_CTE, Window, cached, money, one, query, rate

_STATUS_SQL = SCOPE_CTE + """
SELECT status, COUNT(*) AS orders, COALESCE(SUM(order_total), 0) AS revenue
FROM scoped
GROUP BY status
ORDER BY orders DESC
"""

_DAILY_SQL = SCOPE_CTE + """
SELECT order_date,
       COUNT(*) FILTER (WHERE status = 'completed') AS completed,
       COUNT(*) FILTER (WHERE status = 'cancelled') AS cancelled,
       COUNT(*) FILTER (WHERE status = 'returned')  AS returned,
       COUNT(*) FILTER (WHERE status IN ('pending', 'processing')) AS pending
FROM scoped
GROUP BY order_date
ORDER BY order_date
"""


def _status_counts(window: Window) -> list[dict[str, Any]]:
    rows = query(_STATUS_SQL, window)
    total = sum(int(r["orders"] or 0) for r in rows) or 1
    return [
        {
            "status": r["status"] or "unknown",
            "orders": int(r["orders"] or 0),
            "revenue": money(r["revenue"]),
            "share": rate(r["orders"], total),
        }
        for r in rows
    ]


def _daily_status(window: Window) -> list[dict[str, Any]]:
    rows = query(_DAILY_SQL, window)
    if len(rows) > 45:  # keep the stacked chart readable
        rows = rows[-45:]
    return [
        {
            "date": r["order_date"].isoformat() if hasattr(r["order_date"], "isoformat") else str(r["order_date"]),
            "completed": int(r["completed"] or 0),
            "cancelled": int(r["cancelled"] or 0),
            "returned": int(r["returned"] or 0),
            "pending": int(r["pending"] or 0),
        }
        for r in rows
    ]


def _fulfilment(window: Window) -> dict[str, Any]:
    sql = SCOPE_CTE + """
    SELECT
        AVG(sh.processing_hours)                                       AS avg_processing_hours,
        AVG(sh.transit_days)                                           AS avg_delivery_days,
        100.0 * COUNT(*) FILTER (WHERE sh.transit_days <= 4) / NULLIF(COUNT(*), 0) AS on_time_rate
    FROM scoped s
    JOIN warehouse.fact_shipments sh ON sh.order_id = s.order_id
    WHERE sh.delivered_at IS NOT NULL
    """
    row = one(sql, window)
    return {
        "avg_processing_hours": round(float(row.get("avg_processing_hours") or 0), 2),
        "avg_delivery_days": round(float(row.get("avg_delivery_days") or 0), 2),
        "on_time_rate": round(float(row.get("on_time_rate") or 0), 2),
    }


def _funnel(window: Window) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT
        COUNT(*)                                        AS placed,
        COUNT(*) FILTER (WHERE pay.status = 'success')  AS paid,
        COUNT(*) FILTER (WHERE sh.shipment_id IS NOT NULL) AS shipped,
        COUNT(*) FILTER (WHERE sh.delivered_at IS NOT NULL) AS delivered
    FROM scoped s
    LEFT JOIN warehouse.fact_payments pay ON pay.order_id = s.order_id
    LEFT JOIN warehouse.fact_shipments sh ON sh.order_id = s.order_id
    """
    row = one(sql, window)
    placed = int(row.get("placed") or 0) or 1
    stages = [
        ("Orders placed", int(row.get("placed") or 0)),
        ("Payment captured", int(row.get("paid") or 0)),
        ("Shipped", int(row.get("shipped") or 0)),
        ("Delivered", int(row.get("delivered") or 0)),
    ]
    return [
        {"stage": name, "orders": count, "conversion": rate(count, placed)} for name, count in stages
    ]


def _payment_failures(window: Window) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT COALESCE(pay.failure_reason, 'Unknown') AS reason, COUNT(*) AS count
    FROM scoped s
    JOIN warehouse.fact_payments pay ON pay.order_id = s.order_id
    WHERE pay.status <> 'success'
    GROUP BY 1
    ORDER BY count DESC
    LIMIT 8
    """
    rows = query(sql, window)
    total = sum(int(r["count"] or 0) for r in rows) or 1
    return [
        {"reason": r["reason"], "count": int(r["count"] or 0), "share": rate(r["count"], total)}
        for r in rows
    ]


def get_orders(window: Window) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        fulfilment = _fulfilment(window)
        return {
            "status_counts": _status_counts(window),
            "daily_status": _daily_status(window),
            "avg_processing_hours": fulfilment["avg_processing_hours"],
            "avg_delivery_days": fulfilment["avg_delivery_days"],
            "on_time_rate": fulfilment["on_time_rate"],
            "funnel": _funnel(window),
            "payment_failures": _payment_failures(window),
        }

    return cached(f"orders:{window}", build)
