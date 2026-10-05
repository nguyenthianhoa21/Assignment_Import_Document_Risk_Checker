import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Loader2, UploadCloud } from "lucide-react";
import FileDropzone from "../components/upload/FileDropzone";
import { uploadShipment } from "../api/shipments";

const PHASES = [
  { key: "upload", label: "Đang tải file lên..." },
  { key: "extracting", label: "AI đang phân loại & trích xuất..." },
  { key: "done", label: "Đang đối chiếu rủi ro..." },
] as const;

export default function UploadPage() {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [phase, setPhase] = useState<(typeof PHASES)[number]["key"] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const busy = phase !== null;

  const submit = async () => {
    if (!title.trim()) {
      setError("Vui lòng nhập tên lô hàng.");
      return;
    }
    if (files.length === 0) {
      setError("Vui lòng thêm ít nhất một chứng từ.");
      return;
    }
    setError(null);
    setPhase("upload");
    try {
      const formData = new FormData();
      formData.append("title", title.trim());
      files.forEach((f) => formData.append("files", f));
      setPhase("extracting");
      const res = await uploadShipment(formData);
      setPhase("done");
      const poll = async () => {
        for (let i = 0; i < 60; i++) {
          const detail = await fetch(`/api/v1/shipments/${res.shipment_id}`).then((r) => r.json());
          if (detail.status === "EXTRACTED" || detail.status === "FAILED") {
            navigate(`/shipments/${res.shipment_id}`);
            return;
          }
          await new Promise((r) => setTimeout(r, 1000));
        }
        navigate(`/shipments/${res.shipment_id}`);
      };
      await poll();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setPhase(null);
    }
  };

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-slate-900">Upload shipment documents</h1>
        <p className="text-sm text-slate-500">
          Tải lên bộ chứng từ (Commercial Invoice, Packing List, Bill of Lading) để trích xuất và kiểm tra chéo.
        </p>
      </div>

      <div className="space-y-4 rounded-xl border border-slate-200 bg-white p-6">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-700">Tên lô hàng / Reference</label>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="VD: Lot 2609 QDO26091288"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
          />
        </div>

        <FileDropzone files={files} onChange={setFiles} />

        {error && (
          <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">{error}</div>
        )}

        {busy && (
          <div className="space-y-2 rounded-lg bg-slate-50 p-4">
            {PHASES.map((p) => {
              const active = phase === p.key;
              const done = phase === "done" && p.key !== "done";
              return (
                <div key={p.key} className="flex items-center gap-2 text-sm">
                  {done ? (
                    <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                  ) : active ? (
                    <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
                  ) : (
                    <span className="h-4 w-4 rounded-full border-2 border-slate-300" />
                  )}
                  <span className={active ? "font-medium text-slate-900" : "text-slate-500"}>{p.label}</span>
                </div>
              );
            })}
          </div>
        )}

        <button
          onClick={submit}
          disabled={busy}
          className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-800 disabled:cursor-not-allowed disabled:opacity-60"
        >
          <UploadCloud className="h-4 w-4" />
          {busy ? "Đang xử lý..." : "Bắt đầu kiểm tra (Process & Validate)"}
        </button>
      </div>
    </div>
  );
}
