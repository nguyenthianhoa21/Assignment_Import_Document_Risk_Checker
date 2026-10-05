# Backend — Import Document Risk Checker (developer guide)

Technical stack: **Python 3.11, FastAPI, SQLAlchemy, Alembic, Pydantic v2, PostgreSQL, Google Gemini**.

## 1. Architecture — Hybrid Extraction pipeline

`uploads/{shipment_id}/` → PDF/Image → **Step A: Offline OCR (`pdfplumber`)** → text length?

- **Text present (≥ 50 characters):** send the extracted text directly to Gemini with a compact text-in prompt.
- **Empty / scanned image:** send the raw bytes as multimodal inline data to Gemini Vision (VLM branch) with a `responseSchema = ExtractedDocument`.

Gemini returns a strict `JSONB` payload validated through the `ExtractedDocument` Pydantic schema (`snippets` keeps the verbatim evidence per field). The result is persisted on `documents.extracted_data`. Once every document of a shipment has been extracted, `validation_engine.run_validations` runs the cross-document rules and writes `validation_results` (with `evidence_snippet` so the UI can highlight the exact line).

Example values backed by the real samples:

- Invoice No. `IV-2026-1008` (CI) vs Reference `IV-2026-100B` (PL) — a single-character `8↔B` typo detected by `RULE_INVOICE_REF_MATCH`.
- Gross Weight `231,000 KG` (CI) vs `232,000 KG` (BL/PL) — detected by `RULE_GROSS_WEIGHT_MATCH`.
- Container `OOLU7654327` (BL) vs `OOLU7654321` (PL) — detected by `RULE_CONTAINER_SEAL_MATCH`.

## 2. Business Analysis Matrix

### 2.1 Fields collected per document

| Field                      | CI | PL | BL |
| -------------------------- | -- | -- | -- |
| Document number            | ●  | ●  | ●  |
| Reference numbers          | —  | ●  | ●  |
| Issue / shipped-on-board date | ● | ● | ● |
| Shipper / Consignee / Notify party | ● | ● | ● |
| Port of loading / discharge / place of delivery | ● | ● | ● |
| Vessel / voyage            | —  | —  | ●  |
| Line items (batch/qty/weights) | ● | ● | — |
| Containers / seals         | —  | ●  | ●  |
| Totals (packages, net/gross kg, amount/currency) | ● | ● | ● |
| Verbatim `snippets` per field  | ● | ● | ● |

### 2.2 Validation Rules Matrix

| Rule ID | Compared fields | Condition | Severity | Sample outcome |
| ------- | --------------- | --------- | -------- | -------------- |
| `RULE_INVOICE_REF_MATCH` | CI.doc_number ↔ PL.references/doc_number | Must be equal | `HIGH` | `IV-2026-1008` ≠ `IV-2026-100B` → flagged |
| `RULE_GROSS_WEIGHT_MATCH` | Total gross kg across CI/PL/BL | Within 0.5 kg | `HIGH` | `231,000` ≠ `232,000` → flagged |
| `RULE_NET_WEIGHT_INTERNAL` | Sum(item.net_weight_kg) ↔ total_net_weight_kg | Within 0.5 kg | `MEDIUM` | If broken → flagged |
| `RULE_CONTAINER_SEAL_MATCH` | Container + seal sets PL ↔ BL | Exact set | `HIGH` | `OOLU7654327` ≠ `…4321` → flagged |
| `RULE_CONSIGNEE_NAME_SIMILARITY` | Consignee.name pairwise | Ratio ≥ 0.85 | `MEDIUM` | `GREENFIELD FOOD …` ≠ `… FOODS … LIMITED` → flagged |
| `RULE_PLACE_OF_DELIVERY_TYPO` | `CAT LAL` substring | Must not occur | `LOW` | Typo `CAT LAL` → flagged |

## 3. Fresh installation

```powershell
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
# Edit .env and set GEMINI_API_KEY to a real Google Generative AI key.
```

Never commit `.env`.

## 4. Database — PostgreSQL + Alembic

```powershell
# Start a PostgreSQL service (example: once-off Docker)
docker run --name import-risk-pg -e POSTGRES_USER=risk_user -e POSTGRES_PASSWORD=risk_pass -e POSTGRES_DB=risk_checker -p 5432:5432 -d postgres:16

# Windows PG client (already installed) is enough:
createdb -h localhost -U risk_user risk_checker
alembic upgrade head  # Tabula rasa: Base.metadata.create_all also works when Alembic is not available
```

On dev without PostgreSQL the backend falls back to `risk_checker_fallback.db` (SQLite) automatically.

## 5. Run the API server

```powershell
cd backend
.venv\Scripts\activate
uvicorn app.main:app --reload --port 8000
# Docs: http://localhost:8000/docs
```

## 6. Endpoints

| Method | Path | Purpose |
| ------ | ---- | ------- |
| `POST` | `/api/v1/shipments/upload` | Create a shipment and upload files, trigger background extraction |
| `GET`  | `/api/v1/shipments/{id}` | Retrieve shipment, documents and validation findings |
| `GET`  | `/api/v1/documents/{id}` | Retrieve one extracted document |
| `GET`  | `/health`, `/health/db` | Liveness and readiness probes |

## 7. Testing — `curl` examples

```powershell
# Upload the three provided samples as a single shipment
curl.exe -X POST http://localhost:8000/api/v1/shipments/upload `
  -F "title=Lot 2609 QDO26091288" `
  -F "files=@../Sample/Sample_Commercial_Invoice.pdf" `
  -F "files=@../Sample/Sample_Packing_List.pdf" `
  -F "files=@../Sample/Sample_Bill_of_Lading.pdf"

# Response contains the shipment id, e.g. { "shipment_id": "..." }

# Fetch the full result (JSONB per document + cross-document findings)
$shipmentId = "<shipment-id-from-previous-response>"
curl.exe http://localhost:8000/api/v1/shipments/$shipmentId | ConvertFrom-Json
