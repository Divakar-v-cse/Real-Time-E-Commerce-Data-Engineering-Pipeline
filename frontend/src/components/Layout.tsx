import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  Activity,
  BarChart3,
  Database,
  FileText,
  LayoutDashboard,
  Menu,
  Package,
  RefreshCw,
  Server,
  ShieldCheck,
  ShoppingCart,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import { CATEGORIES, REGIONS, useFilters, type Preset } from "../context/Filters";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { compact, dateOnly, money } from "../lib/format";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/sales", label: "Sales", icon: TrendingUp },
  { to: "/customers", label: "Customers", icon: Users },
  { to: "/products", label: "Products", icon: Package },
  { to: "/orders", label: "Order management", icon: ShoppingCart },
  { to: "/data-quality", label: "Data quality", icon: ShieldCheck },
  { to: "/pipeline", label: "Pipeline monitoring", icon: Activity },
  { to: "/system", label: "System status", icon: Server },
  { to: "/reports", label: "Reports", icon: FileText },
];

const PRESETS: { value: Preset; label: string }[] = [
  { value: "7d", label: "Last 7 days" },
  { value: "30d", label: "Last 30 days" },
  { value: "90d", label: "Last 90 days" },
  { value: "180d", label: "Last 180 days" },
  { value: "365d", label: "Last 12 months" },
  { value: "all", label: "All time" },
];

export default function Layout() {
  const { preset, setPreset, filters, setCategory, setRegion, refresh, refreshToken } = useFilters();
  const [navOpen, setNavOpen] = useState(false);
  const [spinning, setSpinning] = useState(false);
  const location = useLocation();
  const health = useApi(() => api.health(), `health-${refreshToken}`);

  const title = NAV.find((n) => (n.end ? location.pathname === n.to : location.pathname.startsWith(n.to)))?.label ?? "Dashboard";

  return (
    <div className="min-h-screen bg-slate-100">
      {/* sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-60 transform bg-ink-950 text-slate-300 transition-transform lg:translate-x-0 ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-16 items-center gap-2.5 border-b border-white/10 px-5">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-brand-600 text-white">
            <BarChart3 size={18} />
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-white">Divakar Analytics</p>
            <p className="truncate text-[11px] text-slate-400">E-Commerce Intelligence</p>
          </div>
          <button type="button" className="ml-auto text-slate-400 lg:hidden" onClick={() => setNavOpen(false)} aria-label="Close navigation">
            <X size={18} />
          </button>
        </div>

        <nav className="mt-4 space-y-1 px-3">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setNavOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition ${
                  isActive ? "bg-brand-600/15 font-semibold text-white ring-1 ring-inset ring-brand-500/40" : "hover:bg-white/5 hover:text-white"
                }`
              }
            >
              <Icon size={16} className="shrink-0" />
              <span className="truncate">{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="absolute inset-x-0 bottom-0 border-t border-white/10 p-4 text-[11px] text-slate-400">
          <div className="flex items-center gap-2">
            <Database size={13} />
            <span className="truncate">
              {health.data ? `${compact(health.data.warehouse.orders)} orders · ${compact(health.data.warehouse.customers)} customers` : "connecting…"}
            </span>
          </div>
          <p className="mt-1.5 truncate">{health.data ? money(health.data.warehouse.revenue, { compact: true }) : "—"} lifetime revenue</p>
        </div>
      </aside>

      {navOpen ? <div className="fixed inset-0 z-30 bg-slate-900/40 lg:hidden" onClick={() => setNavOpen(false)} /> : null}

      {/* main */}
      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/85 backdrop-blur">
          <div className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
            <button type="button" className="btn lg:hidden" onClick={() => setNavOpen(true)} aria-label="Open navigation">
              <Menu size={16} />
            </button>
            <div className="mr-auto">
              <h1 className="text-sm font-semibold text-slate-900">{title}</h1>
              <p className="text-[11px] text-slate-500">
                {dateOnly(filters.start_date)} → {dateOnly(filters.end_date)} · {filters.category} · {filters.region}
              </p>
            </div>

            <select className="select" value={preset} onChange={(e) => setPreset(e.target.value as Preset)} aria-label="Date range">
              {PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
            <select className="select" value={filters.category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c === "All" ? "All categories" : c}
                </option>
              ))}
            </select>
            <select className="select" value={filters.region} onChange={(e) => setRegion(e.target.value)} aria-label="Region">
              {REGIONS.map((r) => (
                <option key={r} value={r}>
                  {r === "All" ? "All regions" : r}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setSpinning(true);
                refresh();
                window.setTimeout(() => setSpinning(false), 700);
              }}
              aria-label="Refresh data"
            >
              <RefreshCw size={14} className={spinning ? "animate-spin" : ""} />
              Refresh
            </button>
            <span
              className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset ${
                health.data?.status === "ok"
                  ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
                  : health.error
                    ? "bg-rose-50 text-rose-700 ring-rose-200"
                    : "bg-slate-100 text-slate-500 ring-slate-200"
              }`}
              title={health.error ?? health.data?.database.version}
            >
              <span className="h-1.5 w-1.5 rounded-full bg-current" />
              {health.data?.status === "ok" ? "Warehouse live" : health.error ? "API offline" : "Connecting"}
            </span>
          </div>
        </header>

        <main className="px-4 py-5 sm:px-6 sm:py-6">
          <Outlet />
        </main>

        <footer className="border-t border-slate-200 px-6 py-4 text-[11px] text-slate-400">
          Divakar Data Analytics E-Commerce Project · every metric is queried from the PostgreSQL warehouse ·
          {" "}
          <a className="text-brand-600 hover:underline" href="/api/docs">
            API docs
          </a>
        </footer>
      </div>
    </div>
  );
}
