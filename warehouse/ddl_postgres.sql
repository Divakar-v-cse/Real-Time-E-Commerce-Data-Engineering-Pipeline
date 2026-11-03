-- =====================================================================
-- Divakar Data Analytics E-Commerce Project
-- PostgreSQL warehouse DDL - star schema + operational metadata
-- ---------------------------------------------------------------------
-- Schemas
--   staging    : landing zone (1:1 with source extracts, all TEXT-ish)
--   warehouse  : conformed dimensions + fact tables (Kimball star schema)
--   analytics  : dbt-built marts consumed by the FastAPI service
--   ops        : pipeline runs, metrics and data-quality results
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS warehouse;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS ops;

-- ---------------------------------------------------------------------
-- STAGING (raw landing)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS staging.raw_orders CASCADE;
CREATE TABLE staging.raw_orders (
    row_id           BIGSERIAL PRIMARY KEY,
    order_id         TEXT,
    customer_id      TEXT,
    order_ts         TEXT,
    status           TEXT,
    channel          TEXT,
    currency         TEXT,
    country          TEXT,
    region           TEXT,
    city             TEXT,
    subtotal         TEXT,
    discount_total   TEXT,
    shipping_total   TEXT,
    order_total      TEXT,
    item_count       TEXT,
    payment_method   TEXT,
    payment_status   TEXT,
    _ingested_at     TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS staging.raw_order_items CASCADE;
CREATE TABLE staging.raw_order_items (
    row_id          BIGSERIAL PRIMARY KEY,
    order_item_id   TEXT,
    order_id        TEXT,
    product_id      TEXT,
    quantity        TEXT,
    unit_price      TEXT,
    discount_pct    TEXT,
    line_total      TEXT,
    unit_cost       TEXT,
    _ingested_at    TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS staging.raw_customers CASCADE;
CREATE TABLE staging.raw_customers (
    row_id                BIGSERIAL PRIMARY KEY,
    customer_id           TEXT,
    email                 TEXT,
    full_name             TEXT,
    country               TEXT,
    city                  TEXT,
    region                TEXT,
    segment               TEXT,
    acquisition_channel   TEXT,
    signup_date           TEXT,
    date_of_birth_year    TEXT,
    _ingested_at          TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS staging.raw_products CASCADE;
CREATE TABLE staging.raw_products (
    row_id        BIGSERIAL PRIMARY KEY,
    product_id    TEXT,
    sku           TEXT,
    product_name  TEXT,
    category      TEXT,
    subcategory   TEXT,
    brand         TEXT,
    unit_price    TEXT,
    unit_cost     TEXT,
    weight_kg     TEXT,
    is_active     TEXT,
    launched_at   TEXT,
    _ingested_at  TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS staging.raw_payments CASCADE;
CREATE TABLE staging.raw_payments (
    row_id           BIGSERIAL PRIMARY KEY,
    payment_id       TEXT,
    order_id         TEXT,
    payment_method   TEXT,
    payment_status   TEXT,
    amount           TEXT,
    currency         TEXT,
    paid_at          TEXT,
    failure_reason   TEXT,
    gateway          TEXT,
    _ingested_at     TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS staging.raw_shipments CASCADE;
CREATE TABLE staging.raw_shipments (
    row_id           BIGSERIAL PRIMARY KEY,
    shipment_id      TEXT,
    order_id         TEXT,
    carrier          TEXT,
    tracking_number  TEXT,
    shipment_status  TEXT,
    shipped_at       TEXT,
    delivered_at     TEXT,
    transit_days     TEXT,
    shipping_cost    TEXT,
    _ingested_at     TIMESTAMPTZ DEFAULT now()
);

DROP TABLE IF EXISTS staging.raw_returns CASCADE;
CREATE TABLE staging.raw_returns (
    row_id                          BIGSERIAL PRIMARY KEY,
    return_id                       TEXT,
    order_id                        TEXT,
    return_ts                       TEXT,
    reason                          TEXT,
    refund_amount                   TEXT,
    refund_status                   TEXT,
    category_return_rate_baseline   TEXT,
    _ingested_at                    TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------
-- DIMENSIONS
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS warehouse.dim_date CASCADE;
CREATE TABLE warehouse.dim_date (
    date_key      INTEGER PRIMARY KEY,          -- yyyymmdd
    date_actual   DATE NOT NULL UNIQUE,
    year          INTEGER NOT NULL,
    quarter       INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    month_name    TEXT NOT NULL,
    year_month    TEXT NOT NULL,
    week_of_year  INTEGER NOT NULL,
    day_of_week   INTEGER NOT NULL,             -- 0 = Monday
    day_name      TEXT NOT NULL,
    is_weekend    BOOLEAN NOT NULL,
    is_holiday    BOOLEAN NOT NULL DEFAULT FALSE
);

-- SCD Type 2: tracked attributes are region/segment/channel/city.
DROP TABLE IF EXISTS warehouse.dim_customer CASCADE;
CREATE TABLE warehouse.dim_customer (
    customer_sk         BIGSERIAL PRIMARY KEY,
    customer_id         TEXT NOT NULL,
    email               TEXT,
    full_name           TEXT,
    country             TEXT,
    city                TEXT,
    region              TEXT,
    segment             TEXT,
    acquisition_channel TEXT,
    signup_date         DATE,
    birth_year          INTEGER,
    valid_from          TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to            TIMESTAMPTZ,
    is_current          BOOLEAN NOT NULL DEFAULT TRUE,
    row_hash            TEXT NOT NULL,
    CONSTRAINT uq_dim_customer_version UNIQUE (customer_id, valid_from)
);
CREATE INDEX idx_dim_customer_current ON warehouse.dim_customer (customer_id) WHERE is_current;

DROP TABLE IF EXISTS warehouse.dim_product CASCADE;
CREATE TABLE warehouse.dim_product (
    product_sk    BIGSERIAL PRIMARY KEY,
    product_id    TEXT NOT NULL UNIQUE,
    sku           TEXT,
    product_name  TEXT,
    category      TEXT,
    subcategory   TEXT,
    brand         TEXT,
    unit_price    NUMERIC(12, 2),
    unit_cost     NUMERIC(12, 2),
    is_active     BOOLEAN,
    launched_at   DATE
);
CREATE INDEX idx_dim_product_category ON warehouse.dim_product (category);

DROP TABLE IF EXISTS warehouse.dim_payment_method CASCADE;
CREATE TABLE warehouse.dim_payment_method (
    payment_method_sk BIGSERIAL PRIMARY KEY,
    method_name       TEXT NOT NULL UNIQUE,
    display_name      TEXT NOT NULL,
    method_group      TEXT NOT NULL,
    is_online         BOOLEAN NOT NULL
);

-- ---------------------------------------------------------------------
-- FACTS
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS warehouse.fact_orders CASCADE;
CREATE TABLE warehouse.fact_orders (
    order_sk          BIGSERIAL PRIMARY KEY,
    order_id          TEXT NOT NULL UNIQUE,
    customer_sk       BIGINT REFERENCES warehouse.dim_customer (customer_sk),
    date_key          INTEGER NOT NULL REFERENCES warehouse.dim_date (date_key),
    payment_method_sk BIGINT REFERENCES warehouse.dim_payment_method (payment_method_sk),
    status            TEXT NOT NULL,
    channel           TEXT,
    currency          TEXT,
    country           TEXT,
    region            TEXT,
    item_count        INTEGER NOT NULL DEFAULT 0,
    subtotal          NUMERIC(14, 2) NOT NULL DEFAULT 0,
    discount_total    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    shipping_total    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    order_total       NUMERIC(14, 2) NOT NULL DEFAULT 0,
    is_completed      BOOLEAN NOT NULL DEFAULT FALSE,
    is_cancelled      BOOLEAN NOT NULL DEFAULT FALSE,
    is_returned       BOOLEAN NOT NULL DEFAULT FALSE,
    order_ts          TIMESTAMPTZ NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_fact_orders_date ON warehouse.fact_orders (date_key);
CREATE INDEX idx_fact_orders_ts ON warehouse.fact_orders (order_ts);
CREATE INDEX idx_fact_orders_customer ON warehouse.fact_orders (customer_sk);
CREATE INDEX idx_fact_orders_status ON warehouse.fact_orders (status);
CREATE INDEX idx_fact_orders_region ON warehouse.fact_orders (region);

DROP TABLE IF EXISTS warehouse.fact_order_items CASCADE;
CREATE TABLE warehouse.fact_order_items (
    order_item_sk BIGSERIAL PRIMARY KEY,
    order_item_id TEXT NOT NULL UNIQUE,
    order_id      TEXT NOT NULL REFERENCES warehouse.fact_orders (order_id) ON DELETE CASCADE,
    product_sk    BIGINT REFERENCES warehouse.dim_product (product_sk),
    quantity      INTEGER NOT NULL,
    unit_price    NUMERIC(12, 2) NOT NULL,
    discount_pct  NUMERIC(5, 4) NOT NULL DEFAULT 0,
    line_total    NUMERIC(14, 2) NOT NULL,
    unit_cost     NUMERIC(12, 2),
    gross_profit  NUMERIC(14, 2)
);
CREATE INDEX idx_fact_items_order ON warehouse.fact_order_items (order_id);
CREATE INDEX idx_fact_items_product ON warehouse.fact_order_items (product_sk);

DROP TABLE IF EXISTS warehouse.fact_payments CASCADE;
CREATE TABLE warehouse.fact_payments (
    payment_sk        BIGSERIAL PRIMARY KEY,
    payment_id        TEXT NOT NULL UNIQUE,
    order_id          TEXT NOT NULL REFERENCES warehouse.fact_orders (order_id) ON DELETE CASCADE,
    payment_method_sk BIGINT REFERENCES warehouse.dim_payment_method (payment_method_sk),
    status            TEXT,
    amount            NUMERIC(14, 2),
    currency          TEXT,
    failure_reason    TEXT,
    gateway           TEXT,
    paid_at           TIMESTAMPTZ
);
CREATE INDEX idx_fact_payments_status ON warehouse.fact_payments (status);
CREATE INDEX idx_fact_payments_order ON warehouse.fact_payments (order_id);

DROP TABLE IF EXISTS warehouse.fact_shipments CASCADE;
CREATE TABLE warehouse.fact_shipments (
    shipment_sk      BIGSERIAL PRIMARY KEY,
    shipment_id      TEXT NOT NULL UNIQUE,
    order_id         TEXT NOT NULL REFERENCES warehouse.fact_orders (order_id) ON DELETE CASCADE,
    carrier          TEXT,
    status           TEXT,
    shipped_at       TIMESTAMPTZ,
    delivered_at     TIMESTAMPTZ,
    transit_days     INTEGER,
    shipping_cost    NUMERIC(10, 2),
    processing_hours NUMERIC(10, 2)
);
CREATE INDEX idx_fact_shipments_order ON warehouse.fact_shipments (order_id);

DROP TABLE IF EXISTS warehouse.fact_returns CASCADE;
CREATE TABLE warehouse.fact_returns (
    return_sk     BIGSERIAL PRIMARY KEY,
    return_id     TEXT NOT NULL UNIQUE,
    order_id      TEXT NOT NULL REFERENCES warehouse.fact_orders (order_id) ON DELETE CASCADE,
    reason        TEXT,
    refund_amount NUMERIC(14, 2),
    refund_status TEXT,
    return_ts     TIMESTAMPTZ
);
CREATE INDEX idx_fact_returns_order ON warehouse.fact_returns (order_id);

-- ---------------------------------------------------------------------
-- OPS (monitoring)
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS ops.pipeline_runs CASCADE;
CREATE TABLE ops.pipeline_runs (
    run_id            BIGSERIAL PRIMARY KEY,
    pipeline_name     TEXT NOT NULL,
    run_type          TEXT NOT NULL,            -- batch | micro_batch | streaming
    status            TEXT NOT NULL,            -- running | success | failed
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at       TIMESTAMPTZ,
    duration_seconds  NUMERIC(12, 2),
    records_in        BIGINT DEFAULT 0,
    records_out       BIGINT DEFAULT 0,
    records_rejected  BIGINT DEFAULT 0,
    error_message     TEXT,
    details           JSONB
);
CREATE INDEX idx_pipeline_runs_name ON ops.pipeline_runs (pipeline_name, started_at DESC);

DROP TABLE IF EXISTS ops.pipeline_metrics CASCADE;
CREATE TABLE ops.pipeline_metrics (
    metric_id   BIGSERIAL PRIMARY KEY,
    metric_name TEXT NOT NULL,
    metric_value NUMERIC(18, 4) NOT NULL,
    unit        TEXT,
    labels      JSONB,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_metrics_name_time ON ops.pipeline_metrics (metric_name, recorded_at DESC);

DROP TABLE IF EXISTS ops.data_quality_results CASCADE;
CREATE TABLE ops.data_quality_results (
    check_id         BIGSERIAL PRIMARY KEY,
    check_name       TEXT NOT NULL,
    layer            TEXT NOT NULL,             -- bronze | silver | gold | warehouse
    table_name       TEXT NOT NULL,
    severity         TEXT NOT NULL,             -- critical | warning
    status           TEXT NOT NULL,             -- passed | failed
    records_checked  BIGINT DEFAULT 0,
    records_failed   BIGINT DEFAULT 0,
    failure_rate     NUMERIC(8, 4) DEFAULT 0,
    details          TEXT,
    run_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_dq_run ON ops.data_quality_results (run_at DESC);

-- ---------------------------------------------------------------------
-- Reject ledger: every source record that failed a business rule is kept
-- here with its reason and payload, so nothing is silently dropped and the
-- warehouse only ever holds records that pass validation.
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS ops.rejected_records CASCADE;
CREATE TABLE ops.rejected_records (
    reject_id     BIGSERIAL PRIMARY KEY,
    source_table  TEXT NOT NULL,
    business_key  TEXT,
    reason        TEXT NOT NULL,
    payload       JSONB,
    run_id        BIGINT,
    rejected_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_rejected_reason ON ops.rejected_records (reason, rejected_at DESC);

-- ---------------------------------------------------------------------
-- Dimension seed data
-- ---------------------------------------------------------------------
INSERT INTO warehouse.dim_date
    (date_key, date_actual, year, quarter, month, month_name, year_month,
     week_of_year, day_of_week, day_name, is_weekend, is_holiday)
SELECT
    TO_CHAR(d, 'YYYYMMDD')::INT,
    d,
    EXTRACT(YEAR FROM d)::INT,
    EXTRACT(QUARTER FROM d)::INT,
    EXTRACT(MONTH FROM d)::INT,
    TO_CHAR(d, 'FMMonth'),
    TO_CHAR(d, 'YYYY-MM'),
    EXTRACT(WEEK FROM d)::INT,
    EXTRACT(ISODOW FROM d)::INT - 1,
    TO_CHAR(d, 'FMDay'),
    EXTRACT(ISODOW FROM d) IN (6, 7),
    TO_CHAR(d, 'MM-DD') IN ('01-01', '12-25', '11-28', '07-04')
FROM generate_series('2024-01-01'::DATE, '2027-12-31'::DATE, '1 day'::INTERVAL) AS d
ON CONFLICT (date_key) DO NOTHING;

INSERT INTO warehouse.dim_payment_method (method_name, display_name, method_group, is_online) VALUES
    ('credit_card', 'Credit Card', 'Card', TRUE),
    ('debit_card',  'Debit Card',  'Card', TRUE),
    ('paypal',      'PayPal',      'Digital Wallet', TRUE),
    ('upi',         'UPI',         'Bank Transfer', TRUE),
    ('wallet',      'Store Wallet','Digital Wallet', TRUE),
    ('cash_on_delivery', 'Cash on Delivery', 'Offline', FALSE)
ON CONFLICT (method_name) DO NOTHING;
