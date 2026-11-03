"""Airflow DAG catalogue shared by the scheduler and the API."""
from orchestration.registry import DAGS, DAG_BY_PIPELINE, as_orchestration, next_run

__all__ = ["DAGS", "DAG_BY_PIPELINE", "as_orchestration", "next_run"]
