import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { AlertTriangle, Download, Sparkles } from "lucide-react";
import { api, toQuery } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useFilters } from "../context/Filters";
import { AsyncBody, EmptyState, KpiCard, Panel, SectionHeading, StatusBadge } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateOnly, money, num, pct, shortDate } from "../lib/format";
import type { DailySalesRow, ForecastResponse } from "../types";

type Anomaly = ForecastResponse["anomalies"][number];

interface PlotRow {
  date: string;
  actual?: number;
  forecast?: number;
  lower?: number;
  band?: number;
}

const HORIZONS = [7, 30, 60, 90];

export default function Reports() {
  const { query, refreshToken } = useFilters();
  const [horizon, setHorizon] = useState(30);
  const key = JSON.stringify(query) + refreshToken;

  const daily = useApi(() => api.dailySales(query), key);
  const forecast = useApi(() => api.forecast({ ...query, horizon }), `${key}-${horizon}`);

  const f = forecast.data;
  const plot: PlotRow[] = [
    ...(f?.history ?? []).map((h) => ({ date: h.date, actual: h.revenue })),
    ...(f?.forecast ?? []).map((p) => ({
      date: p.date,
      forecast: p.revenue,
      lower: p.lower,
      band: Math.max(0, p.upper - p.lower),
    })),
  ];

  const salesColumns: Column<DailySalesRow>[] = [
    { key: "date", header: "Date", render: (r) => dateOnly(r.date) },
    { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
    { key: "completed_orders", header: "Done", align: "right", render: (r) => num(r.completed_orders) },
    { key: "cancelled_orders", header: "Cancel", align: "right", render: (r) => num(r.cancelled_orders) },
    { key: "returned_orders", header: "Returns", align: "right", render: (r) => num(r.returned_orders) },
    { key: "units_sold", header: "Units", align: "right", render: (r) => num(r.units_sold) },
    { key: "gross_revenue", header: "Gross", align: "right", render: (r) => money(r.gross_revenue) },
    { key: "discount_amount", header: "Discount", align: "right", render: (r) => money(r.discount_amount) },
    { key: "net_revenue", header: "Net", align: "right", render: (r) => <span className="font-medium text-slate-900">{money(r.net_revenue, { decimals: 2 })}</span> },
    { key: "new_customers", header: "New", align: "right", render: (r) => num(r.new_customers) },
  ];

  const anomalyColumns: Column<Anomaly>[] = [
    { key: "date", header: "Date", render: (r) => dateOnly(r.date) },
    { key: "revenue", header: "Observed", align: "right", render: (r) => money(r.revenue, { decimals: 2 }) },
    { key: "expected", header: "Expected", align: "right", render: (r) => money(r.expected, { decimals: 2 }) },
    {
      key: "deviation_pct",
      header: "Deviation",
      align: "right",
      render: (r) => (
        <span className={r.deviation_pct >= 0 ? "text-emerald-600" : "text-rose-600"}>
          {r.deviation_pct > 0 ? "+" : ""}
          {pct(r.deviation_pct)}
        </span>
      ),
    },
    { key: "z_score", header: "Z-score", align: "right", render: (r) => num(r.z_score, 2) },
    { key: "severity", header: "Severity", render: (r) => <StatusBadge status={r.severity} /> },
    { key: "direction", header: "Direction", render: (r) => <span className="text-xs capitalize text-slate-500">{r.direction}</span> },
  ];

  const totals = daily.data?.totals;

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Reports"
        subtitle="Daily gold-layer report plus the revenue forecast — observed history and model output are drawn and labelled separately"
        right={
          <a className="btn" href={`/api/reports/daily-sales${toQuery({ ...query, format: "csv" })}`}>
            <Download size={14} /> Download CSV
          </a>
        }
      />

      <AsyncBody loading={daily.loading} error={daily.error} onRetry={daily.reload} skeletonRows={4}>
        <div className="grid gap-3 sm:grid-cols-3">
          <KpiCard label="Report revenue" value={money(totals?.revenue, { compact: true })} hint="sum of daily net revenue" />
          <KpiCard label="Orders in report" value={num(totals?.orders)} tone="sky" />
          <KpiCard label="Units in report" value={num(totals?.units)} tone="emerald" />
        </div>

        {daily.data?.note ? (
          <p className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-700">
            <AlertTriangle size={13} className="mt-0.5 shrink-0" /> {daily.data.note}
          </p>
        ) : null}

        <Panel
          className="mt-3"
          title="Daily sales report"
          subtitle={daily.data ? `${daily.data.rows.length} daily rows · gold layer analytics.sales_daily · generated ${dateOnly(daily.data.generated_at)}` : undefined}
          bodyClassName="p-0"
        >
          {daily.data?.rows.length === 0 ? (
            <EmptyState title="No daily aggregate rows" message="The gold layer has no rows for this window." />
          ) : (
            <DataTable columns={salesColumns} rows={daily.data?.rows ?? []} rowKey={(r) => r.date} dense maxHeight="420px" />
          )}
        </Panel>
      </AsyncBody>

      <AsyncBody loading={forecast.loading} error={forecast.error} onRetry={forecast.reload} skeletonRows={3}>
        <Panel
          title="Revenue forecast"
          subtitle="Solid line = observed revenue from the warehouse · dashed line = model output · shaded band = prediction interval"
          actions={
            <div className="flex items-center gap-1 rounded-lg border border-slate-200 bg-white p-1">
              {HORIZONS.map((h) => (
                <button
                  key={h}
                  type="button"
                  onClick={() => setHorizon(h)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
                    horizon === h ? "bg-brand-600 text-white" : "text-slate-600 hover:bg-slate-50"
                  }`}
                >
                  {h}d
                </button>
              ))}
            </div>
          }
        >
          <div className="mb-3 grid gap-3 sm:grid-cols-4">
            <KpiCard label="Forecast revenue" value={money(f?.summary.forecast_revenue, { compact: true })} hint={`${f?.summary.horizon_days ?? horizon} day horizon`} />
            <KpiCard
              label="Expected growth"
              value={f ? `${f.summary.expected_growth_pct > 0 ? "+" : ""}${pct(f.summary.expected_growth_pct)}` : "—"}
              hint="vs the observed window"
              tone="emerald"
            />
            <KpiCard label="Model error (MAPE)" value={f ? pct(f.model.mape, 2) : "—"} hint={f?.model.name} tone="amber" />
            <KpiCard label="Anomalies flagged" value={num(f?.anomalies.length)} hint="observed days outside the band" tone="rose" />
          </div>

          {plot.length === 0 ? (
            <EmptyState title="Forecast unavailable" message="At least two weeks of daily revenue are required." />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={plot} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                  <XAxis
                    dataKey="date"
                    tickFormatter={(value) => shortDate(String(value))}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={30}
                  />
                  <YAxis
                    tickFormatter={(value) => money(Number(value), { compact: true })}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    width={58}
                  />
                  <Tooltip
                    formatter={(value, name) => {
                      if (name === "lower") return ["", ""];
                      if (name === "band") return ["prediction interval", "Interval"];
                      return [money(Number(value)), name === "actual" ? "Actual revenue" : "Forecast"];
                    }}
                    labelFormatter={(label) => dateOnly(String(label))}
                  />
                  <Area dataKey="lower" stackId="ci" stroke="none" fill="transparent" isAnimationActive={false} />
                  <Area dataKey="band" stackId="ci" stroke="none" fill="#a5b4fc" fillOpacity={0.35} isAnimationActive={false} />
                  <Line type="monotone" dataKey="actual" stroke="#4f46e5" strokeWidth={2} dot={false} isAnimationActive={false} />
                  <Line type="monotone" dataKey="forecast" stroke="#f59e0b" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </div>
          )}

          <p className="mt-3 flex items-start gap-2 rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
            <Sparkles size={13} className="mt-0.5 shrink-0" />
            <span>
              <span className="font-semibold text-slate-700">Model output, not actuals.</span> {f?.disclaimer ?? ""}
              {f ? ` Trained on ${num(f.model.trained_on_days)} days with ${f.model.method}.` : null}
            </span>
          </p>
        </Panel>

        <Panel className="mt-3" title="Detected anomalies" subtitle="Observed days whose revenue deviates beyond the expected range" bodyClassName="p-0">
          {(f?.anomalies ?? []).length === 0 ? (
            <EmptyState title="No anomalies detected" message="Every observed day sits inside the expected range." />
          ) : (
            <DataTable columns={anomalyColumns} rows={f?.anomalies ?? []} rowKey={(r) => r.date} dense maxHeight="320px" />
          )}
        </Panel>
      </AsyncBody>
    </div>
  );
}
