import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.shipment import Base


class Severity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shipment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("shipments.id", ondelete="CASCADE"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), index=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestion: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    shipment: Mapped["Shipment"] = relationship(back_populates="validation_results")  # noqa: F821
