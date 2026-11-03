import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  width?: string;
  render?: (row: T, index: number) => ReactNode;
}

const ALIGN: Record<string, string> = {
  left: "text-left",
  right: "text-right",
  center: "text-center",
};

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  dense = false,
  maxHeight,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T, index: number) => string;
  dense?: boolean;
  maxHeight?: string;
}) {
  return (
    <div className="overflow-auto" style={maxHeight ? { maxHeight } : undefined}>
      <table className="min-w-full border-separate border-spacing-0">
        <thead className="sticky top-0 z-10 bg-slate-50/95 backdrop-blur">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                style={col.width ? { width: col.width } : undefined}
                className={`th border-b border-slate-200 ${ALIGN[col.align ?? "left"]} ${dense ? "py-2" : ""}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)} className="transition hover:bg-slate-50/70">
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`td border-b border-slate-100 ${ALIGN[col.align ?? "left"]} ${dense ? "py-2 text-[13px]" : ""}`}
                >
                  {col.render ? col.render(row, index) : String((row as Record<string, unknown>)[col.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
