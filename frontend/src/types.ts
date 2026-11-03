export interface Period {
  start: string;
  end: string;
  days: number;
}

export interface Kpis {
  total_revenue: number;
  revenue_change_pct: number | null;
  total_orders: number;
  orders_change_pct: number | null;
  average_order_value: number;
  aov_change_pct: number | null;
  total_customers: number;
  new_customers: number;
  total_products: number;
  order_completion_rate: number;
  payment_success_rate: number;
  return_rate: number;
  total_units: number;
  gross_profit: number;
  gross_margin_pct: number;
}

export interface TrendPoint {
  date: string;
  revenue: number;
  orders: number;
}

export interface StatusSlice {
  status: string;
  orders: number;
  revenue: number;
  share: number;
}

export interface CategorySlice {
  category: string;
  revenue: number;
  orders: number;
  units: number;
  share: number;
  avg_discount_pct: number;
}

export interface RegionSlice {
  region: string;
  revenue: number;
  orders: number;
  units: number;
  share: number;
}

export interface RecentOrder {
  order_id: string;
  order_ts: string;
  customer: string;
  country: string;
  region: string;
  status: string;
  total: number;
  items: number;
}

export interface OverviewResponse {
  period: Period;
  kpis: Kpis;
  revenue_trend: TrendPoint[];
  status_breakdown: StatusSlice[];
  top_categories: CategorySlice[];
  top_regions: RegionSlice[];
  recent_orders: RecentOrder[];
}

export interface SalesResponse {
  granularity: "day" | "week" | "month";
  series: { period: string; revenue: number; orders: number; units: number; discount: number }[];
  by_category: CategorySlice[];
  by_region: RegionSlice[];
  by_payment_method: { payment_method: string; revenue: number; orders: number; share: number }[];
  top_products: {
    product_id: string;
    product_name: string;
    category: string;
    revenue: number;
    units: number;
    orders: number;
  }[];
  growth: { current_revenue: number; previous_revenue: number; growth_pct: number | null };
  discount_impact: { band: string; revenue: number; orders: number; aov: number; share: number }[];
}

export interface CustomerResponse {
  new_vs_returning: { month: string; new_customers: number; returning_customers: number }[];
  rfm_segments: {
    segment: string;
    customers: number;
    revenue: number;
    share: number;
    avg_recency_days: number;
    avg_frequency: number;
    avg_monetary: number;
  }[];
  clv: { average_ltv: number; median_ltv: number; top_decile_ltv: number; customers: number };
  repeat_purchase_rate: number;
  avg_spend_per_customer: number;
  top_customers: {
    customer_id: string;
    full_name: string;
    country: string;
    orders: number;
    total_spend: number;
    last_order: string | null;
  }[];
}

export interface ProductResponse {
  best_sellers: {
    product_id: string;
    product_name: string;
    category: string;
    revenue: number;
    units: number;
    orders: number;
    return_rate: number;
  }[];
  low_performers: { product_id: string; product_name: string; category: string; revenue: number; units: number }[];
  by_category: CategorySlice[];
  return_rates: {
    product_id: string;
    product_name: string;
    category: string;
    units_sold: number;
    units_returned: number;
    return_rate: number;
  }[];
}

export interface OrderAnalyticsResponse {
  status_counts: { status: string; orders: number; revenue: number; share: number }[];
  daily_status: { date: string; completed: number; cancelled: number; returned: number; pending: number }[];
  avg_processing_hours: number;
  avg_delivery_days: number;
  on_time_rate: number;
  funnel: { stage: string; orders: number; conversion: number }[];
  payment_failures: { reason: string; count: number; share: number }[];
}

export interface RetentionResponse {
  cohorts: { cohort: string; size: number; periods: { month_offset: number; retained: number; retention: number }[] }[];
  retention_curve: { month_offset: number; retention: number }[];
  repeat_rate: number;
  churn_rate: number;
  avg_lifetime_days: number;
}

