import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, CheckCircle2, RefreshCw, ShieldAlert, TriangleAlert } from "lucide-react";
import { getShipmentDetail } from "../api/shipments";
import type { Shipment, ValidationRiskItem } from "../types/shipment";
import RiskOverviewCards from "../components/inspection/RiskOverviewCards";
import RiskAlertList from "../components/inspection/RiskAlertList";
import SideBySideViewer from "../components/inspection/SideBySideViewer";
import EvidenceModal from "../components/inspection/EvidenceModal";

function verdict(findings: ValidationRiskItem[]) {
  if (findings.some((f) => ["CRITICAL", "HIGH"].includes(f.severity.toUpperCase()))) {
    return { label: "REJECTED — High Inconsistencies Detected", tone: "danger" as const };
  }
  if (findings.some((f) => f.severity.toUpperCase() === "MEDIUM")) {
    return { label: "WARNING", tone: "warning" as const };
  }
  if (findings.length === 0) return { label: "PASSED", tone: "success" as const };
  return { label: "REVIEW", tone: "info" as const };
}

const TONE_STYLE: Record<string, string> = {
  danger: "bg-red-50 text-red-800 ring-red-300",
  warning: "bg-amber-50 text-amber-800 ring-amber-300",
  success: "bg-emerald-50 text-emerald-800 ring-emerald-300",
  info: "bg-sky-50 text-sky-800 ring-sky-300",
};

export default function ShipmentDetailPage() {
  const { id = "" } = useParams();
  const [shipment, setShipment] = useState<Shipment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focusRule, setFocusRule] = useState<string | null>(null);
  const [snippetItem, setSnippetItem] = useState<ValidationRiskItem | null>(null);

  const load = () => {
    getShipmentDetail(id)
      .then(setShipment)
      .catch((e) => setError(e.message));
  };

  useEffect(load, [id]);

  const findings = shipment?.validation_results ?? [];
  const v = useMemo(() => verdict(findings), [findings]);

  if (error) {
    return (
      <div className="rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-red-200">
        {error}
      </div>
    );
  }
  if (!shipment) {
    return (
      <div className="flex justify-center py-16">
        <span className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  const VerdictIcon =
    v.tone === "danger" ? ShieldAlert : v.tone === "warning" ? TriangleAlert : CheckCircle2;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Link to="/" className="rounded-md p-1.5 text-slate-500 hover:bg-slate-100">
            <ArrowLeft className="h-5 w-5" />
          </Link>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">{shipment.title}</h1>
            <p className="text-xs text-slate-500">
              {shipment.created_at ? new Date(shipment.created_at).toLocaleString() : ""} · {shipment.documents.length} chứng từ
            </p>
          </div>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 rounded-md bg-white px-3 py-2 text-xs font-semibold text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50"
        >
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </button>
      </div>

      <div className={`rounded-xl px-5 py-4 ring-1 ${TONE_STYLE[v.tone]}`}>
        <div className="flex items-center gap-2">
          <VerdictIcon className="h-5 w-5" />
          <p className="text-lg font-bold">{v.label}</p>
        </div>
      </div>

      <RiskOverviewCards findings={findings} />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[1.6fr_1fr]">
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            Cross-document comparison
          </h2>
          <SideBySideViewer
            documents={shipment.documents.map((d) => ({
              detected_doc_type: d.detected_doc_type,
              extracted_data: d.extracted_data,
            }))}
            findings={findings}
            focusRuleId={focusRule}
          />
        </div>
        <div className="space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Risk alerts</h2>
          <RiskAlertList findings={findings} onFocus={setFocusRule} onSnippet={setSnippetItem} />
        </div>
      </div>

      <EvidenceModal
        title={snippetItem?.rule_id || "Evidence"}
        snippet={snippetItem?.evidence_snippet || null}
        onClose={() => setSnippetItem(null)}
      />
    </div>
  );
}
