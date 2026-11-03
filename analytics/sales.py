"""Sales analytics: time series, growth, category/region/payment mix, discount impact."""
from __future__ import annotations

from typing import Any

from analytics.base import SCOPE_CTE, Window, cached, change_pct, money, one, query, rate

_BUCKETS = {"day": "day", "week": "week", "month": "month"}


def _granularity(window: Window, requested: str | None) -> str:
    if requested in _BUCKETS:
        return requested  # type: ignore[return-value]
    if window.days <= 62:
        return "day"
    if window.days <= 400:
        return "week"
    return "month"


def _series(window: Window, granularity: str) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT
        date_trunc(:granularity, order_date)::date AS bucket,
        COALESCE(SUM(order_total) FILTER (WHERE status <> 'cancelled'), 0) AS revenue,
        COUNT(*) AS orders,
        COALESCE(SUM(item_count) FILTER (WHERE status <> 'cancelled'), 0) AS units,
        COALESCE(SUM(discount_total), 0) AS discount
    FROM scoped
    GROUP BY 1
    ORDER BY 1
    """
    rows = query(sql, window, {"granularity": granularity})
    return [
        {
            "period": r["bucket"].isoformat() if hasattr(r["bucket"], "isoformat") else str(r["bucket"]),
            "revenue": money(r["revenue"]),
            "orders": int(r["orders"] or 0),
            "units": int(r["units"] or 0),
            "discount": money(r["discount"]),
        }
        for r in rows
    ]


def _by_payment(window: Window) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT pm.display_name AS payment_method,
           COALESCE(SUM(s.order_total) FILTER (WHERE s.status <> 'cancelled'), 0) AS revenue,
           COUNT(*) AS orders
    FROM scoped s
    LEFT JOIN warehouse.dim_payment_method pm ON pm.payment_method_sk = s.payment_method_sk
    GROUP BY pm.display_name
    ORDER BY revenue DESC
    """
    rows = query(sql, window)
    total = sum(float(r["revenue"] or 0) for r in rows) or 1
    return [
        {
            "payment_method": r["payment_method"] or "Unknown",
            "revenue": money(r["revenue"]),
            "orders": int(r["orders"] or 0),
            "share": rate(r["revenue"], total),
        }
        for r in rows
    ]


def _top_products(window: Window, limit: int = 10) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT p.product_id, p.product_name, p.category,
           COALESCE(SUM(foi.line_total), 0) AS revenue,
           COALESCE(SUM(foi.quantity), 0)   AS units,
           COUNT(DISTINCT s.order_id)       AS orders
    FROM scoped s
    JOIN warehouse.fact_order_items foi ON foi.order_id = s.order_id
    JOIN warehouse.dim_product p ON p.product_sk = foi.product_sk
    WHERE s.status <> 'cancelled'
    GROUP BY p.product_id, p.product_name, p.category
    ORDER BY revenue DESC
    LIMIT :limit
    """
    rows = query(sql, window, {"limit": limit})
    return [
        {
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "category": r["category"],
            "revenue": money(r["revenue"]),
            "units": int(r["units"] or 0),
            "orders": int(r["orders"] or 0),
        }
        for r in rows
    ]


def _discount_impact(window: Window) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    , banded AS (
        SELECT order_total,
               CASE
                   WHEN subtotal IS NULL OR subtotal = 0 THEN '0%'
                   WHEN discount_total / subtotal <= 0.001 THEN '0%'
                   WHEN discount_total / subtotal <= 0.10 THEN '1-10%'
                   WHEN discount_total / subtotal <= 0.25 THEN '11-25%'
                   WHEN discount_total / subtotal <= 0.40 THEN '26-40%'
                   ELSE '40%+'
               END AS band
        FROM scoped
        WHERE status <> 'cancelled'
    )
    SELECT band, COALESCE(SUM(order_total), 0) AS revenue, COUNT(*) AS orders
    FROM banded
    GROUP BY band
    """
    rows = query(sql, window)
    total = sum(float(r["revenue"] or 0) for r in rows) or 1
    order = {"0%": 0, "1-10%": 1, "11-25%": 2, "26-40%": 3, "40%+": 4}
    result = [
        {
            "band": r["band"],
            "revenue": money(r["revenue"]),
            "orders": int(r["orders"] or 0),
            "aov": round(float(r["revenue"] or 0) / int(r["orders"] or 1), 2),
            "share": rate(r["revenue"], total),
        }
        for r in rows
    ]
    return sorted(result, key=lambda r: order.get(r["band"], 9))


def get_sales(window: Window, granularity: str | None = None) -> dict[str, Any]:
    from analytics.overview import _categories, _regions

    gran = _granularity(window, granularity)

    def build() -> dict[str, Any]:
        current = one(
            SCOPE_CTE
            + "SELECT COALESCE(SUM(order_total) FILTER (WHERE status <> 'cancelled'), 0) AS revenue "
            "FROM scoped",
            window,
        )
        previous = one(
            SCOPE_CTE
            + "SELECT COALESCE(SUM(order_total) FILTER (WHERE status <> 'cancelled'), 0) AS revenue "
            "FROM scoped",
            window.previous(),
        )
        cur_rev = money(current.get("revenue"))
        prev_rev = money(previous.get("revenue"))
        return {
            "granularity": gran,
            "series": _series(window, gran),
            "by_category": _categories(window, limit=20),
            "by_region": _regions(window, limit=20),
            "by_payment_method": _by_payment(window),
            "top_products": _top_products(window),
            "growth": {
                "current_revenue": cur_rev,
                "previous_revenue": prev_rev,
                "growth_pct": change_pct(cur_rev, prev_rev),
            },
            "discount_impact": _discount_impact(window),
        }

    return cached(f"sales:{window}:{gran}", build)
