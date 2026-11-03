import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useFilters } from "../context/Filters";
import { AsyncBody, EmptyState, KpiCard, Panel, SectionHeading, StatusBadge } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateOnly, money, num, pct } from "../lib/format";
import type { CustomerResponse } from "../types";

type Rfm = CustomerResponse["rfm_segments"][number];
type TopCustomer = CustomerResponse["top_customers"][number];

export default function Customers() {
  const { query, refreshToken } = useFilters();
  const key = JSON.stringify(query) + refreshToken;
  const customers = useApi(() => api.customers(query), key);
  const retention = useApi(() => api.retention(query), key);

  const data = customers.data;
  const clv = data?.clv;

  const rfmColumns: Column<Rfm>[] = [
    { key: "segment", header: "Segment", render: (r) => <StatusBadge status={r.segment} /> },
    { key: "customers", header: "Customers", align: "right", render: (r) => num(r.customers) },
    { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { compact: true }) },
    { key: "share", header: "Share", align: "right", render: (r) => pct(r.share) },
    { key: "avg_recency_days", header: "Avg recency", align: "right", render: (r) => `${num(r.avg_recency_days, 1)} d` },
    { key: "avg_frequency", header: "Avg orders", align: "right", render: (r) => num(r.avg_frequency, 1) },
    { key: "avg_monetary", header: "Avg spend", align: "right", render: (r) => money(r.avg_monetary, { decimals: 2 }) },
  ];

  const topColumns: Column<TopCustomer>[] = [
    { key: "full_name", header: "Customer", render: (r) => <span className="block max-w-[200px] truncate">{r.full_name}</span> },
    { key: "country", header: "Country" },
    { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
    { key: "total_spend", header: "Lifetime spend", align: "right", render: (r) => money(r.total_spend, { decimals: 2 }) },
    { key: "last_order", header: "Last order", align: "right", render: (r) => dateOnly(r.last_order) },
  ];

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Customer analytics"
        subtitle="Acquisition mix, RFM segmentation, lifetime value and cohort retention"
      />

      <AsyncBody loading={customers.loading} error={customers.error} onRetry={customers.reload} skeletonRows={4}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Average LTV" value={money(clv?.average_ltv, { decimals: 2 })} hint={`${num(clv?.customers)} customers scored`} />
          <KpiCard label="Median LTV" value={money(clv?.median_ltv, { decimals: 2 })} tone="sky" />
          <KpiCard label="Top-decile LTV" value={money(clv?.top_decile_ltv, { decimals: 2 })} tone="emerald" />
          <KpiCard
            label="Repeat purchase rate"
            value={pct(data?.repeat_purchase_rate)}
            hint={`${money(data?.avg_spend_per_customer, { decimals: 2 })} avg spend`}
            tone="amber"
          />
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="New vs returning" subtitle="Monthly acquisition split inside the window">
            {(data?.new_vs_returning ?? []).length === 0 ? (
              <EmptyState title="No customer activity" />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={data?.new_vs_returning} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                    <XAxis dataKey="month" tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} width={46} />
                    <Tooltip formatter={(value) => num(Number(value))} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="new_customers" name="New" stackId="a" fill="#4f46e5" radius={[0, 0, 0, 0]} />
                    <Bar dataKey="returning_customers" name="Returning" stackId="a" fill="#a5b4fc" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Retention curve" subtitle="Share of each cohort still ordering, by month offset">
            {retention.loading ? (
              <p className="py-10 text-center text-xs text-slate-500">Loading retention…</p>
            ) : (retention.data?.retention_curve ?? []).length === 0 ? (
              <EmptyState title="No repeat activity in this window" message="Retention needs at least two purchase months." />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={retention.data?.retention_curve} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                    <XAxis
                      dataKey="month_offset"
                      tickFormatter={(value) => `M${Number(value)}`}
                      tick={{ fontSize: 11, fill: "#64748b" }}
                      tickLine={false}
                      axisLine={false}
                    />
                    <YAxis
                      tickFormatter={(value) => pct(Number(value), 0)}
                      tick={{ fontSize: 11, fill: "#64748b" }}
                      tickLine={false}
                      axisLine={false}
                      width={46}
                    />
                    <Tooltip
                      formatter={(value) => pct(Number(value))}
                      labelFormatter={(label) => `Month offset ${Number(label)}`}
                    />
                    <Line type="monotone" dataKey="retention" stroke="#0ea5e9" strokeWidth={2} dot={{ r: 2 }} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            <div className="mt-2 flex flex-wrap gap-4 text-[11px] text-slate-500">
              <span>Repeat rate {pct(retention.data?.repeat_rate)}</span>
              <span>Churn {pct(retention.data?.churn_rate)}</span>
              <span>Avg lifetime {num(retention.data?.avg_lifetime_days, 1)} days</span>
            </div>
          </Panel>
        </div>

        <Panel className="mt-3" title="RFM segments" subtitle="Recency, frequency and monetary scoring over the selected window" bodyClassName="p-0">
          {data?.rfm_segments.length === 0 ? (
            <EmptyState title="No scored customers" />
          ) : (
            <DataTable columns={rfmColumns} rows={data?.rfm_segments ?? []} rowKey={(r) => r.segment} dense />
          )}
        </Panel>

        <Panel className="mt-3" title="Highest-value customers" subtitle="Ranked by lifetime spend inside the filter" bodyClassName="p-0">
          {data?.top_customers.length === 0 ? (
            <EmptyState title="No customers in scope" />
          ) : (
            <DataTable columns={topColumns} rows={data?.top_customers ?? []} rowKey={(r) => r.customer_id} dense maxHeight="360px" />
          )}
        </Panel>
      </AsyncBody>
    </div>
  );
}
