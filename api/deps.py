"""Shared FastAPI dependencies: date scoping, filters and pagination."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from fastapi import HTTPException, Query

from analytics.base import Window, resolve_window

DATE_HELP = "ISO date (YYYY-MM-DD). Defaults to the latest order date in the warehouse."


def window_params(
    start_date: date | None = Query(None, description=DATE_HELP),
    end_date: date | None = Query(None, description=DATE_HELP),
    days: int | None = Query(None, ge=1, le=1095, description="Preset window length in days (ignored when start_date is given)."),
    category: str | None = Query(None, max_length=80, description="Product category filter."),
    region: str | None = Query(None, max_length=80, description="Customer region filter."),
) -> Window:
    """Resolve the analytics window once so every KPI on a page is consistent."""
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must be on or before end_date")
    return resolve_window(start_date, end_date, days, category, region)


@dataclass(frozen=True)
class Page:
    page: int
    size: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size


def pagination(
    page: int = Query(1, ge=1, le=10_000, description="1-based page number."),
    size: int = Query(25, ge=5, le=200, description="Rows per page."),
) -> Page:
    return Page(page=page, size=size)
