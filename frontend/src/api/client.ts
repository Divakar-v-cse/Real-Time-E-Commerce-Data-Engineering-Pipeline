import type {
  CustomerResponse,
  DailySalesResponse,
  DataQualityResponse,
  ForecastResponse,
  HealthResponse,
  OrderAnalyticsResponse,
  OrdersResponse,
  OverviewResponse,
  PipelineStatusResponse,
  ProductResponse,
  RetentionResponse,
  SalesResponse,
  SystemResponse,
} from "../types";

const BASE = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* keep status text */
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export type Query = Record<string, string | number | boolean | undefined | null>;

export function toQuery(params: Query = {}): string {
  const sp = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") sp.append(key, String(value));
  });
  const qs = sp.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  health: () => request<HealthResponse>("/health"),
  overview: (q: Query) => request<OverviewResponse>(`/api/dashboard/overview${toQuery(q)}`),
  sales: (q: Query) => request<SalesResponse>(`/api/analytics/sales${toQuery(q)}`),
  customers: (q: Query) => request<CustomerResponse>(`/api/analytics/customers${toQuery(q)}`),
  products: (q: Query) => request<ProductResponse>(`/api/analytics/products${toQuery(q)}`),
  orderAnalytics: (q: Query) => request<OrderAnalyticsResponse>(`/api/analytics/orders${toQuery(q)}`),
  retention: (q: Query) => request<RetentionResponse>(`/api/analytics/retention${toQuery(q)}`),
  forecast: (q: Query) => request<ForecastResponse>(`/api/analytics/forecast${toQuery(q)}`),
  pipelineStatus: () => request<PipelineStatusResponse>("/api/pipeline/status"),
  dataQuality: () => request<DataQualityResponse>("/api/data-quality"),
  orders: (q: Query) => request<OrdersResponse>(`/api/orders${toQuery(q)}`),
  dailySales: (q: Query) => request<DailySalesResponse>(`/api/reports/daily-sales${toQuery(q)}`),
  system: () => request<SystemResponse>("/api/system/status"),
  triggerPipeline: (body: { stages?: string[]; rebuild?: boolean } = {}) =>
    request<{ run_id?: number; status?: string; message?: string; stages?: string[] }>("/api/pipeline/trigger", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  generateEvents: (body: { count: number; rate_per_second: number; inject_issues: boolean }) =>
    request<{
      accepted: number;
      rejected: number;
      topics: Record<string, number>;
      lag: number;
      batch_id?: string;
      emitted?: number;
      rejected_samples?: { reason: string; payload?: unknown }[];
    }>("/api/events/generate", { method: "POST", body: JSON.stringify(body) }),
};
