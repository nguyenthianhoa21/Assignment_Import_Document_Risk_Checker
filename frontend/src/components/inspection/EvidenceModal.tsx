import { X } from "lucide-react";

export default function EvidenceModal({
  title,
  snippet,
  onClose,
}: {
  title: string;
  snippet: string | null;
  onClose: () => void;
}) {
  if (!snippet) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-2xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
          <button onClick={onClose} className="rounded-md p-1 text-slate-400 hover:bg-slate-100">
            <X className="h-5 w-5" />
          </button>
        </div>
        <pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-4 text-sm text-slate-700 ring-1 ring-slate-200">
          {snippet}
        </pre>
      </div>
    </div>
  );
}