export interface ForecastResponse {
  /** Observed revenue only — `kind` is always "actual". */
  history: { date: string; revenue: number; orders?: number; kind?: string }[];
  /** Model output only — `kind` is always "forecast". */
  forecast: { date: string; revenue: number; lower: number; upper: number; kind?: string }[];
  model: {
    name: string;
    mape: number;
    trained_on_days: number;
    method: string;
    holdout_days?: number;
    daily_trend?: number;
  };
  summary: {
    horizon_days: number;
    forecast_revenue: number;
    expected_growth_pct: number;
    avg_daily_forecast?: number;
  };
  anomalies: {
    date: string;
    revenue: number;
    expected: number;
    deviation_pct: number;
    z_score: number;
    severity: string;
    direction: string;
    method: string;
  }[];
  disclaimer: string;
}

export interface PipelineRun {
  run_id: number;
  pipeline_name: string;
  run_type: string;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_seconds: number | null;
  records_in: number;
  records_out: number;
  records_rejected: number;
  error_message: string | null;
}

export interface PipelineStatusResponse {
  status: "healthy" | "degraded" | "stalled";
  checked_at: string;
  last_run: PipelineRun | null;
  runs: PipelineRun[];
  metrics: {
    events_processed: number;
    records_rejected: number;
    processing_latency_ms: number;
    consumer_lag: number;
    throughput_per_min: number;
    deduplicated: number;
    late_events: number;
  };
  topics: { topic: string; partitions: number; messages: number; lag: number; bytes?: number; role?: string }[];
  layers: {
    layer: string;
    records: number;
    size_mb: number;
    last_updated: string | null;
    location: string;
    file_count?: number;
    unit?: string;
  }[];
  orchestration: {
    dag_id: string;
    schedule: string;
    last_run: string | null;
    state: string;
    next_run: string | null;
    cron?: string;
    description?: string;
    tasks?: string[];
  }[];
  stream_health?: {
    consumer_group: string;
    total_lag: number;
    /** Present on some deployments; the API currently reports `last_run_age_hours`. */
    last_run_at?: string | null;
    last_run_age_hours?: number | null;
    status?: string;
  };
}

export interface QualityCheck {
  check_id: number;
  check_name: string;
  layer: string;
  table_name: string;
  severity: string;
  status: string;
  records_checked: number;
  records_failed: number;
  failure_rate: number;
  details: string;
  run_at: string;
}

export interface DataQualityResponse {
  score: number;
  summary: { total: number; passed: number; failed: number; critical_failed: number };
  by_layer: { layer: string; total: number; passed: number; failed: number; score: number }[];
  checks: QualityCheck[];
  trend: { run_at: string; score: number; failed: number }[];
  quarantine?: {
    rejected: number;
    source_orders: number;
    rejection_rate: number;
    reasons: { reason: string; records: number }[];
  };
  run_at?: string | null;
  note?: string;
}

export interface OrderRow {
  order_id: string;
  order_date: string;
  customer: string;
  country: string;
  region: string;
  status: string;
  payment_status: string;
  payment_method: string;
  items: number;
  total: number;
}

export interface OrdersResponse {
  items: OrderRow[];
  page: number;
  page_size: number;
  total: number;
  pages: number;
  summary?: { revenue: number; average_order_value: number };
  sort?: string;
}

export interface DailySalesRow {
  date: string;
  orders: number;
  completed_orders: number;
  cancelled_orders: number;
  returned_orders: number;
  units_sold: number;
  gross_revenue: number;
  discount_amount: number;
  shipping_revenue: number;
  net_revenue: number;
  active_customers: number;
  new_customers: number;
}

export interface DailySalesResponse {
  period: Period;
  granularity: string;
  rows: DailySalesRow[];
  totals: { orders: number; revenue: number; units: number };
  note: string;
  generated_at: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  database: { connected: boolean; engine: string; version: string };
  uptime_seconds: number;
  warehouse: { orders: number; customers: number; products: number; revenue: number };
  generated_at: string;
}

export interface SystemResponse {
  application: { name: string; version: string; environment: string; started_at: string; uptime_seconds: number };
  database: { url: string; connected: boolean; version: string; size_mb: number };
  services: { name: string; status: string; detail: string; mode: string }[];
  data_freshness: { dataset: string; latest: string | null; lag_minutes: number | null; status: string }[];
  row_counts: { table: string; rows: number }[];
}

export interface Filters {
  start_date: string;
  end_date: string;
  category: string;
  region: string;
}
