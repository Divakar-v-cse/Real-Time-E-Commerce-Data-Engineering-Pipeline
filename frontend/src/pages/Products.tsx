import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useApi } from "../hooks/useApi";
import { useFilters } from "../context/Filters";
import { AsyncBody, EmptyState, KpiCard, Panel, SectionHeading } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";
import { money, num, pct } from "../lib/format";
import type { ProductResponse } from "../types";

type BestSeller = ProductResponse["best_sellers"][number];
type LowPerformer = ProductResponse["low_performers"][number];
type ReturnRate = ProductResponse["return_rates"][number];

export default function Products() {
  const { query, refreshToken } = useFilters();
  const key = JSON.stringify(query) + refreshToken;
  const { data, loading, error, reload } = useApi(() => api.products(query), key);

  const bestSellers = data?.best_sellers ?? [];
  const categories = data?.by_category ?? [];
  const revenueTotal = bestSellers.reduce((acc, row) => acc + row.revenue, 0);
  const unitsTotal = bestSellers.reduce((acc, row) => acc + row.units, 0);
  const weightedReturn =
    unitsTotal > 0
      ? bestSellers.reduce((acc, row) => acc + row.return_rate * row.units, 0) / unitsTotal
      : null;

  const bestColumns: Column<BestSeller>[] = [
    { key: "product_name", header: "Product", render: (r) => <span className="block max-w-[240px] truncate">{r.product_name}</span> },
    { key: "category", header: "Category", render: (r) => <span className="text-xs text-slate-500">{r.category}</span> },
    { key: "orders", header: "Orders", align: "right", render: (r) => num(r.orders) },
    { key: "units", header: "Units", align: "right", render: (r) => num(r.units) },
    { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { decimals: 2 }) },
    {
      key: "return_rate",
      header: "Return rate",
      align: "right",
      render: (r) => <span className={r.return_rate >= 10 ? "font-medium text-rose-600" : ""}>{pct(r.return_rate)}</span>,
    },
  ];

  const lowColumns: Column<LowPerformer>[] = [
    { key: "product_name", header: "Product", render: (r) => <span className="block max-w-[240px] truncate">{r.product_name}</span> },
    { key: "category", header: "Category", render: (r) => <span className="text-xs text-slate-500">{r.category}</span> },
    { key: "units", header: "Units", align: "right", render: (r) => num(r.units) },
    { key: "revenue", header: "Revenue", align: "right", render: (r) => money(r.revenue, { decimals: 2 }) },
  ];

  const returnColumns: Column<ReturnRate>[] = [
    { key: "product_name", header: "Product", render: (r) => <span className="block max-w-[240px] truncate">{r.product_name}</span> },
    { key: "units_sold", header: "Sold", align: "right", render: (r) => num(r.units_sold) },
    { key: "units_returned", header: "Returned", align: "right", render: (r) => num(r.units_returned) },
    {
      key: "return_rate",
      header: "Return rate",
      align: "right",
      render: (r) => <span className={r.return_rate >= 10 ? "font-medium text-rose-600" : ""}>{pct(r.return_rate)}</span>,
    },
  ];

  return (
    <div className="space-y-5">
      <SectionHeading
        title="Product performance"
        subtitle="Best sellers, under-performers and return behaviour by product and category"
      />

      <AsyncBody loading={loading} error={error} onRetry={reload} skeletonRows={4}>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <KpiCard label="Catalogue revenue" value={money(revenueTotal, { compact: true })} hint={`${num(bestSellers.length)} ranked products`} />
          <KpiCard label="Units sold" value={num(unitsTotal)} tone="sky" />
          <KpiCard label="Categories" value={num(categories.length)} tone="emerald" />
          <KpiCard label="Unit-weighted return rate" value={pct(weightedReturn)} tone="rose" hint="returns ÷ units sold" />
        </div>

        <Panel className="mt-3" title="Revenue by category" subtitle="Category contribution inside the selected window">
          {categories.length === 0 ? (
            <EmptyState title="No category sales" />
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={categories} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#eef2f7" vertical={false} />
                  <XAxis
                    dataKey="category"
                    tick={{ fontSize: 10, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    interval={0}
                    angle={-18}
                    textAnchor="end"
                    height={54}
                  />
                  <YAxis
                    tickFormatter={(value) => money(Number(value), { compact: true })}
                    tick={{ fontSize: 11, fill: "#64748b" }}
                    tickLine={false}
                    axisLine={false}
                    width={58}
                  />
                  <Tooltip formatter={(value) => money(Number(value))} />
                  <Bar dataKey="revenue" name="Revenue" fill="#4f46e5" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel className="mt-3" title="Best sellers" subtitle="Top products by revenue" bodyClassName="p-0">
          {bestSellers.length === 0 ? (
            <EmptyState title="No product sales in scope" />
          ) : (
            <DataTable columns={bestColumns} rows={bestSellers} rowKey={(r) => r.product_id} dense maxHeight="380px" />
          )}
        </Panel>

        <div className="mt-3 grid gap-3 xl:grid-cols-2">
          <Panel title="Low performers" subtitle="Lowest revenue products with at least one sale" bodyClassName="p-0">
            <DataTable columns={lowColumns} rows={data?.low_performers ?? []} rowKey={(r) => r.product_id} dense maxHeight="340px" />
          </Panel>
          <Panel title="Return rates" subtitle="Products most often sent back" bodyClassName="p-0">
            <DataTable columns={returnColumns} rows={data?.return_rates ?? []} rowKey={(r) => r.product_id} dense maxHeight="340px" />
          </Panel>
        </div>
      </AsyncBody>
    </div>
  );
}
