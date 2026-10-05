import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { PlusCircle, ShieldCheck, ShieldAlert, ShieldQuestion } from "lucide-react";
import { listShipments } from "../api/shipments";
import type { ShipmentListRow } from "../types/shipment";
import ShipmentTable from "../components/history/ShipmentTable";

export default function DashboardPage() {
  const [rows, setRows] = useState<ShipmentListRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listShipments()
      .then(setRows)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  const passed = rows.filter((r) => r.verdict === "PASSED").length;
  const flagged = rows.filter((r) => r.verdict === "WARNING" || r.verdict === "REJECTED").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Shipment history</h1>
          <p className="text-sm text-slate-500">Các lô hàng đã trích xuất và đối chiếu rủi ro.</p>
        </div>
        <Link
          to="/upload"
          className="inline-flex items-center gap-2 rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800"
        >
          <PlusCircle className="h-4 w-4" />
          Kiểm tra lô hàng mới
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-2 inline-flex rounded-lg bg-slate-100 p-2 text-slate-700">
            <ShieldQuestion className="h-5 w-5" />
          </div>
          <p className="text-2xl font-bold text-slate-900">{rows.length}</p>
          <p className="text-xs text-slate-500">Tổng số hồ sơ đã kiểm tra</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-2 inline-flex rounded-lg bg-emerald-100 p-2 text-emerald-700">
            <ShieldCheck className="h-5 w-5" />
          </div>
          <p className="text-2xl font-bold text-slate-900">{passed}</p>
          <p className="text-xs text-slate-500">Hồ sơ hợp lệ (PASSED)</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="mb-2 inline-flex rounded-lg bg-red-100 p-2 text-red-700">
            <ShieldAlert className="h-5 w-5" />
          </div>
          <p className="text-2xl font-bold text-slate-900">{flagged}</p>
          <p className="text-xs text-slate-500">Hồ sơ bị cảnh báo rủi ro</p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">
          {error}
        </div>
      )}
      {loading ? (
        <div className="flex justify-center py-12">
          <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : (
        <ShipmentTable rows={rows} />
      )}
    </div>
  );
}
