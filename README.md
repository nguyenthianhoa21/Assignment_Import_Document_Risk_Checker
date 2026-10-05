# Import Document Risk Checker

AI-assisted system for reading and cross-checking import shipment documents
(Commercial Invoice, Packing List, Bill of Lading).

## Stack

| Layer    | Technology                                  |
| -------- | ------------------------------------------- |
| Backend  | Python 3.11, FastAPI, SQLAlchemy, Alembic   |
| Database | PostgreSQL 16 (SQLite fallback for local)   |
| AI       | OpenRouter (`qwen/qwen3.8-27b:free`) for extraction + offline deterministic parser |
| AI (validation) | BGE-M3 (`BAAI/bge-m3`, local/offline, strict string matching) |
| Frontend | React 18, Vite                              |

## Repository layout

```
.
├── backend/            FastAPI application
│   ├── app/
│   │   ├── api/v1/     API routes (shipments, documents)
│   │   ├── models/     SQLAlchemy models (Shipment, Document, ValidationResult)
│   │   ├── schemas/    Pydantic schemas (extraction, validation, shipment)
│   │   ├── services/   pdf_parser, openrouter_extractor, extraction_offline, storage, validation_engine, bge_matcher
│   │   ├── config.py   Pydantic settings
│   │   ├── database.py Engine / session
│   │   └── main.py     FastAPI app
│   ├── alembic/        Migrations
│   ├── uploads/        Uploaded documents (git-ignored)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/           React (Vite) application (scaffold)
├── docker-compose.yml  Full stack orchestration
├── .env.example        Environment template
└── README.md
```

## Quick start (Docker)

```bash
cp .env.example .env
# edit .env and set OPENROUTER_API_KEY
docker compose up --build
```

- Backend: http://localhost:8000 (docs at /docs)
- Frontend: http://localhost:5173

## Quick start (local, no Docker)

Backend:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # set OPENROUTER_API_KEY
alembic upgrade head             # or rely on create_all fallback
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The system uses the open-weights model `qwen/qwen3.8-27b:free` through the
OpenRouter API as the primary AI extractor, combined with the offline
deterministic parser for high availability: if OpenRouter times out (>15s),
returns a non-200 status, or produces unparseable JSON, the pipeline
automatically falls back to `extract_document_offline()` so extraction
never stalls.

The backend automatically falls back to SQLite when PostgreSQL is not
reachable, so the project runs locally without any external service. Set
`DATABASE_URL` to a PostgreSQL DSN to use the production database.

## Environment variables

See `.env.example`. Never commit real secrets.

| Variable            | Purpose                                |
| ------------------- | -------------------------------------- |
| `DATABASE_URL`      | SQLAlchemy DSN (PostgreSQL or SQLite)  |
| `OPENROUTER_API_KEY` | OpenRouter API key (free-tier Qwen) |
| `OPENROUTER_MODEL`   | OpenRouter model (qwen/qwen3.8-27b:free) |
| `OPENROUTER_BASE_URL` | OpenRouter chat-completions endpoint |
| `CORS_ORIGINS`      | Allowed frontend origins               |
| `UPLOAD_DIR`        | Uploaded files directory               |
| `BGE_MODEL_ENABLED` | Enable the local BGE-M3 matcher (set `false` on low-memory hosts) |
| `BGE_MODEL_NAME` | BGE-M3 weights id (`BAAI/bge-m3`, ~2.2 GB, cached locally) |
| `BGE_SIMILARITY_THRESHOLD` | Cosine threshold on top of zero lexical drift (0.995) |
| `OPENROUTER_TOTAL_BUDGET_SECONDS` | Per-shipment AI budget before offline fallback |
| `VITE_API_BASE`     | Frontend API base URL                  |

## API

- `GET /`, `GET /health`, `GET /health/db` — probes
- `POST /api/v1/shipments/upload` — create shipment + upload files + trigger extraction
- `GET /api/v1/shipments/{id}` — shipment detail with extraction and findings
- `GET /api/v1/documents/{id}` — single document extraction

## Cross-Document Validation Rules

Deterministic engine (pure Python, no LLM hallucination) compares the three
documents and emits findings with `severity`, `risk_level`, `reason`,
`suggestion` and `evidence_snippet`:

| Rule ID | Compared fields | Severity |
| ------- | --------------- | -------- |
| `RULE_INVOICE_REF_MATCH` | CI invoice no ↔ PL reference | HIGH |
| `RULE_GROSS_WEIGHT_MATCH` | Total gross kg CI/PL/BL | HIGH |
| `RULE_NET_WEIGHT_INTERNAL` | Line-item net sum ↔ total net | MEDIUM |
| `RULE_NET_WEIGHT_MATCH` | CI total net ↔ PL total net | MEDIUM |
| `RULE_TOTAL_PACKAGES_MATCH` | Total packages CI/PL/BL | MEDIUM |
| `RULE_GROSS_WEIGHT_PER_CONTAINER` | Per-container gross PL ↔ BL | MEDIUM |
| `RULE_CONTAINER_SEAL_MATCH` | Container + seal sets PL ↔ BL | HIGH |
| `RULE_CONSIGNEE_NAME_SIMILARITY` | Consignee core name (legal suffix ignored) | MEDIUM |
| `RULE_ADDRESS_SIMILARITY` | Consignee address CI ↔ PL | LOW |
| `RULE_PLACE_OF_DELIVERY_TYPO` | `CAT LAL` typo watch | LOW |
| `RULE_PORT_CONSISTENCY` | Port of loading CI ↔ BL | MEDIUM |
| `RULE_DATE_CHRONOLOGY` | Invoice/PL date vs B/L shipped-on-board | INFO |

## Local entity matching with BGE-M3

String rules for entity comparison run through a local, offline dense encoder
instead of a fuzzy-similarity heuristic, because customs and L/C practice
requires strict consistency: a single differing character or word
(`GREENFIELD FOOD` vs `GREENFIELD FOODS`, `CAT LAI` vs `CAT LAL`) must be
flagged, not smoothed over.

`backend/app/services/bge_matcher.py` exposes a lazily loaded singleton:

```python
BGEMatcher.compare(text1, text2) -> BGECompareResult(is_consistent, score, diff_tokens)
```

Four stages:

1. Fast path: identical strings return `score=1.0` with no diff.
2. Tokenize and clean: uppercase, strip punctuation, split into tokens (`[A-Z0-9]+`).
3. BGE-M3 encoding: cosine similarity between the two normalized embeddings.
4. Strict decision: `is_consistent = len(diff_tokens) == 0 and score >= 0.995`.

If `sentence-transformers`/`torch` are missing, the weights are not on disk, or
the host runs out of memory, the matcher degrades to the deterministic token
comparison and logs a warning, so the API keeps serving.

Dependencies added in `backend/requirements.txt`: `sentence-transformers`,
`torch` (CPU wheel index), `numpy`. No paid external API is used by this layer.

## Status

Backend extraction (OpenRouter AI-first with offline fallback) plus
cross-document validation (deterministic rules + local BGE-M3 matching) is
implemented and covered by tests (`pytest backend/tests`). The frontend shows
the side-by-side matrix, paginated risk alerts (3 per tab) and field
highlighting.