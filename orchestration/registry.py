"""Single source of truth for the Airflow DAG catalogue.

The Airflow DAG files in ``airflow/dags`` build their task graphs from this
registry, and the ``/api/pipeline/status`` endpoint reads the same metadata to
report the orchestration schedule.  Keeping one registry means the dashboard can
never advertise a schedule that Airflow does not actually run.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

DAGS: list[dict[str, Any]] = [
    {
        "dag_id": "ecom_historical_ingestion",
        "pipeline_name": "historical_ingestion",
        "schedule": "0 2 * * *",
        "cron_human": "Daily at 02:00 UTC",
        "description": "Generate / refresh the historical source files and load them into staging.",
        "tasks": ["generate_history", "validate_sources", "load_staging"],
    },
    {
        "dag_id": "ecom_stream_monitor",
        "pipeline_name": "stream_monitor",
        "schedule": "*/5 * * * *",
        "cron_human": "Every 5 minutes",
        "description": "Micro-batch the Kafka topics into the lake and check consumer lag.",
        "tasks": ["process_micro_batch", "check_consumer_lag", "refresh_gold"],
    },
    {
        "dag_id": "ecom_warehouse_load",
        "pipeline_name": "warehouse_load",
        "schedule": "15 2 * * *",
        "cron_human": "Daily at 02:15 UTC",
        "description": "SCD2 dimension load plus incremental fact load into the PostgreSQL star schema.",
        "tasks": ["load_dimensions", "load_facts", "assert_row_counts"],
    },
    {
        "dag_id": "ecom_dbt_transformations",
        "pipeline_name": "dbt_transformations",
        "schedule": "45 2 * * *",
        "cron_human": "Daily at 02:45 UTC",
        "description": "dbt run + dbt test over staging, intermediate and mart models.",
        "tasks": ["dbt_deps", "dbt_run", "dbt_test"],
    },
    {
        "dag_id": "ecom_data_quality",
        "pipeline_name": "data_quality",
        "schedule": "0 3 * * *",
        "cron_human": "Daily at 03:00 UTC",
        "description": "Eight-point data-quality suite across bronze, silver, warehouse and gold.",
        "tasks": ["run_quality_suite", "publish_score"],
    },
    {
        "dag_id": "ecom_daily_sales_aggregation",
        "pipeline_name": "daily_sales_aggregation",
        "schedule": "30 3 * * *",
        "cron_human": "Daily at 03:30 UTC",
        "description": "Refresh analytics.sales_daily and emit the scheduled sales report.",
        "tasks": ["refresh_sales_daily", "build_report"],
    },
]

DAG_BY_PIPELINE = {d["pipeline_name"]: d for d in DAGS}


def next_run(schedule: str, now: datetime | None = None) -> datetime | None:
    """Minimal cron interpretation for the two schedule shapes we use."""
    now = now or datetime.now(timezone.utc)
    parts = schedule.split()
    if len(parts) != 5:
        return None
    minute, hour, dom, month, dow = parts
    if minute.startswith("*/"):
        try:
            step = int(minute[2:])
        except ValueError:
            return None
        base = now.replace(second=0, microsecond=0)
        nxt = base + timedelta(minutes=step - base.minute % step)
        return nxt
    if minute.isdigit() and hour.isdigit():
        target = now.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
    return None


def as_orchestration(now: datetime | None = None) -> list[dict[str, Any]]:
    return [
        {
            "dag_id": d["dag_id"],
            "schedule": d["cron_human"],
            "cron": d["schedule"],
            "description": d["description"],
            "tasks": d["tasks"],
            "next_run": (nr.isoformat() if (nr := next_run(d["schedule"], now)) else None),
        }
        for d in DAGS
    ]
