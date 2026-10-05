import { useEffect, useMemo, useRef } from "react";
import type { ExtractedData, ValidationRiskItem } from "../../types/shipment";
import { toneForSeverity } from "../common/StatusBadge";

const MISSING = "_";

const DOC_COLUMNS = [
  { type: "COMMERCIAL_INVOICE", label: "Commercial Invoice" },
  { type: "PACKING_LIST", label: "Packing List" },
  { type: "BILL_OF_LADING", label: "Bill of Lading" },
] as const;

/** Maps each validation rule to the matrix cells it relates to. */
const RULE_CELLS: Record<string, string[]> = {
  RULE_INVOICE_REF_MATCH: ["COMMERCIAL_INVOICE:doc_number", "PACKING_LIST:references"],
  RULE_GROSS_WEIGHT_MATCH: [
    "COMMERCIAL_INVOICE:total_gross_weight_kg",
    "PACKING_LIST:total_gross_weight_kg",
    "BILL_OF_LADING:total_gross_weight_kg",
  ],
  RULE_NET_WEIGHT_MATCH: ["COMMERCIAL_INVOICE:total_net_weight_kg", "PACKING_LIST:total_net_weight_kg"],
  RULE_NET_WEIGHT_INTERNAL: ["COMMERCIAL_INVOICE:total_net_weight_kg", "PACKING_LIST:total_net_weight_kg"],
  RULE_TOTAL_PACKAGES_MATCH: [
    "COMMERCIAL_INVOICE:total_packages",
    "PACKING_LIST:total_packages",
    "BILL_OF_LADING:total_packages",
  ],
  RULE_GROSS_WEIGHT_PER_CONTAINER: [
    "COMMERCIAL_INVOICE:containers",
    "PACKING_LIST:containers",
    "BILL_OF_LADING:containers",
  ],
  RULE_CONTAINER_SEAL_MATCH: [
    "COMMERCIAL_INVOICE:containers",
    "PACKING_LIST:containers",
    "BILL_OF_LADING:containers",
  ],
  RULE_CONSIGNEE_NAME_SIMILARITY: [
    "COMMERCIAL_INVOICE:consignee_name",
    "PACKING_LIST:consignee_name",
    "BILL_OF_LADING:consignee_name",
  ],
  RULE_ADDRESS_SIMILARITY: ["COMMERCIAL_INVOICE:consignee_address", "PACKING_LIST:consignee_address"],
  RULE_PLACE_OF_DELIVERY_TYPO: [
    "COMMERCIAL_INVOICE:port_of_discharge",
    "BILL_OF_LADING:place_of_delivery",
  ],
  RULE_PORT_CONSISTENCY: ["COMMERCIAL_INVOICE:port_of_loading", "BILL_OF_LADING:port_of_loading"],
  RULE_DATE_CHRONOLOGY: [
    "COMMERCIAL_INVOICE:issue_date",
    "PACKING_LIST:issue_date",
    "BILL_OF_LADING:issue_date",
  ],
  // Legacy shorthands kept so old findings with field_name="containers" still highlight.
  RULE_MISSING_DOCUMENT: [],
};

const GROUPS = [
  {
    name: "General Info",
    rows: [
      { key: "doc_number", label: "Document No." },
      { key: "references", label: "Reference No." },
      { key: "issue_date", label: "Issue Date" },
    ],
  },
  {
    name: "Parties",
    rows: [
      { key: "shipper_name", label: "Shipper" },
      { key: "consignee_name", label: "Consignee" },
      { key: "consignee_address", label: "Consignee Address" },
    ],
  },
  {
    name: "Port & Logistics",
    rows: [
      { key: "port_of_loading", label: "Port of Loading" },
      { key: "port_of_discharge", label: "Port of Discharge" },
      { key: "place_of_delivery", label: "Place of Delivery" },
      { key: "vessel_voyage", label: "Vessel / Voyage" },
    ],
  },
  {
    name: "Weights & Quantities",
    rows: [
      { key: "total_packages", label: "Total Packages" },
      { key: "total_net_weight_kg", label: "Total Net Weight (KG)" },
      { key: "total_gross_weight_kg", label: "Total Gross Weight (KG)" },
      { key: "total_amount", label: "Total Amount" },
    ],
  },
];

