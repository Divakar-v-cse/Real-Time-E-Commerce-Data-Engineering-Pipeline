import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CreditCard, DollarSign, PackageCheck, ShoppingBag, TrendingUp, Users } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useFilters } from "../context/Filters";
import { AsyncBody, KpiCard, Panel, SectionHeading, StatusBadge } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateOnly, money, num, pct, shortDate, signedPct } from "../lib/format";
import type { RecentOrder } from "../types";

const PIE_COLORS = ["#10b981", "#f59e0b", "#ef4444", "#0ea5e9", "#8b5cf6", "#64748b"];

export default function Overview() {
  const { query, refreshToken } = useFilters();
  const key = JSON.stringify(query) + refreshToken;
  const { data, loading, error, reload } = useApi(() => api.overview(query), key);

  const k = data?.kpis;
  const trend = data?.revenue_trend ?? [];

  const orderColumns: Column<RecentOrder>[] = [
    { key: "order_id", header: "Order", render: (r) => <span className="font-mono text-xs text-slate-700">{r.order_id}</span> },
    { key: "order_ts", header: "Placed", render: (r) => dateOnly(r.order_ts) },
    { key: "customer", header: "Customer", render: (r) => <span className="block max-w-[180px] truncate">{r.customer || "Guest"}</span> },
    { key: "country", header: "Country" },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "items", header: "Items", align: "right" },
    { key: "total", header: "Total", align: "right", render: (r) => <span className="font-medium text-slate-900">{money(r.total, { decimals: 2 })}</span> },
  ];

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Executive dashboard"
        subtitle={
          data
            ? `${dateOnly(data.period.start)} → ${dateOnly(data.period.end)} · ${data.period.days} days · ${num(k?.total_orders ?? 0)} orders in scope`
            : "Revenue, orders and customer health for the selected window"
        }
      />

      <AsyncBody loading={loading} error={error} onRetry={reload} skeletonRows={2}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Net revenue"
            value={money(k?.total_revenue, { compact: true })}
            delta={k?.revenue_change_pct}
            deltaLabel="vs previous period"
            icon={DollarSign}
          />
          <KpiCard
            label="Orders"
            value={num(k?.total_orders)}
            delta={k?.orders_change_pct}
            deltaLabel="vs previous period"
            icon={ShoppingBag}
            tone="sky"
          />
          <KpiCard
            label="Average order value"
            value={money(k?.average_order_value, { decimals: 2 })}
            delta={k?.aov_change_pct}
            deltaLabel="vs previous period"
            icon={TrendingUp}
            tone="emerald"
          />
          <KpiCard
            label="Active customers"
            value={num(k?.total_customers)}
            hint={`${num(k?.new_customers)} new in period`}
            icon={Users}
            tone="amber"
          />
        </div>

        <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Completion rate" value={pct(k?.order_completion_rate)} hint="delivered + shipped + completed" icon={PackageCheck} tone="emerald" />
          <KpiCard label="Payment success" value={pct(k?.payment_success_rate)} hint="captured / attempted" icon={CreditCard} tone="sky" />
          <KpiCard label="Return rate" value={pct(k?.return_rate)} hint="returned vs completed" tone="rose" />
          <KpiCard
            label="Gross margin"
            value={pct(k?.gross_margin_pct)}
            hint={`${money(k?.gross_profit, { compact: true })} profit · ${num(k?.total_units)} units`}
            tone="brand"
          />
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-3">
          <Panel
            className="xl:col-span-2"
            title="Revenue trend"
            subtitle="Daily net revenue from the orders fact table"
            actions={k ? <span className="text-[11px] font-medium text-slate-500">{signedPct(k.revenue_change_pct)} vs previous window</span> : null}
          >
            {trend.length === 0 ? (
              <p className="py-12 text-center text-sm text-slate-500">No orders in this window.</p>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={trend} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="rev" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#4f46e5" stopOpacity={0.28} />
                        <stop offset="100%" stopColor="#4f46e5" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                    <XAxis dataKey="date" tickFormatter={(v: string) => shortDate(v)} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} minTickGap={28} />
                    <YAxis tickFormatter={(v: number) => money(v, { compact: true })} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} width={58} />
                    <Tooltip
                      formatter={(value: number, name: string) => [name === "revenue" ? money(value) : num(value), name === "revenue" ? "Revenue" : "Orders"]}
                      labelFormatter={(v: string) => dateOnly(v)}
                    />
                    <Area type="monotone" dataKey="revenue" stroke="#4f46e5" strokeWidth={2} fill="url(#rev)" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="Order status mix" subtitle="Share of orders by final status">
            {(data?.status_breakdown ?? []).length === 0 ? (
              <p className="py-12 text-center text-sm text-slate-500">No status data.</p>
            ) : (
              <>
                <div className="h-44">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={data?.status_breakdown} dataKey="orders" nameKey="status" innerRadius={44} outerRadius={70} paddingAngle={2}>
                        {(data?.status_breakdown ?? []).map((entry, i) => (
                          <Cell key={entry.status} fill={PIE_COLORS[i % PIE_COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip formatter={(value: number) => num(value)} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
                <ul className="mt-2 space-y-1.5">
                  {(data?.status_breakdown ?? []).map((s, i) => (
                    <li key={s.status} className="flex items-center gap-2 text-xs">
                      <span className="h-2 w-2 rounded-full" style={{ background: PIE_COLORS[i % PIE_COLORS.length] }} />
                      <span className="capitalize text-slate-600">{s.status}</span>
                      <span className="ml-auto font-medium text-slate-800">{num(s.orders)}</span>
                      <span className="w-12 text-right text-slate-400">{pct(s.share)}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </Panel>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Top categories" subtitle="Revenue contribution inside the current scope">
            <ul className="space-y-3">
              {(data?.top_categories ?? []).map((c) => (
                <li key={c.category}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="font-medium text-slate-700">{c.category}</span>
                    <span className="text-slate-500">
                      {money(c.revenue, { compact: true })} · {pct(c.share)}
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(100, c.share)}%` }} />
                  </div>
                </li>
              ))}
              {(data?.top_categories ?? []).length === 0 ? <li className="py-6 text-center text-sm text-slate-500">No category revenue.</li> : null}
            </ul>
          </Panel>

          <Panel title="Top regions" subtitle="Where the revenue comes from">
            <ul className="space-y-3">
              {(data?.top_regions ?? []).map((r) => (
                <li key={r.region}>
                  <div className="flex items-baseline justify-between text-xs">
                    <span className="font-medium text-slate-700">{r.region}</span>
                    <span className="text-slate-500">
                      {money(r.revenue, { compact: true })} · {num(r.orders)} orders
                    </span>
                  </div>
                  <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.min(100, r.share)}%` }} />
                  </div>
                </li>
              ))}
              {(data?.top_regions ?? []).length === 0 ? <li className="py-6 text-center text-sm text-slate-500">No regional revenue.</li> : null}
            </ul>
          </Panel>
        </div>

        <Panel className="mt-3" title="Latest orders" subtitle="Most recent rows in the selected window" bodyClassName="p-0">
          {(data?.recent_orders ?? []).length === 0 ? (
            <p className="py-10 text-center text-sm text-slate-500">No orders in this window.</p>
          ) : (
            <DataTable columns={orderColumns} rows={data?.recent_orders ?? []} rowKey={(r) => r.order_id} />
          )}
        </Panel>
      </AsyncBody>
    </div>
  );
}
