"""Analytics endpoints — every number is produced by SQL against the warehouse."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from analytics.base import Window
from analytics.customers import get_customers
from analytics.forecast import get_forecast
from analytics.orders import get_orders
from analytics.overview import get_overview
from analytics.products import get_products
from analytics.retention import get_retention
from analytics.sales import get_sales
from api.deps import window_params

router = APIRouter(prefix="/api", tags=["analytics"])

WINDOW_ERRORS = {422: {"description": "Invalid date range or filter value."}}


@router.get(
    "/dashboard/overview",
    summary="Executive KPI overview",
    description=(
        "Headline revenue, orders, AOV, customers, completion/payment/return rates, "
        "the revenue trend, status mix, top categories and regions, and the latest orders "
        "for the selected window."
    ),
    responses=WINDOW_ERRORS,
)
def dashboard_overview(window: Window = Depends(window_params)) -> dict[str, Any]:
    return get_overview(window)


@router.get(
    "/analytics/sales",
    summary="Sales analytics",
    description="Revenue/orders/units trend at day, week or month grain plus category, region, payment-method, product and discount-band breakdowns.",
    responses=WINDOW_ERRORS,
)
def sales(
    window: Window = Depends(window_params),
    granularity: str | None = Query(None, pattern="^(day|week|month|auto)$", description="Trend grain. 'auto' picks day <=45d, week <=180d, else month."),
) -> dict[str, Any]:
    return get_sales(window, granularity)


@router.get(
    "/analytics/customers",
    summary="Customer analytics",
    description="New vs returning customers, RFM segments with NTILE(5) scoring, CLV distribution, repeat-purchase rate and the top customers by spend.",
    responses=WINDOW_ERRORS,
)
def customers(window: Window = Depends(window_params)) -> dict[str, Any]:
    return get_customers(window)


@router.get(
    "/analytics/products",
    summary="Product analytics",
    description="Best sellers, low performers, category mix and the products with the highest return rates.",
    responses=WINDOW_ERRORS,
)
def products(window: Window = Depends(window_params)) -> dict[str, Any]:
    return get_products(window)


@router.get(
    "/analytics/orders",
    summary="Order analytics",
    description="Status counts, daily status mix, fulfilment timings, the placed→paid→shipped→delivered funnel and payment-failure reasons.",
    responses=WINDOW_ERRORS,
)
def order_analytics(window: Window = Depends(window_params)) -> dict[str, Any]:
    return get_orders(window)


@router.get(
    "/analytics/retention",
    summary="Cohort retention",
    description="Monthly acquisition cohorts, the retention curve by month offset, repeat and churn rates, and average customer lifetime.",
    responses=WINDOW_ERRORS,
)
def retention(window: Window = Depends(window_params)) -> dict[str, Any]:
    return get_retention(window)


@router.get(
    "/analytics/forecast",
    summary="Revenue forecast and anomalies",
    description=(
        "Fits a linear trend with weekday seasonality on the daily revenue series, reports "
        "held-out MAPE, and projects the next N days with 95% bands. Every forecast row is "
        "returned separately from `history` (observed revenue) and flagged by the `disclaimer`."
    ),
    responses=WINDOW_ERRORS,
)
def forecast(
    window: Window = Depends(window_params),
    horizon: int = Query(30, ge=7, le=90, description="Forecast horizon in days."),
) -> dict[str, Any]:
    return get_forecast(window, horizon)