function cellValue(data: ExtractedData | null, key: string): string {
  if (!data) return MISSING;
  const fmt = (n: number | null | undefined, suffix = "") =>
    n === null || n === undefined ? MISSING : `${n.toLocaleString("en-US")}${suffix}`;

  switch (key) {
    case "doc_number":
      return data.doc_number || MISSING;
    case "references":
      return data.reference_numbers?.length ? data.reference_numbers.join(", ") : MISSING;
    case "issue_date":
      return data.issue_date || MISSING;
    case "shipper_name":
      return data.shipper?.name || MISSING;
    case "consignee_name":
      return data.consignee?.name || MISSING;
    case "consignee_address":
      return data.consignee?.address || MISSING;
    case "port_of_loading":
      return data.port_of_loading || MISSING;
    case "port_of_discharge":
      return data.port_of_discharge || MISSING;
    case "place_of_delivery":
      return data.place_of_delivery || MISSING;
    case "vessel_voyage":
      return data.vessel_voyage || MISSING;
    case "total_packages":
      return fmt(data.total_packages, data.package_unit ? ` ${data.package_unit}` : "");
    case "total_net_weight_kg":
      return fmt(data.total_net_weight_kg);
    case "total_gross_weight_kg":
      return fmt(data.total_gross_weight_kg);
    case "total_amount":
      return data.total_amount === null || data.total_amount === undefined
        ? MISSING
        : `${data.total_amount.toLocaleString("en-US")} ${data.currency || ""}`.trim();
    default:
      return MISSING;
  }
}

