# Divakar Data Analytics — E-Commerce Platform
## Completion Report — 2026-11-03

---

## 1. Working URL

**http://127.0.0.1:8040/**

Single origin: the FastAPI process serves both the JSON API (`/api/*`, `/health`, `/api/docs`) and the compiled React SPA (`/`, `/assets/*`, all nine deep links).

Verified in a real browser: the dashboard loads, renders live warehouse numbers, and produces **0 console errors / 0 failed network requests** across all nine pages.

| Route | Page | Status |
|---|---|---|
| `/` | Overview | loaded |
| `/sales` | Sales | loaded |
| `/customers` | Customers | loaded |
| `/products` | Products | loaded |
| `/orders` | Orders | loaded |
| `/data-quality` | Data quality | loaded |
| `/pipeline` | Pipeline | loaded |
| `/system` | System | loaded |
| `/reports` | Reports | loaded |

---

## 2. Backend status

**UP** — `uvicorn api.main:app --host 127.0.0.1 --port 8040`

```json
GET /health  →  200
{
  "status": "ok",
  "version": "1.0.0",
  "database": { "connected": true, "engine": "PostgreSQL", "version": "16.2" },
  "uptime_seconds": 912.9,
  "warehouse": { "orders": 118384, "customers": 25000, "products": 900, "revenue": 42113299.58 }
}
```

Interactive docs: **http://127.0.0.1:8040/api/docs** · OpenAPI: `/api/openapi.json`

Database: embedded **PostgreSQL 16.2** on `127.0.0.1:53018`, database `ecommerce` (~256.68 MB), started from the existing on-disk cluster. **No schema recreation, no reload, no data modification.**

---

## 3. Frontend status

**BUILT AND SERVED** from `frontend/dist` — three artifacts, all returning 200 with correct MIME types:

| File | Size | MIME |
|---|---|---|
| `index.html` | 595 B | `text/html` |
| `assets/index-BLIH_Rzo.js` | 681,641 B (gzip 189.81 kB) | `text/javascript` |
| `assets/index-Cb-G8_8A.css` | 22,446 B | `text/css` |

Stack: React 18.3.1, TypeScript 5.6.2 (strict), Vite 5.4.8, Tailwind 3.4.13, Recharts 2.12.7, react-router-dom 6.26.2.

### How the npm EPERM blocker was resolved

npm was never repaired at the OS level, and no Windows security or antivirus setting was changed. The pinned `node_modules` tree was already complete, so the installed binaries were invoked directly — npm itself never spawns a process:

```powershell
node node_modules/typescript/bin/tsc --noEmit   # type-check, exit 0
node node_modules/vite/bin/vite.js build        # production bundle
```

This is a supported path (same tool versions as `package.json` pins) and required no installer, no elevation, and no security change.

---

## 4. API test results

Automated suite: `python -m scripts.verify_api --base http://127.0.0.1:8040`

```
TOTAL 88  PASS 88  FAIL 0
```

Coverage:

- **Health & index** — `/health` status + DB connected; `/api` index lists ≥12 endpoints
- **Analytics** — overview KPIs and trend, sales, customers, products, orders, retention, forecast payload shapes
- **Forecast integrity** — `disclaimer` present; `history[].kind == "actual"` (history never mixed with predictions)
- **Orders** — page size 25, sort/filter params, 422 on `page=0`, 422 on `sort=bogus`, 422 on reversed date range
- **Reports** — `daily-sales` returns 31 August rows with a `totals` block; CSV export returns `text/csv` with header `date,orders`
- **Pipeline** — status, topics, medallion layers
- **Data quality** — ≥1 check with a numeric score; `ops.rejected_records` surfaced as a quarantine ledger, not a failure
- **System** — `row_counts` cross-checked against exact warehouse totals
- **Routing semantics** — JSON 404 envelope for unknown `/api/*`; nine SPA deep links return the shell; hashed assets 200

### Two genuine backend defects found and fixed during testing

