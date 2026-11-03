"""Customer analytics: acquisition mix, RFM segmentation, CLV and loyalty."""
from __future__ import annotations

from typing import Any

from analytics.base import SCOPE_CTE, Window, cached, money, one, query, rate, scalar

_RFM_SQL = SCOPE_CTE + """
, cust AS (
    SELECT customer_sk,
           MAX(order_date) AS last_date,
           COUNT(*)        AS frequency,
           COALESCE(SUM(order_total), 0) AS monetary
    FROM scoped
    WHERE status <> 'cancelled' AND customer_sk IS NOT NULL
    GROUP BY customer_sk
), scored AS (
    SELECT *,
           NTILE(5) OVER (ORDER BY last_date ASC)   AS r_score,
           NTILE(5) OVER (ORDER BY frequency ASC)   AS f_score,
           NTILE(5) OVER (ORDER BY monetary ASC)    AS m_score
    FROM cust
), labelled AS (
    SELECT *,
           CASE
               WHEN r_score >= 4 AND f_score >= 4 THEN 'Champions'
               WHEN r_score >= 3 AND f_score >= 3 THEN 'Loyal Customers'
               WHEN r_score >= 4 AND f_score <= 2 THEN 'New / Promising'
               WHEN r_score <= 2 AND f_score >= 3 THEN 'At Risk'
               WHEN r_score <= 2 AND f_score <= 2 THEN 'Hibernating'
               ELSE 'Needs Attention'
           END AS segment
    FROM scored
)
SELECT segment,
       COUNT(*)                                   AS customers,
       COALESCE(SUM(monetary), 0)                 AS revenue,
       AVG((CAST(:end_date AS date) - last_date)) AS avg_recency_days,
       AVG(frequency)                             AS avg_frequency,
       AVG(monetary)                              AS avg_monetary
FROM labelled
GROUP BY segment
ORDER BY revenue DESC
"""


def _rfm(window: Window) -> list[dict[str, Any]]:
    rows = query(_RFM_SQL, window)
    total = sum(float(r["revenue"] or 0) for r in rows) or 1
    return [
        {
            "segment": r["segment"],
            "customers": int(r["customers"] or 0),
            "revenue": money(r["revenue"]),
            "share": rate(r["revenue"], total),
            "avg_recency_days": round(float(r["avg_recency_days"] or 0), 1),
            "avg_frequency": round(float(r["avg_frequency"] or 0), 2),
            "avg_monetary": money(r["avg_monetary"]),
        }
        for r in rows
    ]


def _new_vs_returning(window: Window) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    , first_order AS (
        SELECT fo.customer_sk, MIN(fo.order_ts)::date AS first_date
        FROM warehouse.fact_orders fo
        WHERE fo.customer_sk IN (SELECT DISTINCT customer_sk FROM scoped)
        GROUP BY fo.customer_sk
    ), active AS (
        SELECT DISTINCT date_trunc('month', order_date)::date AS month, customer_sk
        FROM scoped
        WHERE customer_sk IS NOT NULL
    )
    SELECT a.month,
           COUNT(*) FILTER (WHERE f.first_date >= a.month) AS new_customers,
           COUNT(*) FILTER (WHERE f.first_date < a.month)  AS returning_customers
    FROM active a
    JOIN first_order f ON f.customer_sk = a.customer_sk
    GROUP BY a.month
    ORDER BY a.month
    """
    rows = query(sql, window)
    return [
        {
            "month": r["month"].isoformat() if hasattr(r["month"], "isoformat") else str(r["month"]),
            "new_customers": int(r["new_customers"] or 0),
            "returning_customers": int(r["returning_customers"] or 0),
        }
        for r in rows
    ]


def _clv(window: Window) -> dict[str, Any]:
    sql = SCOPE_CTE + """
    , cust AS (
        SELECT customer_sk, COALESCE(SUM(order_total), 0) AS ltv
        FROM scoped
        WHERE status <> 'cancelled' AND customer_sk IS NOT NULL
        GROUP BY customer_sk
    ), ranked AS (
        SELECT ltv, NTILE(10) OVER (ORDER BY ltv) AS decile FROM cust
    )
    SELECT
        AVG(ltv)                                        AS average_ltv,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ltv) AS median_ltv,
        MAX(ltv) FILTER (WHERE decile = 10)             AS top_decile_ltv,
        COUNT(*)                                        AS customers
    FROM ranked
    """
    row = one(sql, window)
    return {
        "average_ltv": money(row.get("average_ltv")),
        "median_ltv": money(row.get("median_ltv")),
        "top_decile_ltv": money(row.get("top_decile_ltv")),
        "customers": int(row.get("customers") or 0),
    }


def _loyalty(window: Window) -> tuple[float, float]:
    sql = SCOPE_CTE + """
    , cust AS (
        SELECT customer_sk, COUNT(*) AS orders, COALESCE(SUM(order_total), 0) AS spend
        FROM scoped
        WHERE status <> 'cancelled' AND customer_sk IS NOT NULL
        GROUP BY customer_sk
    )
    SELECT COUNT(*) AS customers,
           COUNT(*) FILTER (WHERE orders > 1) AS repeaters,
           AVG(spend) AS avg_spend
    FROM cust
    """
    row = one(sql, window)
    return (
        rate(row.get("repeaters"), row.get("customers")),
        money(row.get("avg_spend")),
    )


def _top_customers(window: Window, limit: int = 10) -> list[dict[str, Any]]:
    sql = SCOPE_CTE + """
    SELECT c.customer_id, c.full_name, c.country,
           COUNT(*) AS orders,
           COALESCE(SUM(s.order_total), 0) AS total_spend,
           MAX(s.order_ts) AS last_order
    FROM scoped s
    JOIN warehouse.dim_customer c ON c.customer_sk = s.customer_sk
    WHERE s.status <> 'cancelled'
    GROUP BY c.customer_id, c.full_name, c.country
    ORDER BY total_spend DESC
    LIMIT :limit
    """
    rows = query(sql, window, {"limit": limit})
    return [
        {
            "customer_id": r["customer_id"],
            "full_name": r["full_name"] or "Unknown",
            "country": r["country"] or "",
            "orders": int(r["orders"] or 0),
            "total_spend": money(r["total_spend"]),
            "last_order": r["last_order"].isoformat() if r["last_order"] else None,
        }
        for r in rows
    ]


def get_customers(window: Window) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        repeat_rate, avg_spend = _loyalty(window)
        return {
            "new_vs_returning": _new_vs_returning(window),
            "rfm_segments": _rfm(window),
            "clv": _clv(window),
            "repeat_purchase_rate": repeat_rate,
            "avg_spend_per_customer": avg_spend,
            "top_customers": _top_customers(window),
        }

    return cached(f"customers:{window}", build)
