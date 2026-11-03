import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import common  # noqa
from common.db import fetch_all
for q in [
  "SELECT 'fact_orders' t, count(*) n FROM warehouse.fact_orders",
  "SELECT 'fact_items' t, count(*) n FROM warehouse.fact_order_items",
  "SELECT 'fact_payments' t, count(*) n FROM warehouse.fact_payments",
  "SELECT 'fact_shipments' t, count(*) n FROM warehouse.fact_shipments",
  "SELECT 'fact_returns' t, count(*) n FROM warehouse.fact_returns",
  "SELECT 'sales_daily' t, count(*) n FROM analytics.sales_daily",
  "SELECT 'stream_events' t, count(*) n FROM ops.stream_events",
  "SELECT 'pipeline_runs' t, count(*) n FROM ops.pipeline_runs",
]:
    print(fetch_all(q)[0])
