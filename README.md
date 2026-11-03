# Divakar — Real-Time E-Commerce Data Engineering Pipeline

An end-to-end e-commerce analytics platform: synthetic event generation → Kafka-style streaming → medallion lakehouse → PostgreSQL star schema → analytics layer → FastAPI → React dashboard.

Synthetic data, a real warehouse, and a dashboard where **every number is read from the database at request time** — not mocked in the frontend.

---

## Highlights

| | |
|---|---|
| **Warehouse** | 118,384 orders · 118,384 payments · 108,997 shipments · 4,592 returns · 211,095 order items |
| **Dimensions** | 25,000 customers (SCD Type 2) · 900 products |
| **API** | 17 business endpoints + 3 framework routes, OpenAPI documented |
| **Dashboard** | 9 responsive pages, React 18 + TypeScript + Recharts |
| **Data quality** | 28 automated checks across bronze / silver / warehouse / gold — currently 100/100 |
| **Streaming** | At-least-once micro-batch with offsets, consumer lag, replay and a dead-letter queue |

---

## Architecture

```
                    ┌──────────────────────────┐
                    │  pipeline/generator      │  synthetic orders, payments,
                    │  catalog · factory       │  shipments, returns
                    └────────────┬─────────────┘
                                 │  direct extract (historical)
                                 │  ┌──────────────────────────────┐
                                 ├─▶│ pipeline/generator/          │
                                 │  │ generate_historical.py       │──▶ data/raw/*.csv
                                 │  └──────────────────────────────┘
                                 │  streaming events
                    ┌────────────▼─────────────┐
                    │  pipeline/streaming      │
                    │  producer → broker       │  topics: ecom.orders.raw,
                    │  (Kafka-compatible log)  │  ecom.payments.raw, ecom.shipments.raw,
                    └────────────┬─────────────┘  ecom.returns.raw, ecom.orders.dlq
                                 │  micro-batch consume
                    ┌────────────▼─────────────┐
                    │  processor               │
                    │  validate · dedupe ·     │
                    │  quarantine · aggregate  │
                    └────┬──────────────┬──────┘
                         │              │
              ┌──────────▼───┐   ┌──────▼──────────────┐
              │ Medallion    │   │ warehouse/          │
              │ lake         │   │ load.py  (batch)    │
              │ bronze →     │   │ stream_sink.py      │
              │ silver →     │   │ (idempotent upsert) │
              │ gold         │   └──────┬──────────────┘
              └──────────────┘          │
                                        ▼
                        ┌───────────────────────────────┐
                        │ PostgreSQL — star schema      │
                        │  warehouse.fact_* / dim_*     │
                        │  analytics.sales_daily        │
                        │  ops.* (runs, quality, log)   │
                        └───────────────┬───────────────┘
                                        │ analytics/*.py
                        ┌───────────────▼───────────────┐
                        │ FastAPI  (api/)               │
                        │  17 endpoints + OpenAPI       │
                        │  serves the built SPA         │
                        └───────────────┬───────────────┘
                                        │ JSON
                        ┌───────────────▼───────────────┐
                        │ React dashboard (frontend/)   │
                        │  9 pages · Vite build         │
                        └───────────────────────────────┘
```

---

## Technology stack