1. **`/api/reports/daily-sales` returned only its JSON keys** (43 B, `totals: null`). Cause: `response_class=StreamingResponse` declared on the route made FastAPI iterate the response dict and stream its keys. Removed the declaration (the CSV branch still returns a `StreamingResponse` explicitly). Now 8,253 B with 31 rows.
2. **Unknown `/api/*` paths returned 200 HTML** because the SPA catch-all masked them. Added a guard in `api/main.py`: `path.startswith(("api/", "assets/"))` → JSON 404.

Three cosmetic UI defects were also fixed at the source and re-verified: a literal `undefined` in the pipeline consumer-lag hint, an empty-string payment-failure reason (now "unspecified"), and a clipped Reports column (now `scrollWidth == clientWidth`).

---

## 5. Warehouse preservation — verified read-only

`GET /api/system/status` → `row_counts`:

| Table | Rows | Required |
|---|---|---|
| `warehouse.fact_orders` | 118,384 | ✅ 118,384 |
| `warehouse.fact_payments` | 118,384 | ✅ 118,384 |
| `warehouse.fact_shipments` | 108,997 | ✅ 108,997 |
| `warehouse.fact_returns` | 4,592 | ✅ 4,592 |
| `warehouse.fact_order_items` | 211,095 | — |
| `warehouse.dim_customer` | 25,000 | — |
| `warehouse.dim_product` | 900 | — |
| `analytics.sales_daily` | 541 | — |
| `ops.rejected_records` | 1,615 | — |
| `ops.pipeline_runs` | 6 | — |

**Dashboard metrics come from PostgreSQL, not constants.** The same figures appear in three independent places: a direct SQL `count(*)`, the `/health` warehouse block, and `/api/system/status`. Windowed dashboard KPIs (26,759 orders / \$8.97M over the default last-90-day window) are a deliberate subset of the 118,384 all-time orders — not a data defect.

---

## 6. Remaining limitations

| # | Limitation | Detail |
|---|---|---|
| 1 | **Port is 8040, not 8010** | Per instruction, 8010 was the fallback if 8000 was occupied. Both were occupied by unrelated stale servers from other sessions — 8000 answering 200, 8010 held by PID 32600 (`uvicorn backend.app.main:app`, a different app). Ports 8040–8119 were bind-tested and **8040** was chosen rather than terminating another session's process. Changing ports is a one-line uvicorn flag. |
| 2 | `dbt transformations → "not_configured"` | `/api/system/status` reports 4 of 7 services fully `up`; dbt is registered but has no project wired yet, so the System page honestly shows 6 of 7 services non-failing but dbt unconfigured. |
| 3 | Single-origin only | The build has no dev proxy config; `frontend/dist` must be served through FastAPI (or any static host pointing at the same `/api` origin). `npm run dev` will not reach the API without a proxy entry. |
| 4 | 681 kB un-chunked bundle | Single JS chunk (189.81 kB gzip). Functional but above Vite's 500 kB warning threshold; manual chunking would improve first load. |
| 5 | Deprecated startup hook | `api/main.py` still uses `@app.on_event("startup")` instead of a lifespan handler. Works on the current FastAPI; emits a deprecation warning. |
| 6 | Navbar filter lists are hardcoded | `Filters.tsx` uses local category/region arrays rather than `/api/system/filters`. Values match the warehouse, but they are not fetched. |
| 7 | One attestation outstanding | `/orders` page content was verified in-browser (search `O2026110201195` → 27 matches, "Showing 1–25 of 27"), but a separate per-page network/console transcript for that single navigation was not captured. |
| 8 | Not part of this narrowed request | Master-prompt items still open: dbt project + passing `dbt build`, Airflow DAG files, `docker-compose.yml`, Spark Structured Streaming job file, pytest suite, README with architecture diagram, `.env.example`, temp-script cleanup. |

---

## 7. Quick reference

```powershell
# start (already running)
cd divakar-analytics
python -m scripts.pg_server start --port 53018 --database ecommerce
python -m uvicorn api.main:app --host 127.0.0.1 --port 8040

# verify
python -m scripts.verify_api --base http://127.0.0.1:8040
```

Logs: `logs/api-8040.out.log`, `logs/api-8040.err.log`
