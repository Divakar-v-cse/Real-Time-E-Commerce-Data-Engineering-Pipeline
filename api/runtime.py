"""Process metadata shared by the health and system-status endpoints."""
from __future__ import annotations

import os
from datetime import datetime, timezone

VERSION = "1.0.0"
APP_NAME = "Divakar Data Analytics E-Commerce Project"
STARTED_AT = datetime.now(timezone.utc)


def uptime_seconds() -> float:
    return round((datetime.now(timezone.utc) - STARTED_AT).total_seconds(), 1)


def environment() -> str:
    if os.getenv("APP_ENV"):
        return os.environ["APP_ENV"]
    return "development" if os.getenv("DEBUG", "false").lower() == "true" else "production-local"
