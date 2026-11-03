import { useState } from "react";
import { Play, Radio, RefreshCw } from "lucide-react";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { AsyncBody, InlineSpinner, KpiCard, Panel, SectionHeading, StatusBadge } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { dateTime, num } from "../lib/format";
import type { PipelineRun, PipelineStatusResponse } from "../types";

type Topic = PipelineStatusResponse["topics"][number];
type Layer = PipelineStatusResponse["layers"][number];
type Dag = PipelineStatusResponse["orchestration"][number];

const STAGES = [
  { value: "quality", label: "Run quality checks" },
  { value: "gold", label: "Rebuild gold layer" },
  { value: "dbt", label: "Run dbt models" },
  { value: "stream", label: "Drain stream topic" },
];

export default function Pipeline() {
  const { data, loading, error, reload } = useApi(() => api.pipelineStatus(), "pipeline-status");
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  async function run(stage: string) {
    setBusy(stage);
    setNotice(null);
    setFailure(null);
    try {
      const res = await api.triggerPipeline({ stages: [stage] });
      setNotice(`${stage}: run #${res.run_id ?? "—"} ${res.status ?? "accepted"}`);
      reload();
    } catch (err) {
      setFailure(`${stage}: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(null);
    }
  }

  const m = data?.metrics;
  const last = data?.last_run;

  // The API reports the consumer group's last activity as an age in hours, not a
  // status string, so build the hint defensively instead of rendering "undefined".
  const health = data?.stream_health;
  const streamHint = health
    ? [
        health.consumer_group,
        typeof health.last_run_age_hours === "number" ? `last batch ${health.last_run_age_hours.toFixed(1)} h ago` : null,
        health.status ?? null,
      ]
        .filter(Boolean)
        .join(" · ")
    : undefined;

  const runColumns: Column<PipelineRun>[] = [
    { key: "run_id", header: "Run", align: "right", render: (r) => <span className="font-mono text-xs">#{r.run_id}</span> },
    { key: "pipeline_name", header: "Pipeline", render: (r) => <span className="block max-w-[220px] truncate">{r.pipeline_name}</span> },
    { key: "run_type", header: "Type", render: (r) => <span className="text-xs uppercase tracking-wide text-slate-500">{r.run_type}</span> },
    { key: "status", header: "Status", render: (r) => <StatusBadge status={r.status} /> },
    { key: "started_at", header: "Started", render: (r) => dateTime(r.started_at) },
    { key: "duration_seconds", header: "Duration", align: "right", render: (r) => (r.duration_seconds === null ? "—" : `${num(r.duration_seconds, 1)} s`) },
    { key: "records_in", header: "In", align: "right", render: (r) => num(r.records_in) },
    { key: "records_out", header: "Out", align: "right", render: (r) => num(r.records_out) },
    { key: "records_rejected", header: "Rejected", align: "right", render: (r) => num(r.records_rejected) },
  ];

  const topicColumns: Column<Topic>[] = [
    { key: "topic", header: "Topic", render: (r) => <span className="font-mono text-xs text-slate-700">{r.topic}</span> },
    { key: "role", header: "Role", render: (r) => <span className="text-xs text-slate-500">{r.role ?? "—"}</span> },
    { key: "partitions", header: "Partitions", align: "right", render: (r) => num(r.partitions) },
    { key: "messages", header: "Messages", align: "right", render: (r) => num(r.messages) },
    {
      key: "bytes",
      header: "Size",
      align: "right",
      render: (r) => (typeof r.bytes === "number" ? `${(r.bytes / 1024 / 1024).toFixed(2)} MB` : "—"),
    },
    {
      key: "lag",
      header: "Lag",
      align: "right",
      render: (r) => <span className={r.lag > 0 ? "font-medium text-amber-600" : "text-slate-500"}>{num(r.lag)}</span>,
    },
  ];

  const layerColumns: Column<Layer>[] = [
    { key: "layer", header: "Layer", render: (r) => <span className="font-medium capitalize text-slate-800">{r.layer}</span> },
    { key: "records", header: "Records", align: "right", render: (r) => num(r.records) },
    { key: "file_count", header: "Files", align: "right", render: (r) => (r.file_count === undefined ? "—" : num(r.file_count)) },
    { key: "size_mb", header: "Size", align: "right", render: (r) => `${num(r.size_mb, 2)} MB` },
    { key: "last_updated", header: "Updated", render: (r) => dateTime(r.last_updated) },
    { key: "location", header: "Location", render: (r) => <span className="block max-w-[240px] truncate font-mono text-[11px] text-slate-500">{r.location}</span> },
  ];

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Pipeline monitoring"
        subtitle={data ? `Stream and batch health · checked ${dateTime(data.checked_at)}` : "Streaming, batch and orchestration health"}
        right={
          <button type="button" className="btn" onClick={reload}>
            <RefreshCw size={14} /> Refresh
          </button>
        }
      />

      <AsyncBody loading={loading} error={error} onRetry={reload} skeletonRows={4}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard
            label="Pipeline status"
            value={(data?.status ?? "unknown").replace(/^\w/, (c) => c.toUpperCase())}
            hint={last ? `last run ${dateTime(last.started_at)}` : "no completed run"}
            tone={data?.status === "healthy" ? "emerald" : data?.status === "degraded" ? "amber" : "rose"}
          />
          <KpiCard label="Events processed" value={num(m?.events_processed)} hint={`${num(m?.throughput_per_min)} events/min`} tone="sky" />
          <KpiCard
            label="Consumer lag"
            value={num(m?.consumer_lag)}
            hint={streamHint}
            tone={(m?.consumer_lag ?? 0) > 0 ? "amber" : "emerald"}
          />
          <KpiCard
            label="Rejected / deduplicated"
            value={`${num(m?.records_rejected)} / ${num(m?.deduplicated)}`}
            hint={`${num(m?.late_events)} late events absorbed`}
            tone="rose"
          />
        </div>

        <Panel
          className="mt-3"
          title="Manual triggers"
          subtitle="Each button calls the same in-process function the Airflow DAG task calls, so a manual run cannot diverge from a scheduled one"
          actions={busy ? <InlineSpinner label={`Running ${busy}…`} /> : undefined}
        >
          <div className="flex flex-wrap gap-2">
            {STAGES.map((stage) => (
              <button key={stage.value} type="button" className="btn-primary" disabled={busy !== null} onClick={() => run(stage.value)}>
                <Play size={13} /> {stage.label}
              </button>
            ))}
          </div>
          {notice ? <p className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-700">{notice}</p> : null}
          {failure ? <p className="mt-3 rounded-lg bg-rose-50 px-3 py-2 text-xs text-rose-700">{failure}</p> : null}
          <p className="mt-3 text-[11px] text-slate-400">
            A full warehouse re-load stays off this screen on purpose: the fact tables are already verified, and a reload is only
            appropriate after a data integrity incident. It remains available at <code className="font-mono">POST /api/pipeline/trigger</code>{" "}
            with <code className="font-mono">{'{"stages":["warehouse"]}'}</code>.
          </p>
        </Panel>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Kafka-style topics" subtitle="Append-only topic files with partition and lag accounting" bodyClassName="p-0">
            <DataTable columns={topicColumns} rows={data?.topics ?? []} rowKey={(r) => r.topic} dense />
          </Panel>
          <Panel title="Medallion layers" subtitle="Bronze, silver and gold footprints on disk" bodyClassName="p-0">
            <DataTable columns={layerColumns} rows={data?.layers ?? []} rowKey={(r) => r.layer} dense />
          </Panel>
        </div>

        <Panel className="mt-3" title="Orchestration" subtitle="DAG definitions registered with the scheduler" bodyClassName="p-0">
          <DataTable
            columns={[
              { key: "dag_id", header: "DAG", render: (r: Dag) => <span className="font-mono text-xs text-slate-700">{r.dag_id}</span> },
              { key: "schedule", header: "Schedule", render: (r: Dag) => <span className="text-xs">{r.schedule}</span> },
              { key: "tasks", header: "Tasks", render: (r: Dag) => <span className="text-xs text-slate-500">{r.tasks ? r.tasks.length : "—"}</span> },
              { key: "state", header: "State", render: (r: Dag) => <StatusBadge status={r.state} /> },
              { key: "last_run", header: "Last run", render: (r: Dag) => dateTime(r.last_run) },
              { key: "next_run", header: "Next run", render: (r: Dag) => dateTime(r.next_run) },
            ]}
            rows={data?.orchestration ?? []}
            rowKey={(r) => r.dag_id}
            dense
          />
        </Panel>

        <Panel className="mt-3" title="Recent runs" subtitle="Durable run history with record accounting" bodyClassName="p-0">
          <DataTable columns={runColumns} rows={data?.runs ?? []} rowKey={(r) => String(r.run_id)} dense maxHeight="380px" />
        </Panel>

        <p className="flex items-center gap-1.5 text-[11px] text-slate-400">
          <Radio size={12} /> Mean processing latency {num(m?.processing_latency_ms)} ms · local runtime, no managed services
        </p>
      </AsyncBody>
    </div>
  );
}
