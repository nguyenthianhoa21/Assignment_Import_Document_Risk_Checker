import datetime
import uuid

from pydantic import BaseModel, Field

from app.schemas.extraction import DocumentType
from app.schemas.validation import ValidationResultOut


class DocumentOut(BaseModel):
    id: uuid.UUID
    file_name: str
    file_type: str
    detected_doc_type: DocumentType
    status: str
    raw_text: str | None = None
    extracted_data: dict | None = None
    created_at: datetime.datetime | None = None

    model_config = {"from_attributes": True}


class ShipmentOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    created_at: datetime.datetime | None = None
    updated_at: datetime.datetime | None = None
    documents: list[DocumentOut] = Field(default_factory=list)
    validation_results: list[ValidationResultOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    shipment_id: uuid.UUID
    title: str
    status: str
    documents: list[DocumentOut]
