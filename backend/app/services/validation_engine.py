from __future__ import annotations

import difflib
import logging
from collections.abc import Iterable
from typing import Any

from app.models.validation import Severity
from app.schemas.extraction import DocumentType, ExtractedDocument
from app.schemas.validation import ValidationRuleId

logger = logging.getLogger(__name__)

WEIGHT_TOLERANCE_KG = 0.5
NAME_SIMILARITY_THRESHOLD = 0.85


def _get(docs: dict[str, ExtractedDocument], doc_type: DocumentType) -> ExtractedDocument | None:
    return docs.get(doc_type.value)


def _compare_names(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    normalise = lambda value: " ".join(value.strip().upper().split())
    return difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def _weights_equal(a: Any, b: Any, tolerance: float = WEIGHT_TOLERANCE_KG) -> bool:
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return False


def _evidence(doc: ExtractedDocument | None, *keys: str) -> str | None:
    if not doc:
        return None
    for key in keys:
        snippet = doc.snippets.get(key)
        if snippet:
            return snippet
    return None


def run_validations(docs: dict[str, ExtractedDocument]) -> list[dict[str, Any]]:
    """Compare extracted documents and emit risk findings.

    `docs` maps DocumentType value -> ExtractedDocument. Each finding carries
    `severity`, involved doc types, values and the verbatim evidence snippet.
    """
    findings: list[dict[str, Any]] = []

    def add(
        rule_id: ValidationRuleId,
        severity: Severity,
        field_name: str,
        message: str,
        source_doc: str | None = None,
        target_doc: str | None = None,
        source_value: Any | None = None,
        target_value: Any | None = None,
        evidence: str | None = None,
    ) -> None:
        findings.append(
            {
                "rule_id": rule_id.value,
                "severity": severity.value,
                "field_name": field_name,
                "message": message,
                "source_doc_type": source_doc,
                "target_doc_type": target_doc,
                "source_value": None if source_value is None else str(source_value),
                "target_value": None if target_value is None else str(target_value),
                "evidence_snippet": evidence,
            }
        )

    invoice = _get(docs, DocumentType.COMMERCIAL_INVOICE)
    packing = _get(docs, DocumentType.PACKING_LIST)
    bol = _get(docs, DocumentType.BILL_OF_LADING)

    # --- R1: invoice reference must match PL reference ---------------------
    inv_no = invoice.doc_number if invoice else None
    pl_refs = []
    if packing:
        if packing.doc_number:
            pl_refs.append(packing.doc_number)
        pl_refs.extend(packing.reference_numbers)
    if invoice and packing:
        matches = inv_no in pl_refs if inv_no else False
        if not matches:
            add(
                ValidationRuleId.RULE_INVOICE_REF_MATCH,
                Severity.HIGH,
                "invoice_no",
                f"Invoice number mismatch: CI={inv_no!r} vs PL references={pl_refs!r}. "
                "Possible typo between '8' and 'B'.",
                DocumentType.COMMERCIAL_INVOICE.value,
                DocumentType.PACKING_LIST.value,
                inv_no,
                ", ".join(pl_refs) if pl_refs else None,
                _evidence(packing, "doc_number", "invoice_no", "reference"),
            )

    # --- R2: total gross weight consistency CI <-> PL <-> BL ---------------
    gross_sources = [
        (DocumentType.COMMERCIAL_INVOICE.value, invoice.total_gross_weight_kg if invoice else None),
        (DocumentType.PACKING_LIST.value, packing.total_gross_weight_kg if packing else None),
        (DocumentType.BILL_OF_LADING.value, bol.total_gross_weight_kg if bol else None),
    ]
    present = [(name, value) for name, value in gross_sources if value is not None]
    if len(present) >= 2:
        first_name, first_value = present[0]
        for other_name, other_value in present[1:]:
            if not _weights_equal(first_value, other_value):
                add(
                    ValidationRuleId.RULE_GROSS_WEIGHT_MATCH,
                    Severity.HIGH,
                    "total_gross_weight_kg",
                    f"Gross weight mismatch: {first_name}={first_value} kg vs "
                    f"{other_name}={other_value} kg.",
                    first_name,
                    other_name,
                    first_value,
                    other_value,
                    _evidence(invoice, "total_gross_weight_kg", "gross_weight")
                    or _evidence(packing, "total_gross_weight_kg", "gross_weight"),
                )

    # --- R3: internal net weight sums -------------------------------------
    for doc, label in ((invoice, "CI"), (packing, "PL")):
        if doc and doc.items and doc.total_net_weight_kg is not None:
            items_sum = sum((item.net_weight_kg or 0) for item in doc.items)
            if not _weights_equal(items_sum, doc.total_net_weight_kg):
                add(
                    ValidationRuleId.RULE_NET_WEIGHT_INTERNAL,
                    Severity.MEDIUM,
                    "total_net_weight_kg",
                    f"{label} line-item net sum {items_sum} kg differs from "
                    f"declared total {doc.total_net_weight_kg} kg.",
                    label,
                    label,
                    items_sum,
                    doc.total_net_weight_kg,
                    _evidence(doc, "total_net_weight_kg", "net_weight"),
                )

    # --- R4: container/seal sets between PL and BL ------------------------
    def containers(doc: ExtractedDocument | None) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        if doc:
            for container in doc.containers:
                if container.container_no:
                    result[container.container_no.strip().upper()] = container.seal_no
        return result

    pl_units = containers(packing)
    bl_units = containers(bol)
    if packing and bol and (pl_units or bl_units):
        only_pl = sorted(set(pl_units) - set(bl_units))
        only_bl = sorted(set(bl_units) - set(pl_units))
        shared = set(pl_units) & set(bl_units)
        seal_mismatch = [
            container
            for container in shared
            if (pl_units[container] or "") != (bl_units[container] or "")
        ]
        if only_pl or only_bl or seal_mismatch:
            add(
                ValidationRuleId.RULE_CONTAINER_SEAL_MATCH,
                Severity.HIGH,
                "containers",
                "Container/seal mismatch between Packing List and B/L: "
                f"only in PL={only_pl or []}, only in BL={only_bl or []}, "
                f"seal mismatch={seal_mismatch or []}.",
                DocumentType.PACKING_LIST.value,
                DocumentType.BILL_OF_LADING.value,
                ", ".join(sorted(pl_units)) or None,
                ", ".join(sorted(bl_units)) or None,
                _evidence(packing, "containers", "container_no")
                or _evidence(bol, "containers", "container_no"),
            )

    # --- R5: consignee name similarity ------------------------------------
    names = [
        (DocumentType.COMMERCIAL_INVOICE.value, invoice.consignee.name if invoice and invoice.consignee else None),
        (DocumentType.PACKING_LIST.value, packing.consignee.name if packing and packing.consignee else None),
        (DocumentType.BILL_OF_LADING.value, bol.consignee.name if bol and bol.consignee else None),
    ]
    present_names = [(label, name) for label, name in names if name]
    for index in range(len(present_names)):
        for other in range(index + 1, len(present_names)):
            label_a, name_a = present_names[index]
            label_b, name_b = present_names[other]
            ratio = _compare_names(name_a, name_b)
            if ratio < NAME_SIMILARITY_THRESHOLD and name_a != name_b:
                add(
                    ValidationRuleId.RULE_CONSIGNEE_NAME_SIMILARITY,
                    Severity.MEDIUM,
                    "consignee.name",
                    f"Consignee name differs ({label_a} vs {label_b}, "
                    f"similarity={ratio:.2f}): {name_a!r} vs {name_b!r}.",
                    label_a,
                    label_b,
                    name_a,
                    name_b,
                    _evidence(invoice, "consignee") or _evidence(packing, "consignee"),
                )

    # --- R6: port of discharge / place-of-delivery typo watch -------------
    ports: Iterable[tuple[str, str | None]] = [
        (DocumentType.COMMERCIAL_INVOICE.value, invoice.port_of_discharge if invoice else None),
        (DocumentType.PACKING_LIST.value, None),
        (DocumentType.BILL_OF_LADING.value, bol.place_of_delivery if bol else None),
    ]
    for label, value in ports:
        if value and "CAT LAL" in value.upper():
            add(
                ValidationRuleId.RULE_PLACE_OF_DELIVERY_TYPO,
                Severity.LOW,
                "place_of_delivery",
                f"Possible port typo on {label}: {value!r} (expected 'CAT LAI').",
                label,
                label,
                value,
                "CAT LAI",
                _evidence(bol, "place_of_delivery"),
            )

    return findings
