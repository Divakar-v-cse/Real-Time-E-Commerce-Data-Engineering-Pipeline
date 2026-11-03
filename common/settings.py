"""Central configuration.

Resolution order for the warehouse connection:
  1. explicit ``DATABASE_URL`` environment variable
  2. ``.state/pg.json`` written by ``scripts/pg_server.py`` (embedded Postgres)
  3. docker-compose default (``postgresql://postgres:postgres@localhost:5432/ecommerce``)
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

STATE_DIR = PROJECT_ROOT / ".state"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
LAKE_DIR = DATA_DIR / "lake"
PG_DATA_DIR = PROJECT_ROOT / ".pgdata"
PG_STATE_FILE = STATE_DIR / "pg.json"

DEFAULT_DOCKER_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/ecommerce"


def _embedded_pg_url() -> str | None:
    if not PG_STATE_FILE.exists():
        return None
    try:
        state = json.loads(PG_STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    host, port = state.get("host"), state.get("port")
    if not host or not port:
        return None
    user = state.get("user", "postgres")
    dbname = state.get("database", "ecommerce")
    pwd = state.get("password", "")
    auth = f"{user}:{pwd}" if pwd else user
    return f"postgresql+psycopg2://{auth}@{host}:{port}/{dbname}"


@lru_cache(maxsize=1)
def database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return _embedded_pg_url() or DEFAULT_DOCKER_URL


class Settings:
    """Lightweight settings object (no external deps needed)."""

    app_name: str = "Divakar Data Analytics E-Commerce Project"
    api_prefix: str = "/api"
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    kafka_bootstrap: str = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    use_real_kafka: bool = os.getenv("USE_REAL_KAFKA", "false").lower() == "true"
    minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    lake_bucket: str = os.getenv("LAKE_BUCKET", "ecommerce-lake")
    late_arrival_tolerance_days: int = int(os.getenv("LATE_TOLERANCE_DAYS", "5"))
    frontend_dist: str = str(PROJECT_ROOT / "frontend" / "dist")

    @property
    def database_url(self) -> str:
        return database_url()


settings = Settings()
