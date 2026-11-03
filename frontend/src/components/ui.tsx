import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";

/* ------------------------------------------------------------------ badges */
const TONES: Record<string, string> = {
  emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  amber: "bg-amber-50 text-amber-700 ring-amber-200",
  rose: "bg-rose-50 text-rose-700 ring-rose-200",
  sky: "bg-sky-50 text-sky-700 ring-sky-200",
  slate: "bg-slate-100 text-slate-600 ring-slate-200",
  violet: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function toneFor(status: string | null | undefined): keyof typeof TONES {
  const s = (status ?? "").toLowerCase();
  if (["healthy", "passed", "success", "up", "fresh", "delivered", "completed", "paid", "active", "fresh"].includes(s)) return "emerald";
  if (["degraded", "warning", "pending", "processing", "stale", "idle", "registered", "available", "shipped"].includes(s)) return "amber";
  if (["failed", "critical", "down", "stalled", "cancelled", "error", "cold", "not_configured"].includes(s)) return "rose";
  if (["returned", "refunded", "refreshed"].includes(s)) return "sky";
  if (["champions", "loyal", "top"].includes(s)) return "violet";
  return "slate";
}

export function StatusBadge({ status, label }: { status: string | null | undefined; label?: string }) {
  const tone = toneFor(status);
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize ring-1 ring-inset ${TONES[tone]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {label ?? (status ?? "unknown").replace(/_/g, " ")}
    </span>
  );
}

/* ------------------------------------------------------------------- kpi */
export function KpiCard({
  label,
  value,
  hint,
  delta,
  deltaLabel,
  icon: Icon,
  tone = "brand",
}: {
  label: string;
  value: string;
  hint?: string;
  delta?: number | null;
  deltaLabel?: string;
  icon?: LucideIcon;
  tone?: "brand" | "emerald" | "amber" | "rose" | "sky";
}) {
  const iconTone: Record<string, string> = {
    brand: "bg-brand-50 text-brand-600",
    emerald: "bg-emerald-50 text-emerald-600",
    amber: "bg-amber-50 text-amber-600",
    rose: "bg-rose-50 text-rose-600",
    sky: "bg-sky-50 text-sky-600",
  };
  const up = typeof delta === "number" && delta >= 0;
  return (
    <div className="card p-4">
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
        {Icon ? (
          <span className={`grid h-8 w-8 place-items-center rounded-lg ${iconTone[tone]}`}>
            <Icon size={16} strokeWidth={2} />
          </span>
        ) : null}
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-slate-900">{value}</p>
      <div className="mt-1 flex items-center gap-2 text-[11px]">
        {typeof delta === "number" ? (
          <span className={`font-semibold ${up ? "text-emerald-600" : "text-rose-600"}`}>
            {up ? "▲" : "▼"} {Math.abs(delta).toFixed(1)}%
          </span>
        ) : null}
        {deltaLabel ? <span className="text-slate-400">{deltaLabel}</span> : null}
        {hint ? <span className="text-slate-500">{hint}</span> : null}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ panels */
export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClassName = "p-5",
}: {
  title?: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {title ? (
        <header className="card-header">
          <div>
            <h2 className="card-title">{title}</h2>
            {subtitle ? <p className="card-subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function SectionHeading({ title, subtitle, right }: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p> : null}
      </div>
      {right}
    </div>
  );
}

/* ------------------------------------------------------------------ states */
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`skeleton ${className}`} />;
}

export function LoadingBlock({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <Skeleton key={i} className="h-10 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ title, message, icon: Icon = Inbox }: { title: string; message?: string; icon?: LucideIcon }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      <span className="grid h-10 w-10 place-items-center rounded-full bg-slate-100 text-slate-400">
        <Icon size={18} />
      </span>
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {message ? <p className="max-w-sm text-xs text-slate-500">{message}</p> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-rose-700">
        <AlertTriangle size={16} /> Request failed
      </div>
      <p className="text-xs text-rose-600">{message}</p>
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function InlineSpinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs text-slate-500">
      <Loader2 size={14} className="animate-spin" />
      {label ?? "Working…"}
    </span>
  );
}

/** Wraps a chart/table body with loading, error and empty handling. */
export function AsyncBody({
  loading,
  error,
  isEmpty,
  emptyTitle = "No data for this filter",
  emptyMessage = "Widen the date range or clear the category/region filter.",
  onRetry,
  skeletonRows = 3,
  children,
}: {
  loading: boolean;
  error: string | null;
  isEmpty?: boolean;
  emptyTitle?: string;
  emptyMessage?: string;
  onRetry?: () => void;
  skeletonRows?: number;
  children: ReactNode;
}) {
  if (loading) return <LoadingBlock rows={skeletonRows} />;
  if (error) return <ErrorState message={error} onRetry={onRetry} />;
  if (isEmpty) return <EmptyState title={emptyTitle} message={emptyMessage} />;
  return <>{children}</>;
}
