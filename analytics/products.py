"""Product analytics: best sellers, laggards, category mix and return rates."""
from __future__ import annotations

from typing import Any

from analytics.base import SCOPE_CTE, Window, cached, money, query, rate

_PRODUCT_SALES = SCOPE_CTE + """
, sales AS (
    SELECT p.product_id, p.product_name, p.category,
           COALESCE(SUM(foi.line_total), 0)      AS revenue,
           COALESCE(SUM(foi.quantity), 0)        AS units,
           COUNT(DISTINCT s.order_id)            AS orders,
           COALESCE(SUM(foi.gross_profit), 0)    AS profit
    FROM scoped s
    JOIN warehouse.fact_order_items foi ON foi.order_id = s.order_id
    JOIN warehouse.dim_product p ON p.product_sk = foi.product_sk
    WHERE s.status <> 'cancelled'
    GROUP BY p.product_id, p.product_name, p.category
)
"""


def _best_sellers(window: Window, limit: int = 12) -> list[dict[str, Any]]:
    sql = _PRODUCT_SALES + """
    , returned AS (
        SELECT p.product_id, COALESCE(SUM(foi.quantity), 0) AS units_returned
        FROM scoped s
        JOIN warehouse.fact_returns r ON r.order_id = s.order_id
        JOIN warehouse.fact_order_items foi ON foi.order_id = s.order_id
        JOIN warehouse.dim_product p ON p.product_sk = foi.product_sk
        GROUP BY p.product_id
    )
    SELECT sales.*, COALESCE(returned.units_returned, 0) AS units_returned
    FROM sales
    LEFT JOIN returned ON returned.product_id = sales.product_id
    ORDER BY sales.revenue DESC
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
            "return_rate": rate(r["units_returned"], r["units"]),
        }
        for r in rows
    ]


def _low_performers(window: Window, limit: int = 10) -> list[dict[str, Any]]:
    sql = _PRODUCT_SALES + """
    SELECT * FROM sales
    ORDER BY revenue ASC, units ASC
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
        }
        for r in rows
    ]


def _return_rates(window: Window, limit: int = 12) -> list[dict[str, Any]]:
    sql = _PRODUCT_SALES + """
    , returned AS (
        SELECT p.product_id, COALESCE(SUM(foi.quantity), 0) AS units_returned
        FROM scoped s
        JOIN warehouse.fact_returns r ON r.order_id = s.order_id
        JOIN warehouse.fact_order_items foi ON foi.order_id = s.order_id
        JOIN warehouse.dim_product p ON p.product_sk = foi.product_sk
        GROUP BY p.product_id
    )
    SELECT sales.product_id, sales.product_name, sales.category, sales.units,
           COALESCE(returned.units_returned, 0) AS units_returned
    FROM sales
    JOIN returned ON returned.product_id = sales.product_id
    WHERE sales.units > 0
    ORDER BY returned.units_returned DESC, sales.units DESC
    LIMIT :limit
    """
    rows = query(sql, window, {"limit": limit})
    return [
        {
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "category": r["category"],
            "units_sold": int(r["units"] or 0),
            "units_returned": int(r["units_returned"] or 0),
            "return_rate": rate(r["units_returned"], r["units"]),
        }
        for r in rows
    ]


def get_products(window: Window) -> dict[str, Any]:
    from analytics.overview import _categories

    return cached(
        f"products:{window}",
        lambda: {
            "best_sellers": _best_sellers(window),
            "low_performers": _low_performers(window),
            "by_category": _categories(window, limit=20),
            "return_rates": _return_rates(window),
        },
    )
