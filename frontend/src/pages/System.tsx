import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { AsyncBody, KpiCard, Panel, SectionHeading, StatusBadge } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateTime, num } from "../lib/format";
import type { SystemResponse } from "../types";

type Service = SystemResponse["services"][number];
type Freshness = SystemResponse["data_freshness"][number];
type RowCount = SystemResponse["row_counts"][number];

export default function System() {
  const { data, loading, error, reload } = useApi(() => api.system(), "system-status");

  const serviceColumns: Column<Service>[] = [
    { key: "name", header: "Service", render: (r) => <span className="font-medium text-slate-800">{r.name}</span> },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "mode", header: "Mode", render: (r) => <span className="text-xs uppercase tracking-wide text-slate-500">{r.mode}</span> },
    { key: "detail", header: "Detail", render: (r) => <span className="block max-w-[480px] truncate text-xs text-slate-500">{r.detail}</span> },
  ];

  const freshnessColumns: Column<Freshness>[] = [
    { key: "dataset", header: "Dataset", render: (r) => <span className="font-mono text-xs text-slate-700">{r.dataset}</span> },
    { key: "latest", header: "Latest record", render: (r) => dateTime(r.latest) },
    {
      key: "lag_minutes",
      header: "Lag",
      align: "right",
      render: (r) => (r.lag_minutes === null ? "—" : r.lag_minutes >= 1440 ? `${num(r.lag_minutes / 1440, 1)} d` : `${num(r.lag_minutes, 0)} min`),
    },
    { key: "status", header: "Freshness", render: (r) => <StatusBadge status={r.status} /> },
  ];

  const app = data?.application;
  const db = data?.database;

  return (
    <div className="space-y-5">
      <SectionHeading
        title="System status"
        subtitle="Runtime configuration, service inventory, data freshness and warehouse row counts"
        right={
          <button type="button" className="btn" onClick={reload}>
            <RefreshCw size={14} /> Refresh
          </button>
        }
      />

      <AsyncBody loading={loading} error={error} onRetry={reload} skeletonRows={4}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Application" value={`${app?.name ?? "—"} ${app?.version ?? ""}`} hint={app?.environment} />
          <KpiCard
            label="Database"
            value={db?.connected ? "Connected" : "Unavailable"}
            hint={`${num(db?.size_mb, 1)} MB`}
            tone={db?.connected ? "emerald" : "rose"}
          />
          <KpiCard
            label="Uptime"
            value={app ? `${Math.floor((app.uptime_seconds ?? 0) / 60)} min` : "—"}
            hint={app ? `started ${dateTime(app.started_at)}` : undefined}
            tone="sky"
          />
          <KpiCard
            label="Tracked tables"
            value={num(data?.row_counts.length)}
            hint={`${num(data?.services.filter((s) => s.status === "up").length)} of ${num(data?.services.length)} services up`}
            tone="amber"
          />
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Services" subtitle="Every dependency the platform declares, with its real status">
            <DataTable columns={serviceColumns} rows={data?.services ?? []} rowKey={(r) => r.name} dense />
          </Panel>
          <Panel title="Data freshness" subtitle="How recently each dataset received data">
            <DataTable columns={freshnessColumns} rows={data?.data_freshness ?? []} rowKey={(r) => r.dataset} dense />
          </Panel>
        </div>

        <div className="mt-3 grid gap-3 xl:grid-cols-3">
          <Panel className="xl:col-span-2" title="Warehouse row counts" subtitle="Live counts read from PostgreSQL, not cached constants">
            <DataTable
              columns={[
                { key: "table", header: "Table", render: (r: RowCount) => <span className="font-mono text-xs text-slate-700">{r.table}</span> },
                { key: "rows", header: "Rows", align: "right", render: (r: RowCount) => <span className="font-medium tabular-nums">{num(r.rows)}</span> },
              ]}
              rows={data?.row_counts ?? []}
              rowKey={(r) => r.table}
              dense
              maxHeight="420px"
            />
          </Panel>

          <Panel title="Connection" subtitle="Secrets are masked server-side before they reach the browser">
            <dl className="space-y-3 text-xs">
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Connection string</dt>
                <dd className="mt-1 break-all font-mono text-[11px] text-slate-700">{db?.url ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Engine</dt>
                <dd className="mt-1 text-slate-700">{db?.version ?? "—"}</dd>
              </div>
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">API documentation</dt>
                <dd className="mt-1">
                  <a className="text-brand-600 hover:underline" href="/api/docs">
                    /api/docs
                  </a>
                  {" · "}
                  <a className="text-brand-600 hover:underline" href="/api/openapi.json">
                    OpenAPI schema
                  </a>
                </dd>
              </div>
            </dl>
          </Panel>
        </div>
      </AsyncBody>
    </div>
  );
}
