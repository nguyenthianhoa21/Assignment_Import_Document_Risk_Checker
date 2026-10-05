# Import Document Risk Checker

AI-assisted system for reading and cross-checking import shipment documents
(Commercial Invoice, Packing List, Bill of Lading).

## Stack

| Layer    | Technology                                  |
| -------- | ------------------------------------------- |
| Backend  | Python 3.11, FastAPI, SQLAlchemy, Alembic   |
| Database | PostgreSQL 16 (SQLite fallback for local)   |
| AI       | Google Gemini (`gemini-2.0-flash`)          |
| Frontend | React 18, Vite                              |

## Repository layout

```
.
├── backend/            FastAPI application
│   ├── app/
│   │   ├── api/v1/     API routes (shipments, documents)
│   │   ├── models/     SQLAlchemy models (Shipment, Document, ValidationResult)
│   │   ├── schemas/    Pydantic schemas (extraction, validation, shipment)
│   │   ├── services/   pdf_parser, gemini_extractor, storage, validation_engine
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
# edit .env and set GEMINI_API_KEY
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
cp .env.example .env             # set GEMINI_API_KEY
alembic upgrade head             # or rely on create_all fallback
uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

The backend automatically falls back to SQLite when PostgreSQL is not
reachable, so the project runs locally without any external service. Set
`DATABASE_URL` to a PostgreSQL DSN to use the production database.

## Environment variables

See `.env.example`. Never commit real secrets.

| Variable            | Purpose                                |
| ------------------- | -------------------------------------- |
| `DATABASE_URL`      | SQLAlchemy DSN (PostgreSQL or SQLite)  |
| `GEMINI_API_KEY`    | Google Generative AI key               |
| `GEMINI_MODEL`      | Gemini model (default gemini-2.0-flash)|
| `GEMINI_RPM_LIMIT`  | Gemini free-tier RPM guard (default 15)|
| `CORS_ORIGINS`      | Allowed frontend origins               |
| `UPLOAD_DIR`        | Uploaded files directory               |
| `VITE_API_BASE`     | Frontend API base URL                  |

## API

- `GET /`, `GET /health`, `GET /health/db` — probes
- `POST /api/v1/shipments/upload` — create shipment + upload files + trigger extraction
- `GET /api/v1/shipments/{id}` — shipment detail with extraction and findings
- `GET /api/v1/documents/{id}` — single document extraction

## Status

Backend extraction + cross-document validation implemented (mocked Gemini in
tests). Frontend wiring and richer UI in later steps.
