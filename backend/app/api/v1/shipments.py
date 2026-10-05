import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.document import Document, DocumentType
from app.models.shipment import DocumentStatus, Shipment, ShipmentStatus
from app.models.validation import Severity, ValidationResult
from app.schemas.extraction import ExtractedDocument
from app.schemas.shipment import DocumentOut, ShipmentListOut, ShipmentOut, UploadResponse
from app.services import gemini_extractor, pdf_parser, storage, validation_engine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/shipments", tags=["shipments"])

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/tiff": "tiff",
    "image/webp": "webp",
}


@router.get("", response_model=list[ShipmentListOut])
def list_shipments(db: Session = Depends(get_db), limit: int = 50) -> list[ShipmentListOut]:
    """Dashboard history: one row per shipment with risk counters."""
    limit = min(max(limit, 1), 200)
    rows = (
        db.query(Shipment)
        .order_by(Shipment.created_at.desc())
        .limit(limit)
        .all()
    )
    out: list[ShipmentListOut] = []
    for shipment in rows:
        docs = db.query(Document).filter(Document.shipment_id == shipment.id).all()
        findings = (
            db.query(ValidationResult)
            .filter(ValidationResult.shipment_id == shipment.id)
            .all()
        )
        high = sum(1 for f in findings if f.severity in (Severity.CRITICAL, Severity.HIGH))
        medium = sum(1 for f in findings if f.severity is Severity.MEDIUM)
        if high:
            verdict = "REJECTED"
        elif medium:
            verdict = "WARNING"
        elif findings:
            verdict = "PASSED"
        else:
            verdict = "PENDING"
        out.append(
            ShipmentListOut(
                id=shipment.id,
                title=shipment.title,
                status=shipment.status.value,
                created_at=shipment.created_at,
                updated_at=shipment.updated_at,
                document_count=len(docs),
                high_count=high,
                medium_count=medium,
                verdict=verdict,
            )
        )
    return out


@router.post("/upload", response_model=UploadResponse, status_code=201)
async def upload_shipment(
    title: str = Form(...),
    files: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = None,  # type: ignore[assignment]
    db: Session = Depends(get_db),
) -> UploadResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    shipment = Shipment(title=title, status=ShipmentStatus.PENDING)
    db.add(shipment)
    db.flush()

    created: list[Document] = []
    for upload in files:
        content_type = (upload.content_type or "").lower()
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"Unsupported content type {content_type!r} for {upload.filename!r}",
            )
        content = await upload.read()
        if not content:
            raise HTTPException(
                status_code=400, detail=f"Empty file: {upload.filename!r}"
            )

        file_path = storage.save_upload(
            shipment.id, upload.filename or "file", content
        )
        document = Document(
            shipment_id=shipment.id,
            file_name=upload.filename or "file",
            file_path=file_path,
            file_type=ALLOWED_TYPES[content_type],
            status=DocumentStatus.UPLOADED,
        )
        db.add(document)
        created.append(document)

    db.commit()
    for document in created:
        db.refresh(document)

    if background_tasks is not None:
        background_tasks.add_task(run_extraction_pipeline, str(shipment.id))

    return UploadResponse(
        shipment_id=shipment.id,
        title=shipment.title,
        status=shipment.status.value,
        documents=[DocumentOut.model_validate(document) for document in created],
    )


@router.get("/{shipment_id}", response_model=ShipmentOut)
def get_shipment(shipment_id: uuid.UUID, db: Session = Depends(get_db)) -> Shipment:
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return shipment


@router.get("/{shipment_id}/report")
def get_validation_report(shipment_id: uuid.UUID, db: Session = Depends(get_db)) -> dict:
    """Compact risk report used by the dashboard and detail pages."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(status_code=404, detail="Shipment not found")
    rows = (
        db.query(ValidationResult)
        .filter(ValidationResult.shipment_id == shipment.id)
        .all()
    )
    verdict = "PASSED"
    if any(r.severity in (Severity.CRITICAL, Severity.HIGH) for r in rows):
        verdict = "REJECTED"
    elif any(r.severity is Severity.MEDIUM for r in rows):
        verdict = "WARNING"
    return {
        "shipment_id": str(shipment.id),
        "status": shipment.status.value,
        "verdict": verdict,
        "findings": [
            {
                "id": str(r.id),
                "rule_id": r.rule_id,
                "severity": r.severity.value,
                "risk_level": r.risk_level,
                "field_name": r.field_name,
                "message": r.message,
                "reason": r.reason,
                "suggestion": r.suggestion,
                "source_doc_type": r.source_doc_type,
                "target_doc_type": r.target_doc_type,
                "source_value": r.source_value,
                "target_value": r.target_value,
                "evidence_snippet": r.evidence_snippet,
            }
            for r in rows
        ],
    }


def run_extraction_pipeline(shipment_id: str) -> None:
    """Parse, extract, then cross-validate every document of a shipment.

    Runs in the background after upload. Uses its own DB session so it is
    safe from the request thread.
    """
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        shipment = db.get(Shipment, uuid.UUID(shipment_id))
        if shipment is None:
            return
        shipment.status = ShipmentStatus.EXTRACTING
        db.commit()

        documents = (
            db.query(Document).filter(Document.shipment_id == shipment.id).all()
        )
        extracted: dict[str, ExtractedDocument] = {}

        for document in documents:
            document.status = DocumentStatus.EXTRACTING
            db.commit()
            try:
                raw_text = pdf_parser.extract_text(document.file_path)
                document.raw_text = raw_text or None
                result = gemini_extractor.extract_document_sync(
                    document.file_path, raw_text
                )
                document.detected_doc_type = DocumentType(result.doc_type.value)
                document.extracted_data = result.model_dump(mode="json")
                document.status = DocumentStatus.COMPLETED
                db.commit()
                extracted[result.doc_type.value] = result
            except Exception:  # noqa: BLE001
                logger.exception("Extraction failed for document %s", document.id)
                document.status = DocumentStatus.FAILED
                db.commit()

        for finding in validation_engine.run_validations(extracted):
            db.add(ValidationResult(shipment_id=shipment.id, **finding))

        shipment.status = ShipmentStatus.EXTRACTED
        db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("Pipeline failed for shipment %s", shipment_id)
        try:
            shipment = db.get(Shipment, uuid.UUID(shipment_id))
            if shipment is not None:
                shipment.status = ShipmentStatus.FAILED
                db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
    finally:
        db.close()
