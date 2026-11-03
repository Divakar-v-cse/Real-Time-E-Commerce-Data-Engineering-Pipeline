import { useMemo, useState } from "react";
import { Line, LineChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { AsyncBody, EmptyState, KpiCard, Panel, SectionHeading, StatusBadge } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateTime, num, pct } from "../lib/format";
import type { QualityCheck } from "../types";

function ScoreRing({ score }: { score: number }) {
  const radius = 46;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.max(0, Math.min(100, score));
  const stroke = clamped >= 95 ? "#059669" : clamped >= 80 ? "#d97706" : "#e11d48";
  return (
    <div className="relative h-32 w-32">
      <svg viewBox="0 0 120 120" className="h-full w-full -rotate-90">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="#e2e8f0" strokeWidth="10" />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          stroke={stroke}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${(clamped / 100) * circumference} ${circumference}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-semibold text-slate-900">{clamped.toFixed(1)}</span>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">score</span>
      </div>
    </div>
  );
}

export default function DataQuality() {
  const { data, loading, error, reload } = useApi(() => api.dataQuality(), "data-quality");
  const [layer, setLayer] = useState("All");
  const [onlyFailures, setOnlyFailures] = useState(false);

  const layers = useMemo(() => ["All", ...Array.from(new Set((data?.checks ?? []).map((c) => c.layer)))], [data]);

  const rows = useMemo(() => {
    let list = data?.checks ?? [];
    if (layer !== "All") list = list.filter((c) => c.layer === layer);
    if (onlyFailures) list = list.filter((c) => c.status.toLowerCase() !== "passed");
    return list;
  }, [data, layer, onlyFailures]);

  const columns: Column<QualityCheck>[] = [
    { key: "check_name", header: "Check", render: (r) => <span className="block max-w-[240px] truncate font-medium text-slate-800">{r.check_name.replace(/_/g, " ")}</span> },
    { key: "layer", header: "Layer", render: (r) => <span className="text-xs uppercase tracking-wide text-slate-500">{r.layer}</span> },
    { key: "table_name", header: "Table", render: (r) => <span className="font-mono text-[11px] text-slate-600">{r.table_name}</span> },
    { key: "severity", header: "Severity", render: (r) => <StatusBadge status={r.severity} /> },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "records_checked", header: "Checked", align: "right", render: (r) => num(r.records_checked) },
    { key: "records_failed", header: "Failed", align: "right", render: (r) => num(r.records_failed) },
    { key: "failure_rate", header: "Fail rate", align: "right", render: (r) => pct(r.failure_rate, 3) },
  ];

  const s = data?.summary;

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Data quality"
        subtitle={data?.run_at ? `Last validation run ${dateTime(data.run_at)}` : "Validation results across every medallion layer"}
        right={
          <button type="button" className="btn" onClick={reload}>
            <ShieldCheck size={14} /> Re-run view
          </button>
        }
      />

      <AsyncBody loading={loading} error={error} onRetry={reload} skeletonRows={4}>
        <div className="grid gap-3 xl:grid-cols-4">
          <div className="card flex items-center gap-5 p-4">
            <ScoreRing score={data?.score ?? 0} />
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Overall quality</p>
              <p className="mt-1 text-sm text-slate-700">
                {num(s?.passed)} of {num(s?.total)} checks passed
              </p>
              <p className="mt-1 text-[11px] text-slate-500">
                {num(s?.failed)} failed · {num(s?.critical_failed)} critical
              </p>
            </div>
          </div>
          <KpiCard label="Checks executed" value={num(s?.total)} hint="across bronze, silver, gold and warehouse" />
          <KpiCard label="Failed checks" value={num(s?.failed)} tone={s && s.failed > 0 ? "rose" : "emerald"} hint={`${num(s?.critical_failed)} critical severity`} />
          <KpiCard
            label="Quarantined rows"
            value={num(data?.quarantine?.rejected)}
            hint={data?.quarantine ? `${pct(data.quarantine.rejection_rate, 3)} of ${num(data.quarantine.source_orders)} source rows` : undefined}
            tone="amber"
          />
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-3">
          <Panel title="Score by layer" subtitle="Passed ÷ total checks per medallion layer">
            {(data?.by_layer ?? []).length === 0 ? (
              <EmptyState title="No layer results" />
            ) : (
              <ul className="space-y-3">
                {(data?.by_layer ?? []).map((l) => (
                  <li key={l.layer}>
                    <div className="flex items-baseline justify-between text-xs">
                      <span className="font-medium uppercase tracking-wide text-slate-700">{l.layer}</span>
                      <span className="text-slate-500">
                        {num(l.passed)}/{num(l.total)} · {pct(l.score)}
                      </span>
                    </div>
                    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
                      <div
                        className={`h-full rounded-full ${l.score >= 95 ? "bg-emerald-500" : l.score >= 80 ? "bg-amber-500" : "bg-rose-500"}`}
                        style={{ width: `${Math.min(100, l.score)}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel className="xl:col-span-2" title="Quality trend" subtitle="Score and failure count per validation run">
            {(data?.trend ?? []).length === 0 ? (
              <EmptyState title="No historical runs" message="The trend fills in as scheduled checks execute." />
            ) : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data?.trend} margin={{ top: 4, right: 12, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                    <XAxis
                      dataKey="run_at"
                      tickFormatter={(value) => new Date(String(value)).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
                      tick={{ fontSize: 10, fill: "#64748b" }}
                      tickLine={false}
                      axisLine={false}
                      minTickGap={20}
                    />
                    <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} width={36} />
                    <Tooltip
                      formatter={(value, name) => [name === "score" ? Number(value).toFixed(1) : num(Number(value)), name === "score" ? "Score" : "Failed"]}
                      labelFormatter={(label) => dateTime(String(label))}
                    />
                    <Line type="monotone" dataKey="score" stroke="#4f46e5" strokeWidth={2} dot={false} />
                    <Line type="monotone" dataKey="failed" stroke="#f43f5e" strokeWidth={1.5} strokeDasharray="4 3" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>
        </div>

        <Panel
          className="mt-3"
          title="Validation checks"
          subtitle={data?.note ? data.note : "Every check records the row counts it inspected and the rows it rejected"}
          actions={
            <div className="flex items-center gap-2">
              <select className="select" value={layer} onChange={(e) => setLayer(e.target.value)} aria-label="Layer filter">
                {layers.map((l) => (
                  <option key={l} value={l}>
                    {l === "All" ? "All layers" : l}
                  </option>
                ))}
              </select>
              <label className="flex items-center gap-1.5 text-[11px] text-slate-600">
                <input type="checkbox" checked={onlyFailures} onChange={(e) => setOnlyFailures(e.target.checked)} /> Failures only
              </label>
            </div>
          }
          bodyClassName="p-0"
        >
          {rows.length === 0 ? (
            <EmptyState title="No checks match" message="Clear the filters to see every validation check." />
          ) : (
            <DataTable columns={columns} rows={rows} rowKey={(r) => String(r.check_id)} dense maxHeight="460px" />
          )}
        </Panel>

        <Panel className="mt-3" title="Quarantine ledger" subtitle="Source rows rejected before they reached the fact tables">
          {!data?.quarantine || data.quarantine.reasons.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">No rejected source rows recorded.</p>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap gap-4 text-xs text-slate-600">
                <span>
                  <span className="font-semibold text-slate-900">{num(data.quarantine.rejected)}</span> rejected
                </span>
                <span>
                  <span className="font-semibold text-slate-900">{num(data.quarantine.source_orders)}</span> source orders
                </span>
                <span>
                  <span className="font-semibold text-slate-900">{pct(data.quarantine.rejection_rate, 3)}</span> rejection rate
                </span>
              </div>
              <DataTable
                dense
                columns={[
                  { key: "reason", header: "Rejection reason" },
                  { key: "records", header: "Records", align: "right", render: (r) => num(r.records) },
                ]}
                rows={data.quarantine.reasons}
                rowKey={(r) => r.reason}
              />
              <p className="mt-3 text-[11px] text-slate-400">
                Quarantined rows are excluded from the facts on purpose and are not counted as quality failures — they are the
                audit trail that proves bad input never entered the warehouse.
              </p>
            </>
          )}
        </Panel>
      </AsyncBody>
    </div>
  );
}
