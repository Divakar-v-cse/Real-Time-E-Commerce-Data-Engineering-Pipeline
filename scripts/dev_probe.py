"""Development probe: quick warehouse/QoL inspection used while building."""
from __future__ import annotations

import json
import sys

from common.db import fetch_all, fetch_scalar, healthcheck


def q(sql: str, limit: int = 40) -> None:
    rows = fetch_all(sql)
    print(json.dumps(rows[:limit], indent=2, default=str))


if __name__ == "__main__":
    sql = sys.argv[1] if len(sys.argv) > 1 else None
    if not sql:
        print("healthcheck:", healthcheck())
        for label, stmt in [
            ("fact_orders", "SELECT count(*) FROM warehouse.fact_orders"),
            ("fact_items", "SELECT count(*) FROM warehouse.fact_order_items"),
            ("sales_daily", "SELECT count(*) FROM analytics.sales_daily"),
            ("dq_rows", "SELECT count(*) FROM ops.data_quality_results"),
        ]:
            print(f"{label}: {fetch_scalar(stmt)}")
    else:
        q(sql)
