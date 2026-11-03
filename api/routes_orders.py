"""Row-level order browser plus the exportable daily sales report."""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from analytics.base import Window, query
from analytics.order_list import list_orders
from api.deps import Page, pagination, window_params
from api.schemas import OrderListResponse

router = APIRouter(prefix="/api", tags=["orders"])


@router.get(
    "/orders",
    response_model=OrderListResponse,
    summary="Search and page through orders",
    description=(
        "Row-level order view joined to the customer and payment dimensions. "
        "`search` matches order id, customer name, country and payment method; "
        "`status` filters on the order status; `sort` accepts recent, oldest, amount_desc, amount_asc."
    ),
    responses={422: {"description": "Invalid page, status or sort value."}},
)
def orders(
    window: Window = Depends(window_params),
    page: Page = Depends(pagination),
    search: str | None = Query(None, max_length=120, description="Free-text search across order id, customer, country, payment method."),
    status: str | None = Query(None, max_length=30, description="Order status filter, e.g. delivered, cancelled, returned."),
    sort: str = Query("recent", pattern="^(recent|oldest|amount_desc|amount_asc)$"),
) -> dict[str, Any]:
    return list_orders(window, page=page.page, size=page.size, search=search, status=status, sort=sort)


@router.get(
    "/reports/daily-sales",
    summary="Daily sales report (JSON or CSV)",
    description=(
        "The gold-layer daily aggregate used by the scheduled report DAG. "
        "Use `format=csv` to download the same rows as a spreadsheet-friendly file."
    ),
    # NOTE: no ``response_class=StreamingResponse`` here. Declaring it would make
    # FastAPI wrap the JSON dict in a StreamingResponse, which iterates the dict
    # and streams its *keys* instead of the payload. The CSV branch returns a
    # StreamingResponse object explicitly, so the class is not needed.
    responses={
        200: {
            "content": {
                "application/json": {},
                "text/csv": {},
            },
            "description": "Daily sales rows as JSON, or a CSV attachment when `format=csv`.",
        }
    },
)
def daily_sales_report(
    window: Window = Depends(window_params),
    format: str = Query("json", pattern="^(json|csv)$"),
) -> Any:
    rows = query(
        """
        SELECT sales_date, orders, completed_orders, cancelled_orders, returned_orders,
               units_sold, gross_revenue, discount_amount, shipping_revenue, net_revenue,
               active_customers, new_customers
        FROM analytics.sales_daily
        WHERE sales_date BETWEEN :start_date AND :end_date
        ORDER BY sales_date
        """,
        window,
    )
    if window.category or window.region:
        # The gold table is pre-aggregated at day grain without category/region
        # dimensions, so it cannot be filtered further. Say so instead of silently
        # returning unfiltered numbers.
        note = "analytics.sales_daily is aggregated at day grain; category/region filters do not apply."
    else:
        note = ""

    payload = {
        "period": window.as_dict(),
        "granularity": "day",
        "rows": [
            {
                "date": r["sales_date"].isoformat() if hasattr(r["sales_date"], "isoformat") else str(r["sales_date"]),
                "orders": int(r["orders"] or 0),
                "completed_orders": int(r["completed_orders"] or 0),
                "cancelled_orders": int(r["cancelled_orders"] or 0),
                "returned_orders": int(r["returned_orders"] or 0),
                "units_sold": int(r["units_sold"] or 0),
                "gross_revenue": round(float(r["gross_revenue"] or 0), 2),
                "discount_amount": round(float(r["discount_amount"] or 0), 2),
                "shipping_revenue": round(float(r["shipping_revenue"] or 0), 2),
                "net_revenue": round(float(r["net_revenue"] or 0), 2),
                "active_customers": int(r["active_customers"] or 0),
                "new_customers": int(r["new_customers"] or 0),
            }
            for r in rows
        ],
        "totals": {
            "orders": sum(int(r["orders"] or 0) for r in rows),
            "revenue": round(sum(float(r["net_revenue"] or 0) for r in rows), 2),
            "units": sum(int(r["units_sold"] or 0) for r in rows),
        },
        "note": note,
        "generated_at": window.end.isoformat(),
    }

    if format == "csv":
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(payload["rows"][0].keys()) if payload["rows"] else ["date"])
        writer.writeheader()
        writer.writerows(payload["rows"])
        filename = f"daily_sales_{window.start}_{window.end}.csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return payload
