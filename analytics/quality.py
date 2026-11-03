"""Read-side view of ``ops.data_quality_results`` for the /api/data-quality endpoint."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from common.db import fetch_all, fetch_one, fetch_scalar

_CURRENT_SQL = """
WITH latest AS (
    SELECT MAX(run_at) AS run_at FROM ops.data_quality_results
)
SELECT check_id, check_name, layer, table_name, severity, status,
       records_checked, records_failed, failure_rate, details,
       run_at
FROM ops.data_quality_results
WHERE run_at = (SELECT run_at FROM latest)
ORDER BY CASE layer WHEN 'bronze' THEN 1 WHEN 'silver' THEN 2 WHEN 'warehouse' THEN 3 WHEN 'gold' THEN 4 ELSE 5 END,
         status DESC, records_failed DESC
"""

_WEIGHT = {"critical": 2.0, "warning": 1.0}


def _score(rows: list[dict[str, Any]]) -> float:
    weight_sum = 0.0
    weighted = 0.0
    for r in rows:
        weight = _WEIGHT.get(str(r["severity"]).lower(), 1.0)
        checked = float(r["records_checked"] or 0)
        failed = float(r["records_failed"] or 0)
        frac = min(1.0, failed / checked) if checked else (1.0 if r["status"] == "failed" else 0.0)
        weight_sum += weight
        weighted += weight * (1.0 - frac)
    return round(weighted / weight_sum * 100, 2) if weight_sum else 100.0


def _quarantine() -> dict[str, Any]:
    """Rows rejected by warehouse business rules, by reason.

    These are *not* quality check failures: they are the audit trail proving the
    validation rules fired and that invalid source rows never reached the facts.
    """
    try:
        rows = fetch_all(
            "SELECT reason, COUNT(*) AS n FROM ops.rejected_records GROUP BY reason ORDER BY n DESC"
        )
        source = fetch_scalar(
            "SELECT COUNT(DISTINCT order_id) FROM staging.raw_orders WHERE COALESCE(order_id, '') <> ''"
        )
    except Exception:  # staging/reject tables only exist after a batch load
        return {"rejected": 0, "source_orders": 0, "rejection_rate": 0.0, "reasons": []}
    reasons = [{"reason": r["reason"], "records": int(r["n"])} for r in rows]
    rejected = sum(r["records"] for r in reasons)
    total = int(source or 0)
    return {
        "rejected": rejected,
        "source_orders": total,
        "rejection_rate": round(rejected / total * 100, 2) if total else 0.0,
        "reasons": reasons,
    }


def get_data_quality() -> dict[str, Any]:
    rows = fetch_all(_CURRENT_SQL)
    if not rows:
        return {
            "score": 0.0,
            "summary": {"total": 0, "passed": 0, "failed": 0, "critical_failed": 0},
            "by_layer": [],
            "checks": [],
            "trend": [],
            "quarantine": _quarantine(),
            "run_at": None,
            "note": "No data-quality run recorded yet. Trigger POST /api/pipeline/trigger?task=quality to execute the suite.",
        }

    checks: list[dict[str, Any]] = []
    for r in rows:
        checks.append(
            {
                "check_id": int(r["check_id"]),
                "check_name": r["check_name"],
                "layer": r["layer"],
                "table_name": r["table_name"],
                "severity": r["severity"],
                "status": r["status"],
                "records_checked": int(r["records_checked"] or 0),
                "records_failed": int(r["records_failed"] or 0),
                "failure_rate": round(float(r["failure_rate"] or 0), 4),
                "details": r["details"] or "",
                "run_at": r["run_at"].isoformat() if isinstance(r["run_at"], datetime) else str(r["run_at"]),
            }
        )

    by_layer: dict[str, dict[str, Any]] = {}
    for c in checks:
        bucket = by_layer.setdefault(
            c["layer"], {"layer": c["layer"], "total": 0, "passed": 0, "failed": 0, "score": 0.0, "_rows": []}
        )
        bucket["total"] += 1
        bucket["passed" if c["status"] == "passed" else "failed"] += 1
        bucket["_rows"].append(c)
    for bucket in by_layer.values():
        bucket["score"] = _score(bucket.pop("_rows"))

    trend_rows = fetch_all(
        """
        SELECT run_at,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'failed') AS failed
        FROM ops.data_quality_results
        GROUP BY run_at
        ORDER BY run_at DESC
        LIMIT 20
        """
    )
    trend = []
    for t in reversed(trend_rows):
        day_rows = fetch_all(
            """
            SELECT severity, status, records_checked, records_failed
            FROM ops.data_quality_results WHERE run_at = :run_at
            """,
            {"run_at": t["run_at"]},
        )
        trend.append(
            {
                "run_at": t["run_at"].isoformat() if isinstance(t["run_at"], datetime) else str(t["run_at"]),
                "score": _score(day_rows),
                "failed": int(t["failed"] or 0),
            }
        )

    summary = {
        "total": len(checks),
        "passed": sum(1 for c in checks if c["status"] == "passed"),
        "failed": sum(1 for c in checks if c["status"] == "failed"),
        "critical_failed": sum(1 for c in checks if c["status"] == "failed" and c["severity"] == "critical"),
    }
    latest_run = rows[0]["run_at"]
    return {
        "score": _score(rows),
        "summary": summary,
        "by_layer": sorted(by_layer.values(), key=lambda b: ["bronze", "silver", "warehouse", "gold"].index(b["layer"])
                           if b["layer"] in ["bronze", "silver", "warehouse", "gold"] else 9),
        "checks": checks,
        "trend": trend,
        "quarantine": _quarantine(),
        "run_at": latest_run.isoformat() if isinstance(latest_run, datetime) else str(latest_run),
    }


def latest_score() -> float:
    row = fetch_one(
        """
        SELECT severity, status, records_checked, records_failed
        FROM ops.data_quality_results
        WHERE run_at = (SELECT MAX(run_at) FROM ops.data_quality_results)
        """
    )
    if not row:
        return 0.0
    rows = fetch_all(
        """
        SELECT severity, status, records_checked, records_failed
        FROM ops.data_quality_results
        WHERE run_at = (SELECT MAX(run_at) FROM ops.data_quality_results)
        """
    )
    return _score(rows)