export default function SideBySideViewer({
  documents,
  findings,
  focusRuleId,
}: {
  documents: { detected_doc_type: string; extracted_data: ExtractedData | null }[];
  findings: ValidationRiskItem[];
  focusRuleId: string | null;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  const byType = useMemo(() => {
    const map: Record<string, ExtractedData | null> = {};
    documents.forEach((d) => {
      map[d.detected_doc_type] = d.extracted_data;
    });
    return map;
  }, [documents]);

  // Build a cellId -> {severity, ruleId} map.
  // Legacy findings used field_name="containers" (no prefix); expand so old data still highlights.
  const flaggedCells = useMemo(() => {
    const map: Record<string, { severity: string; ruleId: string }> = {};
    const expandCell = (cellId: string): string[] => {
      if (cellId === "containers") {
        return DOC_COLUMNS.map((c) => `${c.type}:containers`);
      }
      return [cellId];
    };
    findings.forEach((f) => {
      const raw = RULE_CELLS[f.rule_id];
      // Use the canonical mapping, but also honour the finding's own field_name
      // as a fallback so misaligned field names still highlight something.
      const cellIds: string[] =
        raw && raw.length > 0
          ? raw.flatMap(expandCell)
          : f.field_name
            ? expandCell(f.field_name).flatMap((c) => (c.includes(":") ? [c] : DOC_COLUMNS.map((d) => `${d.type}:${c}`)))
            : [];
      cellIds.forEach((cellId) => {
        const existing = map[cellId];
        // HIGH/CRITICAL overrides lower severities so the most serious tone wins.
        const rank = (s: string) => (["CRITICAL", "HIGH"].includes(s.toUpperCase()) ? 3 : s.toUpperCase() === "MEDIUM" ? 2 : 1);
        if (!existing || rank(f.severity) > rank(existing.severity)) {
          map[cellId] = { severity: f.severity, ruleId: f.rule_id };
        }
      });
    });
    return map;
  }, [findings]);

  // Scroll to and flash the first cell belonging to the focused rule.
  useEffect(() => {
    if (!focusRuleId) return;
    const targets = RULE_CELLS[focusRuleId] || [];
    const first = targets[0];
    if (!first) return;
    const el = containerRef.current?.querySelector<HTMLElement>(`[data-cell="${first}"]`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [focusRuleId]);

  const highlightClass = (cellId: string) => {
    const hit = flaggedCells[cellId];
    if (!hit) return "px-3 py-2 align-top text-sm text-slate-700";
    const rawTone = toneForSeverity(hit.severity);
    // Validation uses INFO for chronology, but `toneForSeverity("INFO")` is
    // "neutral" (badge style). In the matrix we still want a visible highlight
    // for INFO findings, so treat neutral as info (sky tint).
    const tone = rawTone === "neutral" ? "info" : rawTone;
    let cls = "px-3 py-2 align-top text-sm text-slate-700";
    if (tone === "danger") cls += " bg-red-50 ring-2 ring-inset ring-red-400";
    else if (tone === "warning") cls += " bg-amber-50 ring-2 ring-inset ring-amber-300";
    else if (tone === "info") cls += " bg-sky-50 ring-2 ring-inset ring-sky-300";
    if (hit.ruleId === focusRuleId) cls += " animate-pulse-ring";
    return cls;
  };

  return (
    <div ref={containerRef} className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full divide-y divide-slate-200 text-left">
        <thead className="bg-slate-50">
          <tr>
            <th className="w-56 px-4 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Field
            </th>
            {DOC_COLUMNS.map((col) => (
              <th key={col.type} className="px-3 py-3 text-xs font-semibold uppercase tracking-wide text-slate-500">
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {GROUPS.map((group) => (
            <>
              <tr key={`g-${group.name}`} className="bg-slate-100/70">
                <td colSpan={4} className="px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-600">
                  {group.name}
                </td>
              </tr>
              {group.rows.map((row) => (
                <tr key={`${group.name}-${row.key}`}>
                  <td className="px-4 py-2 text-sm font-medium text-slate-600">{row.label}</td>
                  {DOC_COLUMNS.map((col) => {
                    const cellId = `${col.type}:${row.key}`;
                    return (
                      <td key={cellId} data-cell={cellId} className={highlightClass(cellId)}>
                        {cellValue(byType[col.type] ?? null, row.key)}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </>
          ))}

          <tr className="bg-slate-100/70">
            <td colSpan={4} className="px-4 py-2 text-xs font-bold uppercase tracking-wide text-slate-600">
              Containers &amp; Seals
            </td>
          </tr>
          <tr>
            <td className="px-4 py-2 text-sm font-medium text-slate-600">Container / Seal list</td>
            {DOC_COLUMNS.map((col) => {
              const cellId = `${col.type}:containers`;
              const list = byType[col.type]?.containers ?? [];
              return (
                <td key={cellId} data-cell={cellId} className={highlightClass(cellId)}>
                  {list.length === 0 ? (
                    MISSING
                  ) : (
                    <ul className="space-y-1">
                      {list.map((c, i) => (
                        <li key={`${c.container_no}-${i}`} className="font-mono text-[13px]">
                          {c.container_no || MISSING}
                          <span className="text-slate-500"> / {c.seal_no || MISSING}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              );
            })}
          </tr>
          <tr>
            <td className="px-4 py-2 text-sm font-medium text-slate-600">Line Items</td>
            {DOC_COLUMNS.map((col) => {
              const items = byType[col.type]?.items ?? [];
              return (
                <td key={`${col.type}-items`} className="px-3 py-2 align-top text-sm text-slate-700">
                  {items.length === 0 ? (
                    MISSING
                  ) : (
                    <ul className="space-y-1">
                      {items.map((it, i) => (
                        <li key={i} className="text-[13px]">
                          <span className="font-medium">{it.description || it.batch || "Item"}</span>
                          <span className="block text-xs text-slate-500">
                            {it.quantity ?? MISSING} {it.unit || ""} · net {it.net_weight_kg?.toLocaleString() ?? MISSING} kg
                          </span>
                        </li>
                      ))}
                    </ul>
                  )}
                </td>
              );
            })}
          </tr>
        </tbody>
      </table>
    </div>
  );
}


