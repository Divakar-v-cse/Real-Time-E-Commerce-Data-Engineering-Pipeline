"""Executive dashboard: headline KPIs, revenue trend, mixes and recent orders."""
from __future__ import annotations

from typing import Any

from analytics.base import SCOPE_CTE, Window, cached, change_pct, money, one, query, rate, scalar

_KPI_SQL = SCOPE_CTE + """
SELECT
    COUNT(*)                                                AS total_orders,
    COUNT(*) FILTER (WHERE status <> 'cancelled')           AS valid_orders,
    COUNT(*) FILTER (WHERE is_completed)                    AS completed_orders,
    COUNT(*) FILTER (WHERE is_cancelled)                     AS cancelled_orders,
    COUNT(*) FILTER (WHERE is_returned)                      AS returned_orders,
    COALESCE(SUM(order_total) FILTER (WHERE status <> 'cancelled'), 0)  AS revenue,
    COALESCE(SUM(item_count) FILTER (WHERE status <> 'cancelled'), 0)   AS units,
    COUNT(DISTINCT customer_sk)                             AS active_customers,
    COALESCE(SUM(discount_total), 0)                        AS discount_total
FROM scoped
"""

# A customer counts as "new" when their *first ever* order falls inside the window,
# so the lookup uses the full fact table rather than the scoped slice.
_NEW_CUSTOMERS_SQL = SCOPE_CTE + """
, first_orders AS (
    SELECT fo.customer_sk, MIN(fo.order_ts)::date AS first_date
    FROM warehouse.fact_orders fo
    WHERE fo.customer_sk IN (SELECT customer_sk FROM scoped)
    GROUP BY fo.customer_sk
)
SELECT COUNT(*) AS new_customers
FROM first_orders
WHERE first_date BETWEEN :start_date AND :end_date
"""

_PROFIT_SQL = SCOPE_CTE + """
SELECT
    COALESCE(SUM(foi.gross_profit), 0) AS gross_profit,
    COALESCE(SUM(foi.line_total), 0)   AS item_revenue
FROM scoped s
JOIN warehouse.fact_order_items foi ON foi.order_id = s.order_id
WHERE s.status <> 'cancelled'
"""

_PAYMENT_SQL = SCOPE_CTE + """
SELECT
    COUNT(*)                                                   AS attempts,
    COUNT(*) FILTER (WHERE pay.status = 'success')             AS successes
FROM scoped s
JOIN warehouse.fact_payments pay ON pay.order_id = s.order_id
"""


def _kpis(window: Window) -> dict[str, Any]:
    current = one(_KPI_SQL, window)
    previous = one(_KPI_SQL, window.previous())

    new_customers = scalar(_NEW_CUSTOMERS_SQL, window) or 0
    profit = one(_PROFIT_SQL, window)
    payments = one(_PAYMENT_SQL, window)

    revenue = money(current.get("revenue"))
    orders = int(current.get("total_orders") or 0)
    valid_orders = int(current.get("valid_orders") or 0)
    aov = round(revenue / valid_orders, 2) if valid_orders else 0.0

    prev_revenue = money(previous.get("revenue"))
    prev_orders = int(previous.get("total_orders") or 0)
    prev_valid = int(previous.get("valid_orders") or 0)
    prev_aov = round(prev_revenue / prev_valid, 2) if prev_valid else 0.0

    gross_profit = money(profit.get("gross_profit"))

    return {
        "total_revenue": revenue,
        "revenue_change_pct": change_pct(revenue, prev_revenue),
        "total_orders": orders,
        "orders_change_pct": change_pct(orders, prev_orders),
        "average_order_value": aov,
        "aov_change_pct": change_pct(aov, prev_aov),
        "total_customers": int(current.get("active_customers") or 0),
        "new_customers": int(new_customers),
        "total_products": int(scalar("SELECT COUNT(*) FROM warehouse.dim_product WHERE is_active", window) or 0),
        "order_completion_rate": rate(current.get("completed_orders"), orders),
        "payment_success_rate": rate(payments.get("successes"), payments.get("attempts")),
        "return_rate": rate(current.get("returned_orders"), orders),
        "total_units": int(current.get("units") or 0),
        "gross_profit": gross_profit,
        "gross_margin_pct": rate(gross_profit, profit.get("item_revenue")),
    }


