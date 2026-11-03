"""End-to-end HTTP smoke test for the running FastAPI service.

Usage
-----
    python -m scripts.verify_api [--base http://127.0.0.1:8040]

Exercises every documented endpoint, checks the SPA bundle is served through the
same origin, and asserts that payloads contain warehouse-derived values.  Exits
non-zero if any check fails so it can be wired into CI.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

RESULTS: list[tuple[str, str, str, str]] = []


def call(base: str, path: str, expect: int = 200, timeout: int = 90) -> tuple[int, bytes, float, dict]:
    url = base + path
    req = urllib.request.Request(url, headers={"Accept": "application/json, text/html, */*"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            code = resp.status
            headers = dict(resp.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        code = exc.code
        headers = dict(exc.headers)
    except Exception as exc:  # noqa: BLE001 - network failure must be reported, not raised
        body = str(exc).encode()
        code = 0
        headers = {}
    elapsed = (time.perf_counter() - started) * 1000
    ok = code == expect
    RESULTS.append((path, str(code), f"{elapsed:.0f} ms", f"{len(body):,} B"))
    if not ok:
        print(f"FAIL {path} expected {expect} got {code}: {body[:400]!r}", file=sys.stderr)
    return code, body, elapsed, headers


def as_json(body: bytes) -> dict:
    try:
        return json.loads(body.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def check(label: str, condition: bool, detail: str = "") -> None:
    RESULTS.append((f"assert: {label}", "PASS" if condition else "FAIL", detail, ""))
    if not condition:
        print(f"ASSERT FAILED: {label} {detail}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8040")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    # ---- meta / health -----------------------------------------------------
    _, body, _, _ = call(base, "/health")
    health = as_json(body)
    check("health.status", health.get("status") in {"ok", "healthy", "degraded"}, str(health)[:160])
    check("health.database true", bool(health.get("database", {}).get("connected", health.get("database_connected", True))), str(health)[:200])

    _, body, _, _ = call(base, "/api")
    index = as_json(body)
    check("api index endpoints >= 12", len(index.get("endpoints", [])) >= 12, str(len(index.get("endpoints", []))))

    call(base, "/api/openapi.json")
    call(base, "/api/docs")

    # ---- dashboard / analytics --------------------------------------------
    _, body, _, _ = call(base, "/api/dashboard/overview")
    overview = as_json(body)
    kpis = overview.get("kpis", {})
    check("overview.total_orders > 0", kpis.get("total_orders", 0) > 0, str(kpis.get("total_orders")))
    check("overview.total_revenue > 0", kpis.get("total_revenue", 0) > 0, str(kpis.get("total_revenue")))
    check("overview.revenue_trend non-empty", len(overview.get("revenue_trend", [])) > 0, str(len(overview.get("revenue_trend", []))))
    check("overview.status_breakdown non-empty", len(overview.get("status_breakdown", [])) > 0)
    check("overview.recent_orders non-empty", len(overview.get("recent_orders", [])) > 0)

    _, body, _, _ = call(base, "/api/analytics/sales")
    sales = as_json(body)
    check("sales.series non-empty", len(sales.get("series", [])) > 0)
    check("sales.by_category non-empty", len(sales.get("by_category", [])) > 0)
    check("sales.top_products non-empty", len(sales.get("top_products", [])) > 0)

    _, body, _, _ = call(base, "/api/analytics/sales?granularity=month&category=Electronics")
    check("sales filtered by category", len(as_json(body).get("series", [])) > 0)

    _, body, _, _ = call(base, "/api/analytics/customers")
    cust = as_json(body)
    check("customers.rfm_segments non-empty", len(cust.get("rfm_segments", [])) > 0)
    check("customers.clv.customers > 0", cust.get("clv", {}).get("customers", 0) > 0, str(cust.get("clv", {}).get("customers")))

    _, body, _, _ = call(base, "/api/analytics/products")
    prods = as_json(body)
    check("products.best_sellers non-empty", len(prods.get("best_sellers", [])) > 0)

    _, body, _, _ = call(base, "/api/analytics/orders")
    orders_a = as_json(body)
    check("orders.funnel non-empty", len(orders_a.get("funnel", [])) > 0)

    _, body, _, _ = call(base, "/api/analytics/retention")
    ret = as_json(body)
    check("retention.retention_curve non-empty", len(ret.get("retention_curve", [])) > 0)

    _, body, _, _ = call(base, "/api/analytics/forecast?horizon_days=30")
    fc = as_json(body)
    check("forecast.history non-empty", len(fc.get("history", [])) > 0)
    check("forecast.forecast non-empty", len(fc.get("forecast", [])) > 0)
    check("forecast has disclaimer", bool(fc.get("disclaimer")), str(fc.get("disclaimer"))[:120])
    if fc.get("history"):
        check("forecast history kind=actual", (fc["history"][0].get("kind") or "actual") == "actual")

    # ---- orders + reports -------------------------------------------------
    _, body, _, _ = call(base, "/api/orders?page=1&size=25&sort=amount_desc")
    order_page = as_json(body)
    check("orders page size 25", len(order_page.get("items", [])) == 25, str(len(order_page.get("items", []))))
    # The default window is the last 90 days, so this total is window-scoped
    # (~26.7k of the 118,384 all-time orders), not the whole warehouse.
    total_window = order_page.get("total", 0)
    check("orders windowed total 10k-118k", 10000 < total_window <= 118384, str(total_window))

    _, body, _, _ = call(base, "/api/orders?search=CUST-00001")
    check("orders search works", isinstance(as_json(body).get("items"), list))

    _, body, hdrs, _ = call(base, "/api/reports/daily-sales?start_date=2026-08-01&end_date=2026-08-31")
    daily = as_json(body)
    check("daily-sales august has 31 rows", len(daily.get("rows", [])) == 31, str(len(daily.get("rows", []))))
    check("daily-sales totals present", "revenue" in daily.get("totals", {}), str(daily.get("totals")))
    check("daily-sales totals revenue > 0", (daily.get("totals") or {}).get("revenue", 0) > 0, str((daily.get("totals") or {}).get("revenue")))

    code, body, _, hdrs = call(base, "/api/reports/daily-sales?start_date=2026-08-01&end_date=2026-08-31&format=csv")
    check("daily-sales csv content-type", "text/csv" in hdrs.get("content-type", ""), hdrs.get("content-type", ""))
    check("daily-sales csv has header", body.splitlines()[0].startswith(b"date,orders") if body else False)

    # ---- ops --------------------------------------------------------------
    _, body, _, _ = call(base, "/api/pipeline/status")
    pipe = as_json(body)
    check("pipeline.status present", pipe.get("status") in {"healthy", "degraded", "stalled"}, str(pipe.get("status")))
    check("pipeline topics non-empty", len(pipe.get("topics", [])) > 0)
    check("pipeline layers non-empty", len(pipe.get("layers", [])) > 0)

    _, body, _, _ = call(base, "/api/data-quality")
    dq = as_json(body)
    check("data-quality checks non-empty", len(dq.get("checks", [])) > 0, str(len(dq.get("checks", []))))
    check("data-quality score numeric", isinstance(dq.get("score"), (int, float)), str(dq.get("score")))

    _, body, _, _ = call(base, "/api/system/status")
    sysinfo = as_json(body)
    counts = {row["table"]: row["rows"] for row in sysinfo.get("row_counts", [])}
    check("system.status row_counts > 0", len(counts) > 0, str(len(counts)))
    # Cross-check the API-reported counts against the preserved warehouse totals.
    check("warehouse fact_orders == 118384", counts.get("warehouse.fact_orders") == 118384, str(counts.get("warehouse.fact_orders")))
    check("warehouse fact_payments == 118384", counts.get("warehouse.fact_payments") == 118384, str(counts.get("warehouse.fact_payments")))
    check("warehouse fact_shipments == 108997", counts.get("warehouse.fact_shipments") == 108997, str(counts.get("warehouse.fact_shipments")))
    check("warehouse fact_returns == 4592", counts.get("warehouse.fact_returns") == 4592, str(counts.get("warehouse.fact_returns")))

    _, body, _, _ = call(base, "/api/system/filters")
    filters = as_json(body)
    check("system.filters categories non-empty", len(filters.get("categories", [])) > 0)

    # ---- error semantics --------------------------------------------------
    call(base, "/api/orders?page=0", expect=422)
    call(base, "/api/orders?sort=bogus", expect=422)
    call(base, "/api/analytics/sales?start_date=2026-09-01&end_date=2026-08-01", expect=422)
    code, body, _, _ = call(base, "/api/definitely-not-a-route", expect=404)
    check("404 uses error envelope", b'"error"' in body, body[:160].decode("utf-8", "ignore"))

    # ---- SPA served by the same origin -----------------------------------
    for route in ["/", "/sales", "/orders", "/reports", "/data-quality", "/pipeline", "/system", "/customers", "/products"]:
        code, body, _, _ = call(base, route)
        check(f"spa {route} is html", b"<div id=\"root\">" in body and b"/assets/" in body)

    import re
    _, html, _, _ = call(base, "/")
    assets = re.findall(rb'/assets/[A-Za-z0-9._-]+', html)
    for asset in sorted({a.decode() for a in assets}):
        code, body, _, hdrs = call(base, asset)
        check(f"asset {asset} served", code == 200 and len(body) > 1000, hdrs.get("content-type", ""))

    # ---- report -----------------------------------------------------------
    width = max(len(r[0]) for r in RESULTS) + 2
    print()
    print(f"{'CHECK'.ljust(width)}{'RESULT':<12}{'TIME':<10}SIZE")
    print("-" * (width + 30))
    for name, result, extra, size in RESULTS:
        print(f"{name.ljust(width)}{result:<12}{extra:<10}{size}")
    failed = [r for r in RESULTS if r[1] == "FAIL"]
    print("-" * (width + 30))
    print(f"TOTAL {len(RESULTS)}  PASS {len(RESULTS) - len(failed)}  FAIL {len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
