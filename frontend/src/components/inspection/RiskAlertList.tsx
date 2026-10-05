import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink, Quote } from "lucide-react";
import type { ValidationRiskItem } from "../../types/shipment";
import StatusBadge, { toneForSeverity } from "../common/StatusBadge";

export default function RiskAlertList({
  findings,
  onFocus,
  onSnippet,
}: {
  findings: ValidationRiskItem[];
  onFocus: (ruleId: string) => void;
  onSnippet: (item: ValidationRiskItem) => void;
}) {
  // Pagination: max 3 risk alert cards per tab; extra findings get their own tabs.
  const PAGE_SIZE = 3;
  const [page, setPage] = useState(0);
  const pageCount = Math.max(1, Math.ceil(findings.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const visible = findings.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE);
  const goPage = (p: number) => setPage(Math.max(0, Math.min(p, pageCount - 1)));

  // Reset to the first tab whenever a different shipment / finding set is shown,
  // so the pager never gets stuck on a page that no longer exists.
  useEffect(() => {
    setPage(0);
  }, [findings]);

  if (findings.length === 0) {
    return (
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-6 text-center">
        <p className="font-semibold text-emerald-700">PASSED — Không phát hiện lỗi</p>
        <p className="text-sm text-emerald-600">Bộ chứng từ nhất quán trên tất cả các quy tắc kiểm tra.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {pageCount > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white px-3 py-2 text-xs font-semibold text-slate-600 ring-1 ring-slate-200">
          <button
            onClick={() => goPage(safePage - 1)}
            disabled={safePage === 0}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Trang trước"
          >
            <ChevronLeft className="h-3.5 w-3.5" />
            Trang trước
          </button>
          <div className="flex items-center gap-1.5">
            {Array.from({ length: pageCount }, (_, i) => (
              <button
                key={i}
                onClick={() => goPage(i)}
                aria-label={`Di toi trang ${i + 1}`}
                aria-current={i === safePage ? "page" : undefined}
                className={`rounded-md px-2.5 py-1 font-mono text-[11px] ${
                  i === safePage
                    ? "bg-slate-900 text-white"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {i + 1}
              </button>
            ))}
          </div>
          <button
            onClick={() => goPage(safePage + 1)}
            disabled={safePage === pageCount - 1}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Trang sau"
          >
            Trang sau
            <ChevronRight className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {visible.map((item) => {
        const tone = toneForSeverity(item.severity);
        return (
          <article
            key={item.id}
            className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md"
          >
            <div className="mb-2 flex items-start justify-between gap-2">
              <StatusBadge label={item.severity} tone={tone} />
              <span className="rounded-md bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-600">
                {item.rule_id}
              </span>
            </div>
            <h4 className="text-sm font-semibold text-slate-900">{item.message}</h4>
            {item.reason && (
              <p className="mt-1 text-xs text-slate-600">{item.reason}</p>
            )}
            {(item.source_value || item.target_value) && (
              <div className="mt-2 grid grid-cols-1 gap-2 rounded-lg bg-slate-50 p-3 text-xs ring-1 ring-slate-200 sm:grid-cols-2">
                <div>
                  <p className="font-semibold text-slate-500">Nguồn</p>
                  <p className="font-medium text-slate-800">
                    {item.source_doc_type || "—"}: {item.source_value || "—"}
                  </p>
                </div>
                <div>
                  <p className="font-semibold text-slate-500">Đích</p>
                  <p className="font-medium text-slate-800">
                    {item.target_doc_type || "—"}: {item.target_value || "—"}
                  </p>
                </div>
              </div>
            )}
            {item.evidence_snippet && (
              <div className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 ring-1 ring-amber-200">
                <Quote className="mr-1 inline h-3.5 w-3.5" />
                {item.evidence_snippet}
              </div>
            )}
            {item.suggestion && (
              <p className="mt-2 rounded-md bg-blue-50 px-3 py-2 text-xs text-blue-800 ring-1 ring-blue-200">
                <span className="font-semibold">Gợi ý:</span> {item.suggestion}
              </p>
            )}
            <div className="mt-3 flex gap-2">
              <button
                onClick={() => onFocus(item.rule_id)}
                className="inline-flex items-center gap-1 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
              >
                Highlight <ChevronRight className="h-3.5 w-3.5" />
              </button>
              {item.evidence_snippet && (
                <button
                  onClick={() => onSnippet(item)}
                  className="inline-flex items-center gap-1 rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
                >
                  View snippet <ExternalLink className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          </article>
        );
      })}
    </div>
  );
}
