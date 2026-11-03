"""Cohort retention, repeat purchase and churn analysis."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from analytics.base import Window, cached, query, rate, scalar

_COHORT_SQL = """
WITH firsts AS (
    SELECT fo.customer_sk, MIN(dd.date_actual) AS first_date
    FROM warehouse.fact_orders fo
    JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key
    WHERE dd.date_actual <= :end_date
      AND (:region = '' OR fo.region = :region)
    GROUP BY fo.customer_sk
), cohort AS (
    SELECT customer_sk, date_trunc('month', first_date)::date AS cohort_month
    FROM firsts
), sized AS (
    SELECT cohort_month, COUNT(*) AS size FROM cohort GROUP BY cohort_month
), activity AS (
    SELECT c.cohort_month,
           date_trunc('month', dd.date_actual)::date AS activity_month,
           fo.customer_sk
    FROM warehouse.fact_orders fo
    JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key
    JOIN cohort c ON c.customer_sk = fo.customer_sk
    WHERE dd.date_actual <= :end_date
)
SELECT a.cohort_month, s.size, a.activity_month,
       ((EXTRACT(YEAR FROM a.activity_month) - EXTRACT(YEAR FROM a.cohort_month)) * 12
        + (EXTRACT(MONTH FROM a.activity_month) - EXTRACT(MONTH FROM a.cohort_month)))::int AS month_offset,
       COUNT(DISTINCT a.customer_sk) AS retained
FROM activity a
JOIN sized s ON s.cohort_month = a.cohort_month
GROUP BY a.cohort_month, s.size, a.activity_month
ORDER BY a.cohort_month, month_offset
"""


def _matrix(window: Window, max_cohorts: int = 12) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = query(_COHORT_SQL, window)
    by_cohort: dict[Any, dict[str, Any]] = {}
    for row in rows:
        cohort = row["cohort_month"]
        entry = by_cohort.setdefault(cohort, {"cohort": cohort, "size": int(row["size"] or 0), "periods": []})
        if int(row["month_offset"]) <= 11:
            entry["periods"].append(
                {
                    "month_offset": int(row["month_offset"]),
                    "retained": int(row["retained"] or 0),
                    "retention": rate(row["retained"], row["size"]),
                }
            )

    cohorts = sorted(by_cohort.values(), key=lambda c: c["cohort"])[-max_cohorts:]
    for entry in cohorts:
        entry["cohort"] = entry["cohort"].isoformat() if hasattr(entry["cohort"], "isoformat") else str(entry["cohort"])
        entry["periods"].sort(key=lambda p: p["month_offset"])

    totals: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for entry in cohorts:
        for period in entry["periods"]:
            bucket = totals[period["month_offset"]]
            bucket[0] += period["retained"]
            bucket[1] += entry["size"]
    curve = [
        {"month_offset": offset, "retention": rate(vals[0], vals[1])}
        for offset, vals in sorted(totals.items())
    ]
    return cohorts, curve


def _loyalty_stats(window: Window) -> tuple[float, float, float]:
    sql = """
    WITH per_customer AS (
        SELECT fo.customer_sk,
               COUNT(*) AS orders,
               MIN(dd.date_actual) AS first_date,
               MAX(dd.date_actual) AS last_date
        FROM warehouse.fact_orders fo
        JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key
        WHERE dd.date_actual <= :end_date
          AND (:region = '' OR fo.region = :region)
        GROUP BY fo.customer_sk
    )
    SELECT COUNT(*) AS customers,
           COUNT(*) FILTER (WHERE orders > 1) AS repeaters,
           COUNT(*) FILTER (WHERE last_date < (CAST(:end_date AS date) - 90)) AS churned,
           AVG((last_date - first_date)) FILTER (WHERE orders > 1) AS avg_lifetime_days
    FROM per_customer
    """
    from analytics.base import one

    row = one(sql, window)
    return (
        rate(row.get("repeaters"), row.get("customers")),
        rate(row.get("churned"), row.get("customers")),
        round(float(row.get("avg_lifetime_days") or 0), 1),
    )


def get_retention(window: Window) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        cohorts, curve = _matrix(window)
        repeat_rate, churn_rate, lifetime = _loyalty_stats(window)
        return {
            "cohorts": cohorts,
            "retention_curve": curve,
            "repeat_rate": repeat_rate,
            "churn_rate": churn_rate,
            "avg_lifetime_days": lifetime,
        }

    return cached(f"retention:{window}", build)
