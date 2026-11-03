import { useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useFilters } from "../context/Filters";
import { AsyncBody, EmptyState, KpiCard, Panel, SectionHeading } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateOnly, money, num, pct, shortDate, signedPct } from "../lib/format";
import type { CategorySlice, RegionSlice } from "../types";

type Granularity = "auto" | "day" | "week" | "month";

const GRANULARITIES: { value: Granularity; label: string }[] = [
  { value: "auto", label: "Auto" },
  { value: "day", label: "Daily" },
  { value: "week", label: "Weekly" },
  { value: "month", label: "Monthly" },
];

export default function Sales() {
  const { query, refreshToken } = useFilters();
  const [granularity, setGranularity] = useState<Granularity>("auto");
  const params = granularity === "auto" ? query : { ...query, granularity };
  const key = JSON.stringify(params) + refreshToken;
  const { data, loading, error, reload } = useApi(() => api.sales(params), key);

  const series = data?.series ?? [];

  const categoryColumns: Column<CategorySlice>[] = [
    { key: "category", header: "Category" },
    { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { compact: true }) },
    { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
    { key: "units", header: "Units", align: "right", render: (r) => num(r.units) },
    { key: "share", header: "Share", align: "right", render: (r) => pct(r.share) },
    { key: "avg_discount_pct", header: "Avg discount", align: "right", render: (r) => pct(r.avg_discount_pct) },
  ];

  const regionColumns: Column<RegionSlice>[] = [
    { key: "region", header: "Region" },
    { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { compact: true }) },
    { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
    { key: "units", header: "Units", align: "right", render: (r) => num(r.units) },
    { key: "share", header: "Share", align: "right", render: (r) => pct(r.share) },
  ];

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Sales performance"
        subtitle={
          data
            ? `${series.length} ${data.granularity} buckets · ${dateOnly(data.series[0]?.period)} → ${dateOnly(data.series[series.length - 1]?.period)}`
            : "Revenue, units and discount behaviour across the selected window"
        }
        right={
          <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
            {GRANULARITIES.map((g) => (
              <button
                key={g.value}
                type="button"
                onClick={() => setGranularity(g.value)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                  granularity === g.value ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-50"
                }`}
              >
                {g.label}
              </button>
            ))}
          </div>
        }
      />

      <AsyncBody loading={loading} error={error} onRetry={reload} skeletonRows={4}>
        <div className="grid gap-3 sm:grid-cols-3">
          <KpiCard
            label="Revenue in scope"
            value={money(data?.growth.current_revenue, { compact: true })}
            delta={data?.growth.growth_pct}
            deltaLabel={`vs ${money(data?.growth.previous_revenue, { compact: true })} previous`}
          />
          <KpiCard
            label="Units sold"
            value={num(series.reduce((acc, row) => acc + row.units, 0))}
            hint={`${num(series.reduce((acc, row) => acc + row.orders, 0))} orders`}
            tone="sky"
          />
          <KpiCard
            label="Discount given"
            value={money(series.reduce((acc, row) => acc + row.discount, 0), { compact: true })}
            hint="sum of order-level discounts"
            tone="amber"
          />
        </div>

        <Panel
          className="mt-3"
          title="Revenue over time"
          subtitle="Area = net revenue, line series derived from the same buckets"
          actions={data ? <span className="text-[11px] text-slate-500">{signedPct(data.growth.growth_pct)} vs previous period</span> : null}
        >
          {series.length === 0 ? (
            <EmptyState title="No sales in this window" />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={series} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="salesRev" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#4f46e5" stopOpacity={0.3} />
                      <stop offset="100%" stopColor="#4f46e5" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                  <XAxis
                    dataKey="period"
                    tickFormatter={(value) => shortDate(String(value))}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={26}
                  />
                  <YAxis
                    tickFormatter={(value) => money(Number(value), { compact: true })}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    width={58}
                  />
                  <Tooltip
                    formatter={(value, name) => [
                      name === "revenue" ? money(Number(value)) : num(Number(value)),
                      name === "revenue" ? "Revenue" : "Orders",
                    ]}
                    labelFormatter={(label) => dateOnly(String(label))}
                  />
                  <Area type="monotone" dataKey="revenue" stroke="#4f46e5" strokeWidth={2} fill="url(#salesRev)" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Units and orders per bucket" subtitle="Volume view of the same window">
            {series.length === 0 ? (
              <EmptyState title="Nothing to plot" />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={series} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                    <XAxis
                      dataKey="period"
                      tickFormatter={(value) => shortDate(String(value))}
                      tick={{ fontSize: 11, fill: "#64748b" }}
                      tickLine={false}
                      axisLine={false}
                      minTickGap={22}
                    />
                    <YAxis tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} width={48} />
                    <Tooltip labelFormatter={(label) => dateOnly(String(label))} formatter={(value) => num(Number(value))} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Bar dataKey="orders" name="Orders" fill="#0ea5e9" radius={[3, 3, 0, 0]} />
                    <Bar dataKey="units" name="Units" fill="#c7d2fe" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Discount impact" subtitle="Revenue by discount band — margin leakage check">
            <DataTable
              dense
              columns={[
                { key: "band", header: "Discount band" },
                { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
                { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { compact: true }) },
                { key: "aov", header: "AOV", align: "right", render: (r) => money(r.aov, { decimals: 2 }) },
                { key: "share", header: "Share", align: "right", render: (r) => pct(r.share) },
              ]}
              rows={data?.discount_impact ?? []}
              rowKey={(r) => r.band}
            />
          </Panel>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Revenue by category" bodyClassName="p-0">
            <DataTable columns={categoryColumns} rows={data?.by_category ?? []} rowKey={(r) => r.category} dense />
          </Panel>
          <Panel title="Revenue by region" bodyClassName="p-0">
            <DataTable columns={regionColumns} rows={data?.by_region ?? []} rowKey={(r) => r.region} dense />
          </Panel>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Payment methods" subtitle="Captured revenue split by payment method">
            <DataTable
              dense
              columns={[
                { key: "payment_method", header: "Method" },
                { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
                { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { compact: true }) },
                { key: "share", header: "Share", align: "right", render: (r) => pct(r.share) },
              ]}
              rows={data?.by_payment_method ?? []}
              rowKey={(r) => r.payment_method}
            />
          </Panel>

          <Panel title="Top products" subtitle="Best sellers inside the current filter" bodyClassName="p-0">
            <DataTable
              dense
              maxHeight="320px"
              columns={[
                { key: "product_name", header: "Product", render: (r) => <span className="block max-w-[220px] truncate">{r.product_name}</span> },
                { key: "category", header: "Category", render: (r) => <span className="text-xs text-slate-500">{r.category}</span> },
                { key: "units", header: "Units", align: "right", render: (r) => num(r.units) },
                { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { compact: true }) },
              ]}
              rows={data?.top_products ?? []}
              rowKey={(r) => r.product_id}
            />
          </Panel>
        </div>
      </AsyncBody>
    </div>
  );
}