def _trend(window: Window) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT
        CASE WHEN :bucket = 'week' THEN date_trunc('week', order_date)::date
             ELSE order_date END AS bucket,
        COALESCE(SUM(order_total) FILTER (WHERE status <> 'cancelled'), 0) AS revenue,
        COUNT(*) AS orders
    FROM scoped
    GROUP BY 1
    ORDER BY 1
    """
    bucket = "week" if window.days > 120 else "day"
    rows = query(sql, window, {"bucket": bucket})
    return [
        {
            "date": r["bucket"].isoformat() if hasattr(r["bucket"], "isoformat") else str(r["bucket"]),
            "revenue": money(r["revenue"]),
            "orders": int(r["orders"] or 0),
        }
        for r in rows
    ]


def _status(window: Window) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT status, COUNT(*) AS orders, COALESCE(SUM(order_total), 0) AS revenue
    FROM scoped
    GROUP BY status
    ORDER BY orders DESC
    """
    rows = query(sql, window)
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


def _categories(window: Window, limit: int = 8) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    , items AS (
        SELECT s.order_id, s.order_total, s.discount_total,
               p.category, foi.quantity, foi.line_total, foi.discount_pct
        FROM scoped s
        JOIN warehouse.fact_order_items foi ON foi.order_id = s.order_id
        JOIN warehouse.dim_product p ON p.product_sk = foi.product_sk
        WHERE s.status <> 'cancelled'
    )
    SELECT category,
           COALESCE(SUM(line_total), 0)          AS revenue,
           COUNT(DISTINCT order_id)              AS orders,
           COALESCE(SUM(quantity), 0)            AS units,
           COALESCE(AVG(discount_pct) * 100, 0)  AS avg_discount_pct
    FROM items
    GROUP BY category
    ORDER BY revenue DESC
    LIMIT :limit
    """
    rows = query(sql, window, {"limit": limit})
    total = sum(float(r["revenue"] or 0) for r in rows) or 1
    return [
        {
            "category": r["category"] or "Uncategorised",
            "revenue": money(r["revenue"]),
            "orders": int(r["orders"] or 0),
            "units": int(r["units"] or 0),
            "share": rate(r["revenue"], total),
            "avg_discount_pct": round(float(r["avg_discount_pct"] or 0), 2),
        }
        for r in rows
    ]


def _regions(window: Window, limit: int = 8) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT region,
           COALESCE(SUM(order_total) FILTER (WHERE status <> 'cancelled'), 0) AS revenue,
           COUNT(*) AS orders,
           COALESCE(SUM(item_count), 0) AS units
    FROM scoped
    GROUP BY region
    ORDER BY revenue DESC
    LIMIT :limit
    """
    rows = query(sql, window, {"limit": limit})
    total = sum(float(r["revenue"] or 0) for r in rows) or 1
    return [
        {
            "region": r["region"] or "Unknown",
            "revenue": money(r["revenue"]),
            "orders": int(r["orders"] or 0),
            "units": int(r["units"] or 0),
            "share": rate(r["revenue"], total),
        }
        for r in rows
    ]


def _recent_orders(window: Window, limit: int = 8) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT s.order_id, s.order_ts, s.country, s.region, s.status,
           s.order_total, s.item_count, c.full_name
    FROM scoped s
    LEFT JOIN warehouse.dim_customer c ON c.customer_sk = s.customer_sk
    ORDER BY s.order_ts DESC
    LIMIT :limit
    """
    rows = query(sql, window, {"limit": limit})
    return [
        {
            "order_id": r["order_id"],
            "order_ts": r["order_ts"].isoformat() if r["order_ts"] else "",
            "customer": r["full_name"] or "Guest",
            "country": r["country"] or "",
            "region": r["region"] or "",
            "status": r["status"] or "unknown",
            "total": money(r["order_total"]),
            "items": int(r["item_count"] or 0),
        }
        for r in rows
    ]


def get_overview(window: Window) -> dict[str, Any]:
    key = f"overview:{window}"
    return cached(
        key,
        lambda: {
            "period": window.as_dict(),
            "kpis": _kpis(window),
            "revenue_trend": _trend(window),
            "status_breakdown": _status(window),
            "top_categories": _categories(window),
            "top_regions": _regions(window),
            "recent_orders": _recent_orders(window),
        },
    )
