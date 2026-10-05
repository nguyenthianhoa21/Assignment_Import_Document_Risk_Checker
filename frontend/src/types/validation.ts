export type RiskSeverity = "CRITICAL" | "HIGH" | "MEDIUM" | "LOW" | "INFO";

export interface ValidationRiskItem {
  id: string;
  rule_id: string;
  severity: string;
  risk_level: string | null;
  field_name: string | null;
  message: string;
  reason: string | null;
  suggestion: string | null;
  source_doc_type: string | null;
  target_doc_type: string | null;
  source_value: string | null;
  target_value: string | null;
  evidence_snippet: string | null;
}

export interface ValidationReport {
  shipment_id: string;
  status: string;
  verdict: string;
  findings: ValidationRiskItem[];
}
