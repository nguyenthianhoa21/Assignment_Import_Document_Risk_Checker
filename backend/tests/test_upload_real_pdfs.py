"""Upload the 3 real sample PDFs through the API with the AI layer mocked."""
from unittest.mock import patch
import io, pathlib, sys, time

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.database import engine
from app.models.shipment import Base
Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

from fastapi.testclient import TestClient
from app.main import app
from app.services import openrouter_extractor, extraction_offline
from app.services.pdf_parser import extract_text

SAMPLE = BACKEND.parent / "Sample"

def fake_extract(file_path: str, raw_text: str):
    """Use the offline parser so no network call is made."""
    return extraction_offline.extract_document_offline(raw_text, file_path)

with patch.object(openrouter_extractor, "extract_document_sync", new=fake_extract):
    client = TestClient(app)
    files = []
    for name in ("Sample_Commercial_Invoice.pdf", "Sample_Packing_List.pdf", "Sample_Bill_of_Lading.pdf"):
        data = (SAMPLE / name).read_bytes()
        files.append(("files", (name, io.BytesIO(data), "application/pdf")))
    resp = client.post("/api/v1/shipments/upload", data={"title": "Sample shipment"}, files=files)
    print("upload status:", resp.status_code)
    body = resp.json()
    print("documents in response:", len(body["documents"]))
    for d in body["documents"]:
        print("   -", d["file_name"])
    sid = body["shipment_id"]

    for _ in range(30):
        detail = client.get(f"/api/v1/shipments/{sid}").json()
        if detail["status"] not in ("EXTRACTING", "PENDING"):
            break
        time.sleep(0.2)

    print("shipment status:", detail["status"])
    for d in detail["documents"]:
        print("   doc:", d["detected_doc_type"], d["status"])
    report = client.get(f"/api/v1/shipments/{sid}/report").json()
    print("verdict:", report["verdict"], "findings:", len(report["findings"]))
    for f in report["findings"]:
        print(f"   {f['severity']:<8} {f['rule_id']:<34} {f['message'][:95]}")
