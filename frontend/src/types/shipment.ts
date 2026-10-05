export type ShipmentStatus = "PENDING" | "EXTRACTING" | "EXTRACTED" | "FAILED";
export type Verdict = "PASSED" | "WARNING" | "REJECTED" | "PENDING";
export type DocumentType = "COMMERCIAL_INVOICE" | "PACKING_LIST" | "BILL_OF_LADING" | "UNKNOWN";

export interface PartyInfo { name: string | null; address: string | null; }

export interface LineItem {
  item_no: number | null;
  description: string | null;
  batch: string | null;
  quantity: number | null;
  unit: string | null;
  net_weight_kg: number | null;
  gross_weight_kg: number | null;
  unit_price: number | null;
  total_amount: number | null;
}

export interface ContainerInfo {
  container_no: string | null;
  seal_no: string | null;
  container_type: string | null;
  packages: number | null;
  package_unit: string | null;
  net_weight_kg: number | null;
  gross_weight_kg: number | null;
  measurement_cbm: number | null;
}

export interface ExtractedData {
  doc_type: DocumentType;
  doc_number: string | null;
  reference_numbers: string[];
  issue_date: string | null;
  shipper: PartyInfo | null;
  consignee: PartyInfo | null;
  notify_party: PartyInfo | null;
  port_of_loading: string | null;
  port_of_discharge: string | null;
  place_of_delivery: string | null;
  vessel_voyage: string | null;
  total_packages: number | null;
  package_unit: string | null;
  total_net_weight_kg: number | null;
  total_gross_weight_kg: number | null;
  total_amount: number | null;
  currency: string | null;
  containers: ContainerInfo[];
  items: LineItem[];
  snippets: Record<string, string>;
}

export interface Document {
  id: string;
  file_name: string;
  file_type: string;
  detected_doc_type: DocumentType;
  status: string;
  raw_text: string | null;
  extracted_data: ExtractedData | null;
  created_at: string | null;
}

export interface ShipmentListRow {
  id: string;
  title: string;
  status: ShipmentStatus;
  created_at: string | null;
  updated_at: string | null;
  document_count: number;
  high_count: number;
  medium_count: number;
  verdict: Verdict;
}

export interface Shipment {
  id: string;
  title: string;
  status: ShipmentStatus;
  created_at: string | null;
  updated_at: string | null;
  documents: Document[];
  validation_results: ValidationRiskItem[];
}

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

export interface ReportResponse {
  shipment_id: string;
  status: ShipmentStatus;
  verdict: Verdict;
  findings: ValidationRiskItem[];
}