| Layer | Target technology | Implemented as |
|---|---|---|
| Event bus | Apache Kafka | `pipeline/streaming/broker.py` — durable, partitioned, append-only log with topics, offsets, consumer groups and lag, matching Kafka semantics. `USE_REAL_KAFKA=true` switches the producer/consumer to `kafka-python`. |
| Stream processing | Spark Structured Streaming | `pipeline/streaming/processor.py` — micro-batch processor running the same logical plan (bronze → validate/dedupe → silver → gold). The Spark job file itself is not included; see [Known gaps](#known-gaps). |
| Lakehouse | S3 / MinIO medallion | Local Parquet with `bronze/ silver/ gold/` layout under `data/lake/` |
| Warehouse | PostgreSQL | PostgreSQL 16 (embedded `pgserver` for a zero-install start; any Postgres works via `DATABASE_URL`) |
| Transformations | dbt | Analytics SQL lives in `analytics/*.py` + `analytics.sales_daily`. A dbt project is **not** yet wired into the runtime. |
| Orchestration | Airflow | `orchestration/registry.py` holds the metadata for 6 DAGs; DAG files are not yet generated. |
| API | FastAPI + Uvicorn | `api/` — schemas, routes, middleware, SPA hosting |
| Frontend | React + TypeScript | React 18.3, TypeScript 5.6 (strict), Vite 5.4, Tailwind 3.4, Recharts 2.12 |

---

## Repository layout

```
divakar-analytics/
├── api/                       FastAPI application
│   ├── main.py                app factory, middleware, error handlers, SPA hosting
│   ├── routes_analytics.py    overview, sales, customers, products, orders, retention, forecast
│   ├── routes_orders.py       order browser, daily-sales report (JSON + CSV)
│   ├── routes_ops.py          pipeline, data quality, system, events, filters
│   ├── deps.py                pagination + window query params
│   ├── runtime.py             runtime state helpers
│   └── schemas.py             Pydantic response models
├── analytics/                 Read-side SQL and models
│   ├── base.py                connection + Window helper
│   ├── overview.py sales.py customers.py products.py
│   ├── orders.py order_list.py retention.py
│   ├── forecast.py            trend + day-of-week seasonality, residual bands
│   ├── quality.py pipeline.py
├── warehouse/                 Write path
│   ├── ddl_postgres.sql       star schema DDL
│   ├── load.py                batch ELT: CSV → staging → warehouse
│   └── stream_sink.py         idempotent upserts for the streaming path
├── pipeline/
│   ├── generator/             catalog, factory, schemas, generate_historical
│   ├── streaming/             broker, producer, processor
│   └── quality/checks.py      28 quality checks + severity-weighted scoring
├── orchestration/registry.py  single source of truth for the Airflow DAG catalogue
├── common/                    settings, db helpers, logging
├── frontend/                  React + TypeScript dashboard
├── scripts/                   pg_server, verify_api, dev utilities
├── outputs/                   verification reports
├── requirements.txt
└── .env.example
```

---

## Quickstart

**Prerequisites:** Python 3.12+, Node.js 18+.

### 1. Python dependencies

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# Unix:     source .venv/bin/activate
pip install -r requirements.txt
pip install pgserver psycopg2-binary psutil   # only for the embedded-Postgres shortcut
```

### 2. Start PostgreSQL

Either point `DATABASE_URL` at an existing server:

```bash
cp .env.example .env      # then edit DATABASE_URL
```

…or use the zero-install embedded server:

```bash
python -m scripts.pg_server start --port 53018 --database ecommerce
python -m scripts.pg_server status
```

`pg_server` writes `.state/pg.json`, which `common/settings.py` picks up automatically — no environment variables required.

### 3. Generate data and load the warehouse

```bash
python -m pipeline.generator.generate_historical --orders 120000 --days 540
python -m warehouse.load                 # schema + bulk load
```

`warehouse.load --rebuild` drops and recreates the schemas. **`--rebuild` is destructive — the default run is incremental-safe.**

### 4. Run the streaming path (optional)

```bash
python -m pipeline.streaming.producer --rate 5 --count 200
python -m pipeline.streaming.processor --once
```

`--interval` / `--batch-size` tune the continuous micro-batch loop; omit `--once` to keep consuming.

### 5. Data quality

```bash
python -m pipeline.quality.checks --groups warehouse,lake,gold
```

### 6. API + dashboard

```bash
python -m uvicorn api.main:app --host 127.0.0.1 --port 8040
```

### 7. Build the frontend

```bash
cd frontend
npm ci
npm run build
```

If `npm` cannot spawn an installer in your environment (`EPERM`, `errno -4048`), the pinned `node_modules` tree can be driven directly — no installer, no security changes:

```bash
node node_modules/typescript/bin/tsc -b
node node_modules/vite/bin/vite.js build
```

The built bundle is served by FastAPI from `frontend/dist`, so a single process serves both the API and the UI:

- Dashboard — <http://127.0.0.1:8040/>
- Swagger UI — <http://127.0.0.1:8040/api/docs>
- Health — <http://127.0.0.1:8040/health>

> `frontend/dist` is git-ignored (build output). Run the build before serving.

---

## API reference

Interactive docs at `/api/docs`.

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness, DB connectivity, warehouse totals, uptime |
| GET | `/api` | Endpoint index |
| GET | `/api/dashboard/overview` | Headline KPIs, trend series, top categories |
| GET | `/api/analytics/sales` | Revenue/orders by period, growth, averages |
| GET | `/api/analytics/customers` | Segmentation, RFM buckets, new vs returning |
| GET | `/api/analytics/products` | Product performance, category mix |
| GET | `/api/analytics/orders` | Status funnel, AOV, payment and shipping mix |
| GET | `/api/analytics/retention` | Cohort retention matrix |
| GET | `/api/analytics/forecast` | Forecast with `history[]` actuals, confidence band, disclaimer |
| GET | `/api/orders` | Paginated order browser with filters and sorting |
| GET | `/api/reports/daily-sales` | Daily sales table; `format=csv` streams a CSV export |
| GET | `/api/data-quality` | 28 checks with severity-weighted score |
| GET | `/api/pipeline/status` | Topics, lag, medallion layers, recent runs |
| POST | `/api/pipeline/trigger` | Trigger a pipeline stage |
| POST | `/api/events/generate` | Generate live events through the producer |
| GET | `/api/system/status` | Row counts, service health, environment |
| GET | `/api/system/filters` | Distinct categories, regions, statuses, date bounds |

Common query params on analytics routes: `start_date`, `end_date`, `category`, `region`. Default window is the **last 90 days**.

---

## Data model

Kimball star schema in the `warehouse` schema:

| Table | Type | Rows |
|---|---|---|
| `fact_orders` | fact | 118,384 |
| `fact_order_items` | fact | 211,095 |
| `fact_payments` | fact | 118,384 |
| `fact_shipments` | fact | 108,997 |
| `fact_returns` | fact | 4,592 |
| `dim_customer` | dimension (SCD2) | 25,000 |
| `dim_product` | dimension | 900 |
| `analytics.sales_daily` | gold aggregate (day grain) | 541 |
| `ops.rejected_records` | quarantine ledger | 1,615 |
| `ops.pipeline_runs` | run telemetry | 6 |
| `ops.data_quality_results` | check results | 1 row / check / run |

DDL: [`warehouse/ddl_postgres.sql`](warehouse/ddl_postgres.sql).

### Notes on interpreting the numbers

- `analytics.sales_daily` is at **day grain only** — no category or region dimension. When those filters are applied the API returns a `note` rather than pretending to slice by them.
- The dashboard's default window is the last 90 days, so windowed KPIs (≈26.8k orders) are a deliberate subset of the 118,384 all-time orders.
- Returning rows are quarantined in `ops.rejected_records` and reported as an audit trail, not as a failed quality check. `quarantine.rejection_rate` is surfaced alongside.

---

## Data quality

28 checks run across four layers:

- **bronze** — event envelope integrity, missing values, duplicate `(topic, partition, offset)` triples
- **silver** — duplicate `order_id`, negative values, timestamp normalisation
- **warehouse** — missing values, duplicate records, invalid order totals, negative prices, invalid customer IDs, incorrect timestamps, referential integrity, data freshness
- **gold** — aggregate reconciliation against the facts

Each check is severity-weighted (critical > warning > info) into a 0–100 run score, so one critical failure hurts more than a cosmetic warning.

---

## Dashboard

Nine pages, all reading live API data: **Overview · Sales · Customers · Products · Orders · Data Quality · Pipeline · System · Reports**.

- The forecast chart renders history as a solid line and predictions as a dashed line over a shaded confidence band, with an explicit "model output, not actuals" disclaimer.
- Global date/category/region filters live in `frontend/src/context/Filters.tsx` and drive every page.
- Loading, empty and error states are handled per panel rather than with a global spinner.

---

## Verification

```bash
python -m scripts.verify_api --base http://127.0.0.1:8040
```

Covers health and DB connectivity, the endpoint index, all analytics payload shapes, forecast/actual separation, orders pagination and validation (`422` on `page=0`, `sort=bogus`, reversed date ranges), CSV export content-type and header, pipeline topics/layers, quality checks, `system.status` row counts cross-checked against exact warehouse totals, JSON `404` semantics, all nine SPA deep links and both hashed assets. Result at time of writing: **88 / 88 pass**.

---

## Known gaps

Documented honestly rather than stubbed out:

- **Spark job file** — `processor.py` implements the same logical plan in-process; a standalone `spark_job.py` is not part of this repository.
- **dbt** — no dbt project yet. Gold aggregates are built by `warehouse/stream_sink.py` and `analytics/*.py`. `/api/system/status` therefore reports dbt as `not_configured`.
- **Airflow DAG files** — `orchestration/registry.py` defines the 6-DAG catalogue, but `airflow/dags/*.py` are not generated yet.
- **Docker** — no `Dockerfile` / `docker-compose.yml`. The embedded Postgres path exists because no Docker daemon was reachable in the build environment.
- **Navbar filter lists** are hardcoded in `Filters.tsx` rather than fetched from `/api/system/filters` (values match the warehouse).
- **Bundle size** — a single ~682 kB JS chunk (≈190 kB gzip); manual chunking would improve first load.
- `api/main.py` still uses the deprecated `@app.on_event("startup")` hook instead of a lifespan handler.

---

## Author

**Divakar** — [github.com/Divakar-v-cse](https://github.com/Divakar-v-cse)
