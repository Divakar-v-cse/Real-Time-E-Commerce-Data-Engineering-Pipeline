"""Sales forecasting and anomaly detection.

Model
-----
Additive trend + multiplicative day-of-week seasonality (a compact
Holt-Winters style decomposition that needs no external ML dependency):

    revenue(t) = trend(t) * dow_factor[weekday(t)] + noise

* ``trend`` is fitted with ordinary least squares on the daily series.
* ``dow_factor`` is the mean residual ratio per weekday, normalised to 1.
* Prediction intervals use the residual standard deviation, widened with the
  forecast horizon (sqrt(1 + h/n)) so bands widen the further we project.

Quality is reported honestly: ``mape`` is a *hold-out* MAPE (fit on the first
75 % of the series, scored on the last 25 %), not in-sample error.

Predictions are returned in a separate ``forecast`` array from ``history`` and
every row carries ``kind`` so the UI can never confuse a prediction with an
actual observation.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, pstdev
from typing import Any

from analytics.base import Window, cached, query

HORIZON_DAYS = 30
_MODEL_NAME = "OLS trend + weekday seasonality"
_METHOD = (
    "Ordinary-least-squares linear trend on the daily revenue series, multiplied "
    "by a normalised day-of-week factor; 95% intervals from residual standard "
    "deviation widened by sqrt(1 + h/n). Hold-out validation on the last 25% "
    "of days."
)

_DAILY_SQL = """
WITH scoped AS (
    SELECT fo.order_id, fo.order_total, dd.date_actual AS order_date
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
SELECT order_date::text AS d, SUM(order_total)::float AS revenue, COUNT(*) AS orders
FROM scoped
GROUP BY order_date
ORDER BY order_date
"""


def _daily_series(window: Window) -> list[dict[str, Any]]:
    rows = query(_DAILY_SQL, window)
    return [
        {"date": r["d"], "revenue": round(float(r["revenue"] or 0), 2), "orders": int(r["orders"])}
        for r in rows
    ]


def _fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Least-squares slope/intercept for y = a + b*x."""
    n = len(xs)
    if n < 2:
        return 0.0, ys[0] if ys else 0.0
    mx, my = mean(xs), mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    slope = 0.0 if denom == 0 else sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return slope, my - slope * mx


def _weekday_factors(xs: list[float], ys: list[float], slope: float, intercept: float,
                     dates: list[date]) -> dict[int, float]:
    buckets: dict[int, list[float]] = {i: [] for i in range(7)}
    for x, y, d in zip(xs, ys, dates):
        base = intercept + slope * x
        if base > 0:
            buckets[d.weekday()].append(y / base)
    factors = {k: (mean(v) if v else 1.0) for k, v in buckets.items()}
    overall = mean(factors.values()) or 1.0
    # Normalise so the factors do not shift the trend level.
    return {k: min(3.0, max(0.2, v / overall)) for k, v in factors.items()}


def _project(series: list[dict[str, Any]], train_len: int) -> dict[str, Any]:
    """Fit on ``train_len`` days and return the fitted model plus residuals."""
    train = series[:train_len]
    xs = [float(i) for i in range(len(train))]
    ys = [t["revenue"] for t in train]
    slope, intercept = _fit(xs, ys)
    dates = [date.fromisoformat(t["date"]) for t in train]
    factors = _weekday_factors(xs, ys, slope, intercept, dates)
    fitted = [max(0.0, (intercept + slope * x) * factors[d.weekday()]) for x, d in zip(xs, dates)]
    residuals = [y - f for y, f in zip(ys, fitted)]
    return {
        "slope": slope,
        "intercept": intercept,
        "factors": factors,
        "fitted": fitted,
        "residuals": residuals,
        "n": len(train),
    }


def _mape(actual: list[float], predicted: list[float]) -> float:
    pairs = [(a, p) for a, p in zip(actual, predicted) if a > 0]
    if not pairs:
        return 0.0
    return round(mean(abs((a - p) / a) for a, p in pairs) * 100, 2)


def _anomalies(series: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Robust z-score on a 7-day moving average to find unusual sales days."""
    revenues = [t["revenue"] for t in series]
    if len(revenues) < 14:
        return []
    out: list[dict[str, Any]] = []
    window = 7
    for i in range(window, len(revenues)):
        recent = revenues[i - window:i]
        baseline = mean(recent)
        spread = pstdev(recent) or 1.0
        value = revenues[i]
        z = (value - baseline) / spread
        if abs(z) >= 2.0:
            out.append(
                {
                    "date": series[i]["date"],
                    "revenue": round(value, 2),
                    "expected": round(baseline, 2),
                    "deviation_pct": round((value - baseline) / baseline * 100, 2) if baseline else 0.0,
                    "z_score": round(z, 2),
                    "severity": "high" if abs(z) >= 3.0 else "medium",
                    "direction": "spike" if z > 0 else "drop",
                    "method": "7-day rolling mean, robust z-score",
                }
            )
        else:
            continue
    # Keep the most extreme 12 so the UI stays readable.
    out.sort(key=lambda r: abs(r["z_score"]), reverse=True)
    return sorted(out[:12], key=lambda r: r["date"])


def get_forecast(window: Window, horizon: int = HORIZON_DAYS) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        series = _daily_series(window)
        if len(series) < 14:
            return {
                "history": series,
                "forecast": [],
                "model": {"name": _MODEL_NAME, "mape": 0.0, "trained_on_days": len(series), "method": _METHOD},
                "summary": {"horizon_days": 0, "forecast_revenue": 0.0, "expected_growth_pct": 0.0},
                "anomalies": _anomalies(series),
                "note": "Not enough daily history (need at least 14 days) to fit the model.",
            }

        split = max(14, int(len(series) * 0.75))
        split = min(split, len(series) - 1)
        holdout = series[split:]
        validation = _project(series, split)
        val_fitted = []
        for i in range(split, len(series)):
            d = date.fromisoformat(series[i]["date"])
            val_fitted.append(max(0.0, (validation["intercept"] + validation["slope"] * i) * validation["factors"][d.weekday()]))
        holdout_mape = _mape([t["revenue"] for t in holdout], val_fitted)

        model = _project(series, len(series))
        slope, intercept, factors = model["slope"], model["intercept"], model["factors"]
        sigma = pstdev(model["residuals"]) if len(model["residuals"]) > 1 else 0.0
        n = len(series)

        last_day = date.fromisoformat(series[-1]["date"])
        forecast: list[dict[str, Any]] = []
        for h in range(1, horizon + 1):
            d = last_day + timedelta(days=h)
            x = float(n - 1 + h)
            point = max(0.0, (intercept + slope * x) * factors[d.weekday()])
            band = 1.96 * sigma * math.sqrt(1 + h / n)
            forecast.append(
                {
                    "date": d.isoformat(),
                    "revenue": round(point, 2),
                    "lower": round(max(0.0, point - band), 2),
                    "upper": round(point + band, 2),
                    "kind": "forecast",
                }
            )

        recent_days = series[-horizon:]
        recent_revenue = sum(t["revenue"] for t in recent_days)
        forecast_revenue = sum(f["revenue"] for f in forecast)
        growth = round((forecast_revenue - recent_revenue) / recent_revenue * 100, 2) if recent_revenue else 0.0

        history = [{**t, "kind": "actual"} for t in series]
        return {
            "history": history,
            "forecast": forecast,
            "model": {
                "name": _MODEL_NAME,
                "mape": holdout_mape,
                "trained_on_days": n,
                "method": _METHOD,
                "daily_trend": round(slope, 2),
                "weekday_factors": {str(k): round(v, 3) for k, v in sorted(factors.items())},
                "holdout_days": len(holdout),
            },
            "summary": {
                "horizon_days": horizon,
                "forecast_revenue": round(forecast_revenue, 2),
                "expected_growth_pct": growth,
                "avg_daily_forecast": round(forecast_revenue / horizon, 2),
            },
            "anomalies": _anomalies(series),
            "disclaimer": "Forecast values are model predictions, not observed revenue. Actuals end on the last history date.",
        }

    key = f"forecast:{window.start}:{window.end}:{window.category}:{window.region}:{horizon}"
    return cached(key, build, ttl=30.0)
