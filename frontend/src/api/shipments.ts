import { api } from "./client";
import type { ReportResponse, Shipment, ShipmentListRow } from "../types/shipment";

export type UploadProgress = {
  phase: "upload" | "extracting" | "done" | "error";
  message: string;
};

export async function listShipments(limit = 100): Promise<ShipmentListRow[]> {
  const { data } = await api.get<ShipmentListRow[]>("/shipments", {
    params: { limit },
  });
  return data;
}

export async function getShipmentDetail(id: string): Promise<Shipment> {
  const { data } = await api.get<Shipment>(`/shipments/${id}`);
  return data;
}

export async function getReport(id: string): Promise<ReportResponse> {
  const { data } = await api.get<ReportResponse>(`/shipments/${id}/report`);
  return data;
}

export async function uploadShipment(
  formData: FormData
): Promise<{ shipment_id: string; title: string; status: string }> {
  const { data } = await api.post("/shipments/upload", formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}
