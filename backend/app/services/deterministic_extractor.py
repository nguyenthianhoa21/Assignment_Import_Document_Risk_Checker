from __future__ import annotations

"""Deterministic (regex) extraction used as a safety net.

Gemini is the primary extractor, but a quota outage, a schema drift or a
network error must never silently produce an empty document set, because an
empty set validates to a false PASSED verdict. This module parses the
offline text with fixed patterns so the pipeline always has data to
cross-check, and the API layer can compare Gemini output against it.
"""

import logging
import re
from typing import Any

from app.schemas.extraction import ContainerInfo, DocumentType, ExtractedDocument, LineItem, PartyInfo

logger = logging.getLogger(__name__)

CONTAINER_RE = re.compile(r"\b([A-Z]{4}\d{7})\s*/?\s*([A-Z]{2}\d{6})\b")
BILL_RE = re.compile(r"\b([A-Z]{3,4}\d{8,12})\b")
DATE_RE = re.compile(r"\b(\d{1,2}\s+[A-Z]{3,9}\s+\d{4})\b")
NUMBER_RE = re.compile(r"([\d][\d,]*(?:\.\d+)?)")


def _to_float(token: str | None) -> float | None:
    if token is None:
        return None
    try:
        return float(token.replace(",", ""))
    except (ValueError, AttributeError):
        return None


def _total_after(text: str, label: str) -> float | None:
    """Find the numeric value that follows a TOTAL <label> header."""
    pattern = rf"TOTAL\s+{label}[^\d\-+]{{0,40}}([\d][\d,]*(?:\.\d+)?)"
    match = re.search(pattern, text, re.IGNORECASE)
    return _to_float(match.group(1)) if match else None


def _value_after(text: str, label: str, max_gap: int = 40) -> str | None:
    pattern = rf"{label}\s*[:\-]?\s*(.{{0,{max_gap}}})"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).strip().splitlines()[0].strip() or None


def classify(text: str, file_name: str = "") -> DocumentType:
    """Identify the document type from its title / headings."""
    haystack = f"{file_name}\n{text}".upper()
    if "BILL OF LADING" in haystack or "B/L NO" in haystack or "SHIPPED ON BOARD" in haystack:
        return DocumentType.BILL_OF_LADING
    if "PACKING LIST" in haystack or "PACKINGLIST" in haystack:
        return DocumentType.PACKING_LIST
    if "COMMERCIAL INVOICE" in haystack or "INVOICE NO" in haystack:
        return DocumentType.COMMERCIAL_INVOICE
    return DocumentType.UNKNOWN


def _party(text: str, label: str) -> PartyInfo | None:
    value = _value_after(text, label)
    if not value:
        return None
    return PartyInfo(name=value, address=None)


def _containers(text: str) -> list[ContainerInfo]:
    seen: dict[str, ContainerInfo] = {}
    for container_no, seal_no in CONTAINER_RE.findall(text):
        key = container_no.upper()
        seen.setdefault(key, ContainerInfo(container_no=key, seal_no=seal_no.upper()))
    return list(seen.values())


def _snippets(text: str) -> dict[str, str]:
    """Verbatim source lines for the fields the UI highlights."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if "Invoice No" in upper and "invoice_no" not in out:
            out["invoice_no"] = stripped
        if "Invoice:" in stripped and "reference" not in out:
            out["reference"] = stripped
        if "TOTAL GROSS WEIGHT" in upper and "total_gross_weight_kg" not in out:
            out["total_gross_weight_kg"] = stripped
        if "TOTAL NET WEIGHT" in upper and "total_net_weight_kg" not in out:
            out["total_net_weight_kg"] = stripped
        if CONTAINER_RE.search(upper) and "containers" not in out:
            out["containers"] = stripped
    return out


def extract(text: str, file_name: str = "") -> ExtractedDocument:
    """Best-effort structured extraction from raw PDF text."""
    doc_type = classify(text, file_name)
    references: list[str] = []

    invoice_ref = re.search(r"Invoice:\s*([A-Z0-9\-/]+)", text, re.IGNORECASE)
    if invoice_ref:
        references.append(invoice_ref.group(1).strip())

    doc_number: str | None = None
    if doc_type is DocumentType.COMMERCIAL_INVOICE:
        doc_number = _value_after(text, r"Invoice\s+No\.?")
    elif doc_type is DocumentType.BILL_OF_LADING:
        doc_number = _value_after(text, r"B/L\s+No\.?")

    booking = re.search(r"Booking\s+No\.?\s*([A-Z0-9\-]+)", text, re.IGNORECASE)
    if booking:
        references.append(booking.group(1).strip())

    date_match = DATE_RE.search(text)
    issue_date = date_match.group(1) if date_match else None

    consignee = None
    if doc_type is DocumentType.BILL_OF_LADING:
        consignee = _party(text, r"CONSIGNEE")
    elif doc_type is DocumentType.PACKING_LIST:
        buyer = _value_after(text, r"Buyer")
        consignee = PartyInfo(name=buyer, address=None) if buyer else None
    else:
        consignee = _party(text, r"BUYER\s*/\s*CONSIGNEE")

    total_gross = _total_after(text, r"GROSS\s+WEIGHT")
    total_net = _total_after(text, r"NET\s+WEIGHT")
    total_packages = _total_after(text, r"PACKAGES|QUANTITY")

    return ExtractedDocument(
        doc_type=doc_type,
        doc_number=doc_number,
        reference_numbers=references,
        issue_date=issue_date,
        shipper=_party(text, r"SELLER\s*/\s*EXPORTER") if doc_type is DocumentType.COMMERCIAL_INVOICE else _party(text, r"SHIPPER"),
        consignee=consignee,
        notify_party=None,
        port_of_loading=_value_after(text, r"Port\s+of\s+Loading"),
        port_of_discharge=_value_after(text, r"Port\s+of\s+Discharge"),
        place_of_delivery=_value_after(text, r"Place\s+of\s+Delivery"),
        vessel_voyage=_value_after(text, r"Vessel\s*/\s*Voyage"),
        total_packages=total_packages,
        total_net_weight_kg=total_net,
        total_gross_weight_kg=total_gross,
        containers=_containers(text),
        items=[],
        snippets=_snippets(text),
    )
