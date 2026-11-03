"""Shared SQL scoping, date handling and numeric helpers for the analytics layer."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from common.db import fetch_all, fetch_one, fetch_scalar

# ``scoped`` exposes the fact rows inside the requested date / category / region
# window.  Every query in the analytics package starts from this CTE so that all
# report numbers are mutually consistent.
SCOPE_CTE = """
WITH scoped AS (
    SELECT
        fo.order_id, fo.order_ts, fo.date_key,
        dd.date_actual                         AS order_date,
        fo.region, fo.country, fo.status,
        fo.order_total, fo.subtotal, fo.discount_total, fo.shipping_total,
        fo.item_count, fo.customer_sk, fo.payment_method_sk, fo.channel, fo.currency,
        fo.is_completed, fo.is_cancelled, fo.is_returned
    FROM warehouse.fact_orders fo
    JOIN warehouse.dim_date dd ON dd.date_key = fo.date_key
    WHERE dd.date_actual BETWEEN :start_date AND :end_date
      AND (:region = '' OR fo.region = :region)
      AND (
            :category = ''
            OR EXISTS (
                SELECT 1
                FROM warehouse.fact_order_items x
                JOIN warehouse.dim_product p ON p.product_sk = x.product_sk
                WHERE x.order_id = fo.order_id AND p.category = :category
            )
      )
)
"""


@dataclass(frozen=True)
class Window:
    start: date
    end: date
    category: str = ""
    region: str = ""

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def params(self) -> dict[str, Any]:
        return {
            "start_date": self.start,
            "end_date": self.end,
            "category": self.category or "",
            "region": self.region or "",
        }

    def previous(self) -> "Window":
        span = timedelta(days=self.days)
        return Window(self.start - span, self.start - timedelta(days=1), self.category, self.region)

    def as_dict(self) -> dict[str, Any]:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "days": self.days}


def latest_order_date() -> date:
    value = fetch_scalar("SELECT MAX(order_ts)::date FROM warehouse.fact_orders")
    if isinstance(value, date):
        return value
    return datetime.now().date()


def resolve_window(
    start_date: date | None = None,
    end_date: date | None = None,
    preset_days: int | None = None,
    category: str | None = None,
    region: str | None = None,
) -> Window:
    anchor = latest_order_date()
    end = end_date or anchor
    if start_date:
        start = start_date
    elif preset_days:
        start = end - timedelta(days=preset_days - 1)
    else:
        start = end - timedelta(days=89)
    if start > end:
        start, end = end, start
    return Window(start, end, (category or "").strip(), (region or "").strip())


def money(value: Any) -> float:
    return round(float(value or 0), 2)


def rate(numerator: Any, denominator: Any) -> float:
    num = float(numerator or 0)
    den = float(denominator or 0)
    return round(num / den * 100, 2) if den else 0.0


def change_pct(current: Any, previous: Any) -> float | None:
    cur = float(current or 0)
    prev = float(previous or 0)
    if prev == 0:
        return None
    return round((cur - prev) / prev * 100, 2)


def share(value: Any, total: Any) -> float:
    return rate(value, total)


_QUERY_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 4.0


def cached(key: str, producer: Callable[[], Any], ttl: float = _CACHE_TTL) -> Any:
    """Tiny in-process cache so dashboard pages do not re-run identical SQL."""
    now = time.time()
    hit = _QUERY_CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = producer()
    _QUERY_CACHE[key] = (now, value)
    if len(_QUERY_CACHE) > 256:
        oldest = min(_QUERY_CACHE, key=lambda k: _QUERY_CACHE[k][0])
        _QUERY_CACHE.pop(oldest, None)
    return value


def query(sql: str, window: Window, extra: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    params = {**window.params, **(extra or {})}
    return fetch_all(sql, params)


def one(sql: str, window: Window, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    params = {**window.params, **(extra or {})}
    return fetch_one(sql, params) or {}


def scalar(sql: str, window: Window, extra: dict[str, Any] | None = None) -> Any:
    params = {**window.params, **(extra or {})}
    return fetch_scalar(sql, params)
