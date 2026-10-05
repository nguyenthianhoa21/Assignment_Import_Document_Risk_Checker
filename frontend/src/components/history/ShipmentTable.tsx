import { Eye, Package } from "lucide-react";
import { Link } from "react-router-dom";
import type { ShipmentListRow } from "../../types/shipment";
import StatusBadge, { toneForSeverity } from "../common/StatusBadge";

function verdictBadge(verdict: string) {
  switch (verdict) {
    case "REJECTED":
      return <StatusBadge label="REJECTED" tone="danger" />;
    case "WARNING":
      return <StatusBadge label="WARNING" tone="warning" />;
    case "PASSED":
      return <StatusBadge label="PASSED" tone="success" />;
    default:
      return <StatusBadge label={verdict} tone={toneForSeverity(verdict)} />;
  }
}

export default function ShipmentTable({ rows }: { rows: ShipmentListRow[] }) {
  if (rows.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-slate-300 px-6 py-12 text-center">
        <Package className="mx-auto h-8 w-8 text-slate-400" />
        <p className="mt-2 text-sm font-medium text-slate-600">Chưa có lô hàng nào</p>
        <p className="text-xs text-slate-500">Hãy tải chứng từ của lô mới để bắt đầu kiểm tra.</p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-left">
        <thead className="bg-slate-50">
          <tr className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            <th className="px-4 py-3">Title</th>
            <th className="px-4 py-3">Created</th>
            <th className="px-4 py-3">Docs</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Verdict</th>
            <th className="px-4 py-3">High / Medium</th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.id} className="hover:bg-slate-50">
              <td className="max-w-[260px] truncate px-4 py-3 text-sm font-medium text-slate-900">
                {row.title}
              </td>
              <td className="px-4 py-3 text-xs text-slate-600">
                {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
              </td>
              <td className="px-4 py-3 text-sm text-slate-600">{row.document_count}</td>
              <td className="px-4 py-3 text-xs font-medium text-slate-700">{row.status}</td>
              <td className="px-4 py-3">{verdictBadge(row.verdict)}</td>
              <td className="px-4 py-3 text-sm">
                <span className="rounded-md bg-red-50 px-2 py-1 font-semibold text-red-700 ring-1 ring-red-200">
                  {row.high_count}
                </span>
                <span className="mx-1 text-slate-300">/</span>
                <span className="rounded-md bg-amber-50 px-2 py-1 font-semibold text-amber-700 ring-1 ring-amber-200">
                  {row.medium_count}
                </span>
              </td>
              <td className="px-4 py-3">
                <Link
                  to={`/shipments/${row.id}`}
                  className="inline-flex items-center gap-1.5 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                >
                  <Eye className="h-3.5 w-3.5" />
                  View
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
