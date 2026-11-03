import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useFilters } from "../context/Filters";
import { AsyncBody, EmptyState, KpiCard, Panel, SectionHeading, StatusBadge } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateOnly, hours, money, num, pct } from "../lib/format";
import type { OrderRow } from "../types";

const STATUSES = ["All", "Delivered", "Shipped", "Processing", "Pending", "Cancelled", "Returned"];

const SORTS: { value: string; label: string }[] = [
  { value: "recent", label: "Newest first" },
  { value: "oldest", label: "Oldest first" },
  { value: "amount_desc", label: "Highest value" },
  { value: "amount_asc", label: "Lowest value" },
];

export default function Orders() {
  const { query, refreshToken } = useFilters();
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");
  const [status, setStatus] = useState("All");
  const [sort, setSort] = useState("recent");
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(25);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebounced(search.trim());
      setPage(1);
    }, 350);
    return () => window.clearTimeout(timer);
  }, [search]);

  const params = {
    ...query,
    page,
    size,
    sort,
    ...(debounced ? { search: debounced } : {}),
    ...(status !== "All" ? { status: status.toLowerCase() } : {}),
  };
  const key = JSON.stringify(params) + refreshToken;
  const { data, loading, error, reload } = useApi(() => api.orders(params), key);
  const analytics = useApi(() => api.orderAnalytics(query), JSON.stringify(query) + refreshToken);

  const columns: Column<OrderRow>[] = [
    { key: "order_id", header: "Order", render: (r) => <span className="font-mono text-xs text-slate-700">{r.order_id}</span> },
    { key: "order_date", header: "Placed", render: (r) => dateOnly(r.order_date) },
    { key: "customer", header: "Customer", render: (r) => <span className="block max-w-[180px] truncate">{r.customer || "Guest"}</span> },
    { key: "country", header: "Country" },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "payment_status", header: "Payment", render: (r) => <StatusBadge status={r.payment_status} /> },
    { key: "payment_method", header: "Method", render: (r) => <span className="text-xs text-slate-500">{r.payment_method}</span> },
    { key: "items", header: "Items", align: "right", render: (r) => num(r.items) },
    { key: "total", header: "Total", align: "right", render: (r) => <span className="font-medium text-slate-900">{money(r.total, { decimals: 2 })}</span> },
  ];

  const a = analytics.data;
  const totalPages = data?.pages ?? 0;

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Order management"
        subtitle="Row-level order browser backed by the warehouse fact tables, plus fulfilment diagnostics"
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard
          label="Orders in scope"
          value={num(data?.total)}
          hint={data ? `page ${data.page} of ${Math.max(1, data.pages)}` : undefined}
        />
        <KpiCard label="Revenue in scope" value={money(data?.summary?.revenue, { compact: true })} tone="sky" />
        <KpiCard label="Average order value" value={money(data?.summary?.average_order_value, { decimals: 2 })} tone="emerald" />
        <KpiCard
          label="On-time delivery"
          value={pct(a?.on_time_rate)}
          hint={a ? `${num(a.avg_delivery_days, 1)} d avg delivery` : undefined}
          tone="amber"
        />
      </div>

      <Panel
        title="Orders"
        subtitle="Search matches order id, customer, country and payment method"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                className="select w-48 pl-7"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search orders…"
                aria-label="Search orders"
              />
            </div>
            <select
              className="select"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(1);
              }}
              aria-label="Status filter"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s === "All" ? "All statuses" : s}
                </option>
              ))}
            </select>
            <select
              className="select"
              value={sort}
              onChange={(e) => {
                setSort(e.target.value);
                setPage(1);
              }}
              aria-label="Sort order"
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
            <select
              className="select"
              value={size}
              onChange={(e) => {
                setSize(Number(e.target.value));
                setPage(1);
              }}
              aria-label="Rows per page"
            >
              {[10, 25, 50, 100].map((n) => (
                <option key={n} value={n}>
                  {n} / page
                </option>
              ))}
            </select>
          </div>
        }
        bodyClassName="p-0"
      >
        <AsyncBody loading={loading} error={error} onRetry={reload} isEmpty={(data?.items ?? []).length === 0} skeletonRows={5}>
          <DataTable columns={columns} rows={data?.items ?? []} rowKey={(r) => r.order_id} dense maxHeight="520px" />
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-4 py-3 text-xs text-slate-500">
            <span>
              {data ? `Showing ${(data.page - 1) * data.page_size + 1}–${Math.min(data.page * data.page_size, data.total)} of ${num(data.total)}` : "—"}
            </span>
            <div className="flex items-center gap-2">
              <button type="button" className="btn" disabled={!data || data.page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                <ChevronLeft size={14} /> Prev
              </button>
              <span className="tabular-nums">
                {data?.page ?? 1} / {Math.max(1, totalPages)}
              </span>
              <button
                type="button"
                className="btn"
                disabled={!data || data.page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </AsyncBody>
      </Panel>

      <AsyncBody loading={analytics.loading} error={analytics.error} onRetry={analytics.reload} skeletonRows={3}>
        <div className="grid gap-3 xl:grid-cols-2">
          <Panel title="Fulfilment funnel" subtitle="How orders progress towards delivery">
            {(a?.funnel ?? []).length === 0 ? (
              <EmptyState title="No funnel data" />
            ) : (
              <ul className="space-y-3">
                {(a?.funnel ?? []).map((stage) => (
                  <li key={stage.stage}>
                    <div className="flex items-baseline justify-between text-xs">
                      <span className="capitalize text-slate-700">{stage.stage}</span>
                      <span className="text-slate-500">
                        {num(stage.orders)} · {pct(stage.conversion)}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(100, stage.conversion)}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel title="Status breakdown" subtitle="Order counts and revenue by final status" bodyClassName="p-0">
            <DataTable
              dense
              columns={[
                { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
                { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
                { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { compact: true }) },
                { key: "share", header: "Share", align: "right", render: (r) => pct(r.share) },
              ]}
              rows={a?.status_counts ?? []}
              rowKey={(r) => r.status}
            />
          </Panel>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Payment failure reasons" subtitle="Declined or failed attempts, with share of failures">
            <DataTable
              dense
              columns={[
                { key: "reason", header: "Reason", render: (r) => r.reason || <span className="text-slate-400">unspecified</span> },
                { key: "count", header: "Count", align: "right", render: (r) => num(r.count) },
                { key: "share", header: "Share", align: "right", render: (r) => pct(r.share) },
              ]}
              rows={a?.payment_failures ?? []}
              rowKey={(r, i) => `${r.reason || "unspecified"}-${i}`}
            />
          </Panel>

          <Panel title="Operational timing" subtitle="Averages derived from shipment and order timestamps">
            <dl className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Avg processing</dt>
                <dd className="mt-1 text-lg font-semibold text-slate-900">{hours(a?.avg_processing_hours)}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Avg delivery</dt>
                <dd className="mt-1 text-lg font-semibold text-slate-900">{num(a?.avg_delivery_days, 1)} d</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">On-time rate</dt>
                <dd className="mt-1 text-lg font-semibold text-slate-900">{pct(a?.on_time_rate)}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Statuses tracked</dt>
                <dd className="mt-1 text-lg font-semibold text-slate-900">{num(a?.status_counts.length)}</dd>
              </div>
            </dl>
          </Panel>
        </div>
      </AsyncBody>
    </div>
  );
}
