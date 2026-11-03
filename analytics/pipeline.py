"""Pipeline / lakehouse health for the /api/pipeline/status endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from common.db import fetch_all, fetch_one
from common.settings import LAKE_DIR
from orchestration.registry import DAG_BY_PIPELINE, as_orchestration

CONSUMER_GROUP = "ecommerce-streaming-v1"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _run_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": int(row["run_id"]),
        "pipeline_name": row["pipeline_name"],
        "run_type": row["run_type"],
        "status": row["status"],
        "started_at": _iso(row["started_at"]),
        "finished_at": _iso(row["finished_at"]),
        "duration_seconds": float(row["duration_seconds"]) if row["duration_seconds"] is not None else None,
        "records_in": int(row["records_in"] or 0),
        "records_out": int(row["records_out"] or 0),
        "records_rejected": int(row["records_rejected"] or 0),
        "error_message": row["error_message"],
    }


def _lake_layers() -> list[dict[str, Any]]:
    layers = []
    for layer in ("bronze", "silver", "gold"):
        base = LAKE_DIR / layer
        files = sorted(base.rglob("*.parquet")) if base.exists() else []
        size = sum(f.stat().st_size for f in files)
        latest = max((f.stat().st_mtime for f in files), default=None)
        location = f"s3://ecommerce-lake/{layer}" if layer != "bronze" else "s3://ecommerce-lake/bronze"
        layers.append(
            {
                "layer": layer,
                "records": len(files),  # partition files; row counts live in the warehouse rows below
                "size_mb": round(size / 1_048_576, 2),
                "last_updated": _iso(datetime.fromtimestamp(latest, timezone.utc)) if latest else None,
                "location": location,
                "file_count": len(files),
                "unit": "files",
            }
        )
    # Gold is materialised in Postgres, so report real row counts there.
    gold = fetch_one("SELECT COUNT(*) AS n, MAX(updated_at) AS upd FROM analytics.sales_daily") or {}
    layers[2]["records"] = int(gold.get("n") or 0)
    layers[2]["unit"] = "rows"
    layers[2]["last_updated"] = _iso(gold.get("upd")) or layers[2]["last_updated"]
    wh = fetch_one("SELECT COUNT(*) AS n FROM warehouse.fact_orders") or {}
    layers.append(
        {
            "layer": "warehouse",
            "records": int(wh.get("n") or 0),
            "size_mb": round(float(fetch_one("SELECT pg_database_size(current_database()) AS b")["b"]) / 1_048_576, 2),
            "last_updated": _iso(fetch_one("SELECT MAX(order_ts) AS t FROM warehouse.fact_orders")["t"]),
            "location": "postgresql://warehouse",
            "file_count": 0,
            "unit": "rows",
        }
    )
    return layers


def get_pipeline_status() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    runs = [_run_row(r) for r in fetch_all(
        """
        SELECT run_id, pipeline_name, run_type, status, started_at, finished_at,
               duration_seconds, records_in, records_out, records_rejected, error_message
        FROM ops.pipeline_runs
        ORDER BY started_at DESC
        LIMIT 15
        """
    )]
    last_run = runs[0] if runs else None

    metric_rows = fetch_all(
        """
        SELECT metric_name, SUM(metric_value) AS total, MAX(metric_value) AS peak, AVG(metric_value) AS avg_value,
               MAX(recorded_at) AS last_at
        FROM ops.pipeline_metrics
        WHERE recorded_at > now() - interval '24 hours'
        GROUP BY metric_name
        """
    )
    m = {r["metric_name"]: r for r in metric_rows}

    def val(name: str, field: str = "total") -> float:
        row = m.get(name)
        return round(float(row[field]), 2) if row and row[field] is not None else 0.0

    # Live broker state (file-backed Kafka alternative, or real Kafka when configured).
    topics: list[dict[str, Any]] = []
    total_lag = 0
    try:
        from pipeline.streaming.broker import broker

        for stat in broker.topic_stats():
            is_dlq = stat["topic"].endswith(".dlq")
            # The dead-letter topic is monitored, never consumed by the main group,
            # so its backlog must not be counted as consumer lag.
            lag = 0 if is_dlq else broker.lag(stat["topic"], CONSUMER_GROUP)
            total_lag += lag
            topics.append(
                {
                    "topic": stat["topic"],
                    "partitions": stat["partitions"],
                    "messages": stat["messages"],
                    "lag": lag,
                    "bytes": stat.get("bytes", 0),
                    "role": "dead_letter" if is_dlq else "stream",
                }
            )
    except Exception as exc:  # pragma: no cover - defensive
        topics = [{"topic": "unavailable", "partitions": 0, "messages": 0, "lag": 0, "error": str(exc)}]

    stream_events = fetch_one("SELECT COUNT(*) AS n FROM ops.stream_events") or {}
    duration_ms = val("batch_duration")
    throughput = 0.0
    if duration_ms > 0:
        # events in the window divided by the time the batches took, expressed per minute
        throughput = round(val("events_processed") / max(duration_ms / 60000.0, 1e-6), 2)

    metrics = {
        "events_processed": int(val("events_processed")),
        "records_rejected": int(val("records_rejected")),
        "processing_latency_ms": round(val("processing_latency", "avg_value"), 2),
        "consumer_lag": int(total_lag),
        "throughput_per_min": throughput,
        "deduplicated": int(val("duplicates_dropped")),
        "late_events": int(val("late_events")),
        "warehouse_event_rows": int(stream_events.get("n") or 0),
    }

    # Health classification
    last_started = fetch_one("SELECT MAX(started_at) AS t FROM ops.pipeline_runs") or {}
    age_hours = None
    if last_started.get("t"):
        ts = last_started["t"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_hours = (now - ts).total_seconds() / 3600

    failed_last = last_run and last_run["status"] == "failed"
    if failed_last:
        status = "degraded"
    elif total_lag > 0:
        status = "degraded"
    elif age_hours is None or age_hours > 72:
        status = "stalled"
    else:
        status = "healthy"

    # Orchestration: last execution per pipeline plus the planned next run.
    last_by_pipeline = {
        r["pipeline_name"]: r["started_at"] for r in runs
    }
    orchestration = []
    for dag in as_orchestration(now):
        pipeline = next((p for p, d in DAG_BY_PIPELINE.items() if d["dag_id"] == dag["dag_id"]), dag["dag_id"])
        last = last_by_pipeline.get(pipeline)
        state = "never_run"
        if last:
            matching = next((r for r in runs if r["pipeline_name"] == pipeline), None)
            state = "success" if matching and matching["status"] == "success" else (matching["status"] if matching else "unknown")
        orchestration.append({**dag, "last_run": last, "state": state})

    return {
        "status": status,
        "checked_at": now.isoformat(),
        "last_run": last_run,
        "runs": runs,
        "metrics": metrics,
        "topics": topics,
        "layers": _lake_layers(),
        "orchestration": orchestration,
        "stream_health": {
            "consumer_group": CONSUMER_GROUP,
            "total_lag": total_lag,
            "last_run_age_hours": round(age_hours, 2) if age_hours is not None else None,
        },
    }
