"""Operational endpoints: health, pipeline status, data quality, triggers, system status."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from analytics.quality import get_data_quality
from analytics.pipeline import get_pipeline_status
from api import runtime
from api.schemas import EventRequest, EventResponse, HealthResponse, SystemResponse, TriggerRequest, TriggerResponse
from common.db import fetch_all, fetch_one, fetch_scalar, healthcheck
from common.settings import LAKE_DIR, PROJECT_ROOT, settings
from orchestration.registry import DAGS

logger = logging.getLogger(__name__)

router = APIRouter(tags=["operations"])

VALID_STAGES = {"warehouse", "quality", "stream", "gold", "dbt"}


# --------------------------------------------------------------------------- #
# health
# --------------------------------------------------------------------------- #
@router.get("/health", response_model=HealthResponse, tags=["health"], summary="Liveness and warehouse readiness")
def health() -> dict[str, Any]:
    ok, detail = healthcheck()
    warehouse = {"orders": 0, "customers": 0, "products": 0, "revenue": 0.0}
    version = "unknown"
    if ok:
        version = str(detail).split(" ")[1] if len(str(detail).split(" ")) > 1 else "PostgreSQL"
        row = fetch_one(
            """
            SELECT
                (SELECT COUNT(*) FROM warehouse.fact_orders)      AS orders,
                (SELECT COUNT(*) FROM warehouse.dim_customer WHERE is_current) AS customers,
                (SELECT COUNT(*) FROM warehouse.dim_product)      AS products,
                (SELECT COALESCE(SUM(order_total), 0) FROM warehouse.fact_orders) AS revenue
            """
        ) or {}
        warehouse = {
            "orders": int(row.get("orders") or 0),
            "customers": int(row.get("customers") or 0),
            "products": int(row.get("products") or 0),
            "revenue": round(float(row.get("revenue") or 0), 2),
        }

    return {
        "status": "ok" if ok else "degraded",
        "version": runtime.VERSION,
        "database": {
            "connected": ok,
            "engine": "PostgreSQL",
            "version": version,
            "latency_ms": None,
        },
        "uptime_seconds": runtime.uptime_seconds(),
        "warehouse": warehouse,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# --------------------------------------------------------------------------- #
# pipeline + quality
# --------------------------------------------------------------------------- #
@router.get("/api/pipeline/status", tags=["pipeline"], summary="Lakehouse, streaming and orchestration status")
def pipeline_status() -> dict[str, Any]:
    return get_pipeline_status()


@router.get("/api/data-quality", tags=["data-quality"], summary="Latest quality score with per-check detail and trend")
def data_quality() -> dict[str, Any]:
    return get_data_quality()


# --------------------------------------------------------------------------- #
# triggers
# --------------------------------------------------------------------------- #
def _run_dbt() -> dict[str, Any]:
    project = PROJECT_ROOT / "dbt"
    if not (project / "dbt_project.yml").exists():
        raise HTTPException(status_code=409, detail="dbt project not found at ./dbt")
    from dbt.cli.main import dbtRunner

    started = time.perf_counter()
    result = dbtRunner().invoke(
        ["build", "--project-dir", str(project), "--profiles-dir", str(project), "--no-use-colors"]
    )
    elapsed = round(time.perf_counter() - started, 1)
    if not result.success:
        detail = str(getattr(result, "exception", None) or "see server log")
        raise HTTPException(status_code=500, detail=f"dbt build failed after {elapsed}s: {detail}")
    return {"status": "success", "duration_seconds": elapsed, "output": [f"dbt build ok in {elapsed}s"]}


@router.post(
    "/api/pipeline/trigger",
    response_model=TriggerResponse,
    tags=["pipeline"],
    summary="Run a pipeline stage on demand",
    description=(
        "Runs the same functions the Airflow DAGs call, so a manual trigger cannot diverge "
        "from the scheduled behaviour. `warehouse` re-loads staging → dimensions → facts → gold, "
        "`quality` re-runs the eight-check suite, `stream` drains the Kafka topics into "
        "bronze/silver/gold, `gold` refreshes analytics.sales_daily, `dbt` runs dbt build."
    ),
    responses={400: {"description": "Unknown stage."}, 500: {"description": "The stage raised an error."}},
)
def trigger_pipeline(body: TriggerRequest | None = None) -> dict[str, Any]:
    body = body or TriggerRequest()
    stages = [s.strip().lower() for s in body.stages if s.strip()]
    unknown = sorted(set(stages) - VALID_STAGES)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown stage(s): {', '.join(unknown)}. Valid: {', '.join(sorted(VALID_STAGES))}")
    if not stages:
        raise HTTPException(status_code=400, detail="Provide at least one stage")

    started = time.perf_counter()
    run_id = 0
    report: dict[str, Any] = {}
    for stage in stages:
        try:
            if stage == "warehouse":
                from warehouse.load import run_batch

                result = run_batch(rebuild=body.rebuild)
                run_id = int(result.get("run_id") or run_id)
                report["warehouse"] = result
            elif stage == "gold":
                from warehouse.stream_sink import backfill_gold

                report["gold"] = {"days_refreshed": backfill_gold()}
            elif stage == "quality":
                from pipeline.quality.checks import run_checks

                report["quality"] = run_checks()
            elif stage == "stream":
                from pipeline.streaming.processor import StreamProcessor

                batch = StreamProcessor().process_once()
                run_id = int(batch.run_id or run_id)
                report["stream"] = batch.as_dict()
            elif stage == "dbt":
                report["dbt"] = _run_dbt()
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("pipeline stage failed", extra={"extra_fields": {"stage": stage}})
            from warehouse.load import finish_run, start_run

            if not run_id:
                run_id = start_run("manual_trigger", "api", {"stages": stages})
            finish_run(run_id, "failed", error=f"{stage}: {type(exc).__name__}: {exc}")
            raise HTTPException(status_code=500, detail=f"{stage} stage failed: {type(exc).__name__}: {exc}") from exc

    elapsed = round(time.perf_counter() - started, 1)
    if not run_id:
        from warehouse.load import finish_run, start_run

        run_id = start_run("manual_trigger", "api", {"stages": stages})
        finish_run(run_id, "success", details=report)

    summary = ", ".join(
        f"{stage}={report[stage].get('records_out') or report[stage].get('passed') or report[stage].get('days_refreshed') or 'ok'}"
        for stage in stages
        if stage in report
    )
    return {
        "run_id": run_id,
        "status": "success",
        "message": f"Completed {len(stages)} stage(s) in {elapsed}s ({summary})",
        "stages": stages,
        "duration_seconds": elapsed,
    }


@router.post(
    "/api/events/generate",
    response_model=EventResponse,
    tags=["streaming"],
    summary="Publish synthetic order events and process them",
    description=(
        "Publishes N orders to the event bus, then drains the topic through the "
        "validation/dedup/watermark pipeline so the response reflects what actually "
        "landed in silver, not merely what was produced."
    ),
    responses={500: {"description": "Publishing or processing raised an error."}},
)
def generate_events(body: EventRequest) -> dict[str, Any]:
    from pipeline.streaming.broker import broker
    from pipeline.streaming.processor import CONSUMER_GROUP, StreamProcessor
    from pipeline.streaming.producer import EventProducer

    try:
        producer = EventProducer(seed=body.seed, live=body.inject_issues)
        published = producer.run(count=body.count, rate=body.rate_per_second)
        batch = StreamProcessor().process_once()
    except Exception as exc:
        logger.exception("event generation failed")
        raise HTTPException(status_code=500, detail=f"Event generation failed: {type(exc).__name__}: {exc}") from exc

    topics = {stat["topic"]: int(stat["messages"]) for stat in broker.topic_stats()}
    lag = sum(
        broker.lag(stat["topic"], CONSUMER_GROUP)
        for stat in broker.topic_stats()
        if not stat["topic"].endswith(".dlq")
    )
    return {
        "accepted": int(batch.silver_rows),
        "rejected": int(batch.rejected),
        "topics": topics,
        "lag": int(lag),
        "batch_id": batch.batch_id,
        "emitted": int(published.get("emitted") or 0),
        "rejected_samples": batch.errors[:5],
    }


# --------------------------------------------------------------------------- #
# system status
# --------------------------------------------------------------------------- #
def _freshness(dataset: str, sql: str, threshold_minutes: float) -> dict[str, Any]:
    try:
        latest = fetch_scalar(sql)
    except Exception:
        latest = None
    if not isinstance(latest, datetime):
        return {"dataset": dataset, "latest": None, "lag_minutes": None, "status": "no_data"}
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    lag = round((datetime.now(timezone.utc) - latest).total_seconds() / 60, 1)
    status = "fresh" if lag <= threshold_minutes else ("stale" if lag <= threshold_minutes * 6 else "cold")
    return {"dataset": dataset, "latest": latest.isoformat(), "lag_minutes": lag, "status": status}


@router.get("/api/system/status", response_model=SystemResponse, tags=["system"], summary="Runtime, services and data freshness")
def system_status() -> dict[str, Any]:
    ok, detail = healthcheck()
    db_version = "unknown"
    size_mb = 0.0
    if ok:
        db_version = str(detail).split(",")[0].replace("PostgreSQL ", "")
        size_mb = round(float(fetch_scalar("SELECT pg_database_size(current_database())") or 0) / 1_048_576, 2)

    lake_files = sorted(LAKE_DIR.rglob("*.parquet")) if LAKE_DIR.exists() else []
    lake_mb = round(sum(f.stat().st_size for f in lake_files) / 1_048_576, 2)

    topics: list[dict[str, Any]] = []
    total_lag = 0
    try:
        from pipeline.streaming.broker import broker

        topics = broker.topic_stats()
        total_lag = sum(broker.lag(t["topic"], "ecommerce-streaming-v1") for t in topics if not t["topic"].endswith(".dlq"))
    except Exception as exc:  # pragma: no cover - broker always importable here
        logger.warning("broker unavailable: %s", exc)

    last_stream = fetch_one(
        "SELECT status, duration_seconds, finished_at FROM ops.pipeline_runs WHERE pipeline_name IN ('stream_processing','stream_monitor') ORDER BY started_at DESC LIMIT 1"
    ) or {}

    services = [
        {
            "name": "PostgreSQL warehouse",
            "status": "up" if ok else "down",
            "detail": f"{db_version} · {size_mb} MB · star schema + ops schema",
            "mode": "native (embedded server)",
        },
        {
            "name": "Event bus (Kafka API)",
            "status": "up" if topics else "down",
            "detail": f"{len(topics)} topics · {sum(t['messages'] for t in topics):,} messages · lag {total_lag}",
            "mode": "file-backed Kafka emulator" if not settings.use_real_kafka else "Apache Kafka",
        },
        {
            "name": "Stream processor (Spark semantics)",
            "status": str(last_stream.get("status") or "idle"),
            "detail": (
                f"last micro-batch {last_stream.get('duration_seconds') or 0}s · "
                f"consumer group ecommerce-streaming-v1 · watermark {settings.late_arrival_tolerance_days}d"
            ),
            "mode": "checkpointed micro-batch executor",
        },
        {
            "name": "Airflow orchestration",
            "status": "registered",
            "detail": f"{len(DAGS)} DAGs sharing orchestration/registry.py with the API",
            "mode": "registry-backed DAG factory",
        },
        {
            "name": "dbt transformations",
            "status": "available" if (PROJECT_ROOT / "dbt" / "dbt_project.yml").exists() else "not_configured",
            "detail": "staging → intermediate → marts models with schema tests",
            "mode": "dbt-core",
        },
        {
            "name": "Object storage / lake",
            "status": "up" if lake_files else "empty",
            "detail": f"{len(lake_files)} parquet files · {lake_mb} MB · s3://{settings.lake_bucket}",
            "mode": "local Parquet lake (S3-compatible layout)",
        },
        {
            "name": "Dashboard",
            "status": "up",
            "detail": "React + TypeScript SPA served by this FastAPI process",
            "mode": "embedded SPA (Superset-compatible gold tables)",
        },
    ]

    row_counts = []
    for label, sql in [
        ("warehouse.fact_orders", "SELECT COUNT(*) FROM warehouse.fact_orders"),
        ("warehouse.fact_order_items", "SELECT COUNT(*) FROM warehouse.fact_order_items"),
        ("warehouse.fact_payments", "SELECT COUNT(*) FROM warehouse.fact_payments"),
        ("warehouse.fact_shipments", "SELECT COUNT(*) FROM warehouse.fact_shipments"),
        ("warehouse.fact_returns", "SELECT COUNT(*) FROM warehouse.fact_returns"),
        ("warehouse.dim_customer", "SELECT COUNT(*) FROM warehouse.dim_customer WHERE is_current"),
        ("warehouse.dim_product", "SELECT COUNT(*) FROM warehouse.dim_product"),
        ("analytics.sales_daily", "SELECT COUNT(*) FROM analytics.sales_daily"),
        ("ops.rejected_records", "SELECT COUNT(*) FROM ops.rejected_records"),
        ("ops.pipeline_runs", "SELECT COUNT(*) FROM ops.pipeline_runs"),
    ]:
        try:
            row_counts.append({"table": label, "rows": int(fetch_scalar(sql) or 0)})
        except Exception:
            row_counts.append({"table": label, "rows": 0})

    return {
        "application": {
            "name": runtime.APP_NAME,
            "version": runtime.VERSION,
            "environment": runtime.environment(),
            "started_at": runtime.STARTED_AT.isoformat(),
            "uptime_seconds": runtime.uptime_seconds(),
        },
        "database": {
            "url": _masked_url(settings.database_url),
            "connected": ok,
            "version": db_version,
            "size_mb": size_mb,
        },
        "services": services,
        "data_freshness": [
            _freshness("orders", "SELECT MAX(order_ts) FROM warehouse.fact_orders", 60 * 24),
            _freshness("payments", "SELECT MAX(paid_at) FROM warehouse.fact_payments", 60 * 24),
            _freshness("gold layer", "SELECT MAX(updated_at) FROM analytics.sales_daily", 60 * 24),
            _freshness("quality suite", "SELECT MAX(run_at) FROM ops.data_quality_results", 60 * 24),
            _freshness("stream events", "SELECT MAX(ingested_at) FROM ops.stream_events", 120),
        ],
        "row_counts": row_counts,
    }


_LAKE_ROOT = LAKE_DIR


def _masked_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.split("@", 1)
    user = creds.split(":")[0]
    return f"{scheme}://{user}:***@{host}"


@router.get("/api/system/filters", tags=["system"], summary="Available filter values")
def filter_values() -> dict[str, Any]:
    categories = [r["category"] for r in fetch_all("SELECT DISTINCT category FROM warehouse.dim_product WHERE is_active ORDER BY 1")]
    regions = [r["region"] for r in fetch_all("SELECT DISTINCT region FROM warehouse.fact_orders WHERE COALESCE(region, '') <> '' ORDER BY 1")]
    bounds = fetch_one("SELECT MIN(order_ts)::date AS min_date, MAX(order_ts)::date AS max_date FROM warehouse.fact_orders") or {}
    return {
        "categories": categories,
        "regions": regions,
        "min_date": bounds.get("min_date").isoformat() if bounds.get("min_date") else None,
        "max_date": bounds.get("max_date").isoformat() if bounds.get("max_date") else None,
    }

