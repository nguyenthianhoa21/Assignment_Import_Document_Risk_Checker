"""Mocked end-to-end pipeline test (files uploaded, extraction + validation run)."""

from unittest.mock import patch

from app.database import SessionLocal, engine
from app.main import app
from app.schemas.extraction import DocumentType, ExtractedDocument
from app.services import gemini_extractor
from app.models.shipment import Base

Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

from fastapi.testclient import TestClient

client = TestClient(app)


def fake_extract_document_sync(path: str, raw_text: str) -> ExtractedDocument:
    path = path.lower()
    if "invoice" in path:
        return ExtractedDocument(
            doc_type=DocumentType.COMMERCIAL_INVOICE,
            doc_number="IV-2026-1008",
            total_gross_weight_kg=231000,
            total_net_weight_kg=220000,
        )
    if "packing" in path:
        return ExtractedDocument(
            doc_type=DocumentType.PACKING_LIST,
            doc_number="IV-2026-100B",
            reference_numbers=["IV-2026-100B"],
            total_gross_weight_kg=232000,
            total_net_weight_kg=220000,
        )
    return ExtractedDocument(
        doc_type=DocumentType.BILL_OF_LADING,
        doc_number="OBSLQDHCM2609187",
        reference_numbers=["QDO26091288"],
        total_gross_weight_kg=232000,
    )


with patch.object(
    gemini_extractor, "extract_document_sync", new=fake_extract_document_sync
):
    import io

    payload = {"title": "Test lot"}
    files = [
        ("files", ("Sample_Commercial_Invoice.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")),
        ("files", ("Sample_Packing_List.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")),
        ("files", ("Sample_Bill_of_Lading.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")),
    ]
    resp = client.post("/api/v1/shipments/upload", data=payload, files=files)
    print("upload:", resp.status_code, resp.json()["shipment_id"])
    shipment_id = resp.json()["shipment_id"]

    import time
    for _ in range(20):
        detail = client.get(f"/api/v1/shipments/{shipment_id}").json()
        if detail["status"] != "EXTRACTING":
            break
        time.sleep(0.2)

    print("status:", detail["status"])
    for d in detail["documents"]:
        print(" doc:", d["detected_doc_type"], d["status"])
    print("findings:", len(detail["validation_results"]))
    for v in detail["validation_results"]:
        print("  -", v["severity"], v["rule_id"])
