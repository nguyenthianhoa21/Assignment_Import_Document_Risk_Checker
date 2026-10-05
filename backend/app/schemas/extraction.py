from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    COMMERCIAL_INVOICE = "COMMERCIAL_INVOICE"
    PACKING_LIST = "PACKING_LIST"
    BILL_OF_LADING = "BILL_OF_LADING"
    UNKNOWN = "UNKNOWN"


class PartyInfo(BaseModel):
    name: str | None = Field(default=None, description="Full legal entity name, verbatim")
    address: str | None = Field(default=None, description="Full address, verbatim")


class LineItem(BaseModel):
    item_no: int | None = None
    description: str | None = None
    batch: str | None = Field(default=None, description="Batch/lot code, verbatim")
    quantity: float | None = None
    unit: str | None = None
    net_weight_kg: float | None = None
    gross_weight_kg: float | None = None
    unit_price: float | None = None
    total_amount: float | None = None


class ContainerInfo(BaseModel):
    container_no: str | None = Field(default=None, description="Container number, verbatim. Never correct typos.")
    seal_no: str | None = Field(default=None, description="Seal number, verbatim")
    container_type: str | None = None
    packages: float | None = None
    package_unit: str | None = None
    net_weight_kg: float | None = None
    gross_weight_kg: float | None = None
    measurement_cbm: float | None = None


class ExtractedDocument(BaseModel):
    """Structured extraction output from the AI provider (OpenRouter / offline fallback)."""

    doc_type: DocumentType
    doc_number: str | None = Field(
        default=None,
        description="Primary document number: invoice no, B/L no, packing list reference",
    )
    reference_numbers: list[str] = Field(
        default_factory=list,
        description="All other reference numbers on the document "
        "(e.g. invoice ref on PL, booking no on BL)",
    )
    issue_date: str | None = None
    shipper: PartyInfo | None = None
    consignee: PartyInfo | None = None
    notify_party: PartyInfo | None = None
    port_of_loading: str | None = None
    port_of_discharge: str | None = None
    place_of_delivery: str | None = None
    vessel_voyage: str | None = None
    total_packages: float | None = None
    package_unit: str | None = None
    total_net_weight_kg: float | None = None
    total_gross_weight_kg: float | None = None
    total_amount: float | None = None
    currency: str | None = None
    containers: list[ContainerInfo] = Field(default_factory=list)
    items: list[LineItem] = Field(default_factory=list)
    snippets: dict[str, str] = Field(
        default_factory=dict,
        description="Verbatim source excerpts for key fields "
        "(invoice_no, gross_weight, container_no, ...) used as UI evidence",
    )

