from common.db import fetch_scalar as f

print("min", f("SELECT min(sales_date) FROM analytics.sales_daily"))
print("max", f("SELECT max(sales_date) FROM analytics.sales_daily"))
print("aug_sep", f("SELECT count(1) FROM analytics.sales_daily WHERE sales_date >= DATE '2026-08-01' AND sales_date < DATE '2026-09-01'"))
print("total_orders_all", f("SELECT count(1) FROM warehouse.fact_orders"))
print("orders_last90", f("SELECT count(1) FROM warehouse.fact_orders WHERE order_ts >= DATE '2026-08-05'"))
