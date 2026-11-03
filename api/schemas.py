"""Pydantic contracts for the endpoints whose shape is fixed and small.

The analytics payloads are deeply nested and produced by parameterised SQL, so
they are returned as typed dictionaries with an OpenAPI example instead of
being re-declared model-by-model (which would duplicate the SQL contract and
drift from it).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class DatabaseHealth(BaseModel):
    connected: bool
    engine: str = "PostgreSQL"
    version: str = "unknown"
    latency_ms: float | None = None


class WarehouseCounts(BaseModel):
    orders: int
    customers: int
    products: int
    revenue: float


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    database: DatabaseHealth
    uptime_seconds: float
    warehouse: WarehouseCounts
    generated_at: str


class OrderRow(BaseModel):
    order_id: str
    order_date: str
    customer: str
    country: str
    region: str
    status: str
    payment_status: str
    payment_method: str
    items: int
    total: float


class OrderListResponse(BaseModel):
    items: list[OrderRow]
    page: int
    page_size: int
    total: int
    pages: int
    summary: dict[str, Any] = Field(default_factory=dict)
    sort: str = "recent"


class TriggerRequest(BaseModel):
    stages: list[str] = Field(
        default_factory=lambda: ["warehouse"],
        description="Stages to run: warehouse, quality, stream, gold, dbt.",
        examples=[["warehouse", "quality"]],
    )
    rebuild: bool = Field(False, description="Drop and rebuild the warehouse tables before loading.")


class TriggerResponse(BaseModel):
    run_id: int
    status: str
    message: str
    stages: list[str]
    duration_seconds: float


class EventRequest(BaseModel):
    count: int = Field(50, ge=1, le=5000, description="Number of synthetic orders to publish.")
    rate_per_second: float = Field(20.0, gt=0, le=1000, description="Publish rate; the Kafka emulator applies back-pressure here.")
    inject_issues: bool = Field(
        True,
        description="Include the ~8% deliberately malformed events so the validation path is exercised.",
    )
    late_probability: float = Field(0.06, ge=0, le=1, description="Share of events published with a late-arriving timestamp.")
    seed: int | None = Field(None, description="Deterministic seed for reproducible demo traffic.")


class EventResponse(BaseModel):
    accepted: int
    rejected: int
    topics: dict[str, int]
    lag: int
    batch_id: str | None = None
    emitted: int = 0
    rejected_samples: list[str] = Field(default_factory=list)


class ServiceStatus(BaseModel):
    name: str
    status: str
    detail: str
    mode: str


class FreshnessRow(BaseModel):
    dataset: str
    latest: str | None
    lag_minutes: float | None
    status: str


class SystemResponse(BaseModel):
    application: dict[str, Any]
    database: dict[str, Any]
    services: list[ServiceStatus]
    data_freshness: list[FreshnessRow]
    row_counts: list[dict[str, Any]]
