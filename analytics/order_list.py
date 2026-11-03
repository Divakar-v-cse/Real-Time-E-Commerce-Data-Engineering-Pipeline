"""Paginated order browser for ``GET /api/orders``.

The dashboard tables need the row-level view of the star schema (one row per
order, enriched with the customer and payment dimensions) rather than the
aggregated KPIs produced by :mod:`analytics.orders`.  Filtering happens in SQL
so pagination stays correct for the full 118k-order warehouse instead of
paginating a Python list.
"""
from __future__ import annotations

from typing import Any

from analytics.base import SCOPE_CTE, Window, one, query

SORTS = {
    "recent": "order_ts DESC",
    "oldest": "order_ts ASC",
    "amount_desc": "total DESC, order_ts DESC",
    "amount_asc": "total ASC, order_ts DESC",
}

_BASE = SCOPE_CTE + """
, enriched AS (
    SELECT
        s.order_id,
        s.order_ts,
        s.status,
        s.channel,
        s.country,
        s.region,
        s.item_count,
        s.order_total AS total,
        COALESCE(NULLIF(TRIM(c.full_name), ''), NULLIF(c.email, ''), 'Guest checkout') AS customer,
        COALESCE(pay.status, 'not_attempted') AS payment_status,
        COALESCE(pm.display_name, pm.method_name, 'unknown') AS payment_method
    FROM scoped s
    LEFT JOIN warehouse.dim_customer c ON c.customer_sk = s.customer_sk
    LEFT JOIN warehouse.fact_payments pay ON pay.order_id = s.order_id
    LEFT JOIN warehouse.dim_payment_method pm ON pm.payment_method_sk = s.payment_method_sk
), filtered AS (
    SELECT * FROM enriched
    WHERE (:status = '' OR status = :status)
      AND (
            :q = ''
            OR order_id ILIKE :q_like
            OR customer ILIKE :q_like
            OR country ILIKE :q_like
            OR payment_method ILIKE :q_like
      )
)
"""


def list_orders(
    window: Window,
    page: int = 1,
    size: int = 25,
    search: str | None = None,
    status: str | None = None,
    sort: str = "recent",
) -> dict[str, Any]:
    q = (search or "").strip()
    extra = {
        "q": q,
        "q_like": f"%{q}%",
        "status": (status or "").strip().lower(),
        "limit": size,
        "offset": (page - 1) * size,
    }
    order_by = SORTS.get(sort, SORTS["recent"])

    rows = query(
        _BASE
        + f"""
        SELECT order_id, order_ts, customer, country, region, status,
               payment_status, payment_method, item_count AS items, total
        FROM filtered
        ORDER BY {order_by}
        LIMIT :limit OFFSET :offset
        """,
        window,
        extra,
    )
    totals = one(
        _BASE
        + """
        SELECT COUNT(*) AS orders,
               COALESCE(SUM(total), 0) AS revenue,
               COALESCE(AVG(total), 0) AS aov
        FROM filtered
        """,
        window,
        extra,
    )

    items = [
        {
            "order_id": r["order_id"],
            "order_date": r["order_ts"].isoformat() if hasattr(r["order_ts"], "isoformat") else str(r["order_ts"]),
            "customer": r["customer"],
            "country": r["country"] or "",
            "region": r["region"] or "",
            "status": r["status"],
            "payment_status": r["payment_status"],
            "payment_method": r["payment_method"],
            "items": int(r["items"] or 0),
            "total": round(float(r["total"] or 0), 2),
        }
        for r in rows
    ]
    total = int(totals.get("orders") or 0)
    return {
        "items": items,
        "page": page,
        "page_size": size,
        "total": total,
        "pages": max(1, -(-total // size)),
        "summary": {
            "revenue": round(float(totals.get("revenue") or 0), 2),
            "average_order_value": round(float(totals.get("aov") or 0), 2),
        },
        "sort": sort if sort in SORTS else "recent",
    }
