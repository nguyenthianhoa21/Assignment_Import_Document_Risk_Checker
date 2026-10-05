from __future__ import annotations

import difflib
import logging
import re
from datetime import date, datetime
from typing import Any

from app.models.validation import Severity
from app.schemas.extraction import DocumentType, ExtractedDocument
from app.schemas.validation import ValidationRuleId

logger = logging.getLogger(__name__)

# --- Tunable thresholds (deterministic layer) ------------------------------
WEIGHT_TOLERANCE_KG = 0.5
PACKAGE_TOLERANCE = 0
NAME_SIMILARITY_THRESHOLD = 0.85
ADDRESS_SIMILARITY_THRESHOLD = 0.80

LEGAL_SUFFIXES = {
    "CO., LTD.", "CO LTD", "CO.,LTD.", "COMPANY LIMITED", "CO., LTD",
    "LTD", "LIMITED", "JSC", "JSC.", "CORP", "CORPORATION", "INC", "CO.",
}

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "SEPT": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


# --- Small helpers ---------------------------------------------------------
def _get(docs: dict[str, ExtractedDocument], doc_type: DocumentType) -> ExtractedDocument | None:
    return docs.get(doc_type.value)


def _strip_legal_suffix(name: str) -> str:
    """Remove a trailing legal-form suffix so core names can be compared."""
    cleaned = " ".join(name.upper().strip().split())
    for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip(" ,.")
    return cleaned


def _similarity(a: str | None, b: str | None) -> float:
    if not a or not b:
        return 0.0
    normalise = lambda value: " ".join(value.upper().strip().split())
    return difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()


def _weights_equal(a: Any, b: Any, tolerance: float = WEIGHT_TOLERANCE_KG) -> bool:
    if a is None or b is None:
        return False
    try:
        return abs(float(a) - float(b)) <= tolerance
    except (TypeError, ValueError):
        return False


def _evidence(doc: ExtractedDocument | None, *keys: str) -> str | None:
    """Return a verbatim snippet from a document for UI highlighting."""
    if not doc:
        return None
    for key in keys:
        snippet = doc.snippets.get(key)
        if snippet:
            return snippet
    return None


def _parse_date(value: str | None) -> date | None:
    """Parse common formats: '18 SEP 2026', '2026-09-18', '18/09/2026'."""
    if not value:
        return None
    text = value.strip().upper()
    match = re.search(r"(\d{1,2})\s+([A-Z]{3,4})\s+(\d{4})", text)
    if match and match.group(2)[:3] in MONTHS:
        return date(int(match.group(3)), MONTHS[match.group(2)[:3]], int(match.group(1)))
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


# --- Engine ----------------------------------------------------------------
def run_validations(docs: dict[str, ExtractedDocument]) -> list[dict[str, Any]]:
    """Deterministic cross-document validation layer.

    Pure Python logic only (exact string, numeric, set and fuzzy-local checks)
    to guarantee reproducibility and avoid LLM hallucination. A semantic
    Gemini layer may be layered on top separately.

    `docs` maps DocumentType value -> ExtractedDocument. Returns findings with
    severity, business reason, remediation, involved docs/values and evidence.
    """
    findings: list[dict[str, Any]] = []

    def add(
        rule_id: ValidationRuleId,
        severity: Severity,
        field_name: str,
        message: str,
        reason: str,
        suggestion: str,
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
                "risk_level": "HIGH" if severity in (Severity.CRITICAL, Severity.HIGH) else severity.value,
                "field_name": field_name,
                "message": message,
                "reason": reason,
                "suggestion": suggestion,
                "source_doc_type": source_doc,
                "target_doc_type": target_doc,
                "source_value": None if source_value is None else str(source_value),
                "target_value": None if target_value is None else str(target_value),
                "evidence_snippet": evidence,
            }
        )

    ci = _get(docs, DocumentType.COMMERCIAL_INVOICE)
    pl = _get(docs, DocumentType.PACKING_LIST)
    bl = _get(docs, DocumentType.BILL_OF_LADING)

    # R1 - Invoice reference exact match (CI doc_number vs PL references)
    inv_no = ci.doc_number if ci else None
    pl_refs = ([pl.doc_number] if pl and pl.doc_number else []) + (pl.reference_numbers if pl else [])
    pl_refs = [r for r in pl_refs if r]
    if ci and pl and inv_no:
        if inv_no not in pl_refs:
            add(
                ValidationRuleId.RULE_INVOICE_REF_MATCH,
                Severity.HIGH,
                "invoice_no",
                f"Invoice number mismatch: CI={inv_no!r} vs PL references={pl_refs!r}.",
                "Likely a 8/B (or similar) transcription typo between Invoice and Packing List. "
                "Customs or the LC issuing bank may reject the document set.",
                "Ask the exporter to re-issue the Packing List with the exact Invoice number "
                "and confirm against the signed contract.",
                DocumentType.COMMERCIAL_INVOICE.value,
                DocumentType.PACKING_LIST.value,
                inv_no,
                ", ".join(pl_refs) if pl_refs else None,
                _evidence(pl, "doc_number", "invoice_no", "reference"),
            )

    # R2 - Total gross weight consistency across CI / PL / BL
    gross = [
        (DocumentType.COMMERCIAL_INVOICE.value, ci.total_gross_weight_kg if ci else None),
        (DocumentType.PACKING_LIST.value, pl.total_gross_weight_kg if pl else None),
        (DocumentType.BILL_OF_LADING.value, bl.total_gross_weight_kg if bl else None),
    ]
    present = [(n, v) for n, v in gross if v is not None]
    if len(present) >= 2:
        base_name, base_val = present[0]
        for other_name, other_val in present[1:]:
            if not _weights_equal(base_val, other_val):
                delta = float(other_val) - float(base_val)
                add(
                    ValidationRuleId.RULE_GROSS_WEIGHT_MATCH,
                    Severity.HIGH,
                    "total_gross_weight_kg",
                    f"Gross weight mismatch: {base_name}={base_val} kg vs {other_name}={other_val} kg (delta={delta:+.0f} kg).",
                    "Gross weight drives customs valuation and freight billing; a discrepancy can "
                    "block clearance or cause demurrage disputes.",
                    "Reconcile the weighing record and re-issue the inconsistent document with the correct total gross weight.",
                    base_name, other_name, base_val, other_val,
                    _evidence(ci, "total_gross_weight_kg", "gross_weight") or _evidence(pl, "total_gross_weight_kg", "gross_weight"),
                )

    # R3 - Total net weight consistency (CI vs PL)
    if ci and pl:
        if (
            ci.total_net_weight_kg is not None
            and pl.total_net_weight_kg is not None
            and not _weights_equal(ci.total_net_weight_kg, pl.total_net_weight_kg)
        ):
            add(
                ValidationRuleId.RULE_NET_WEIGHT_MATCH,
                Severity.MEDIUM,
                "total_net_weight_kg",
                f"Net weight mismatch: CI={ci.total_net_weight_kg} kg vs PL={pl.total_net_weight_kg} kg.",
                "Net weight underpins duty calculation; an inconsistency signals a data entry error.",
                "Verify line-item weights on both documents and re-issue the incorrect one.",
                DocumentType.COMMERCIAL_INVOICE.value, DocumentType.PACKING_LIST.value,
                ci.total_net_weight_kg, pl.total_net_weight_kg,
                _evidence(ci, "total_net_weight_kg", "net_weight"),
            )

    # R4 - Total packages consistency (CI vs PL vs BL)
    pkg = [
        (DocumentType.COMMERCIAL_INVOICE.value, ci.total_packages if ci else None),
        (DocumentType.PACKING_LIST.value, pl.total_packages if pl else None),
        (DocumentType.BILL_OF_LADING.value, bl.total_packages if bl else None),
    ]
    present_pkg = [(n, v) for n, v in pkg if v is not None]
    if len(present_pkg) >= 2:
        base_name, base_val = present_pkg[0]
        for other_name, other_val in present_pkg[1:]:
            if abs(float(base_val) - float(other_val)) > PACKAGE_TOLERANCE:
                add(
                    ValidationRuleId.RULE_TOTAL_PACKAGES_MATCH,
                    Severity.MEDIUM,
                    "total_packages",
                    f"Total packages mismatch: {base_name}={base_val} vs {other_name}={other_val}.",
                    "Package count affects receiving inspection and container stowage verification.",
                    "Recount packages and align the totals before submission.",
                    base_name, other_name, base_val, other_val,
                    _evidence(pl, "total_packages", "packages") or _evidence(bl, "total_packages"),
                )

    # R5 - Internal net-weight sum per document (line items vs declared total)
    for doc, label in ((ci, "CI"), (pl, "PL")):
        if doc and doc.items and doc.total_net_weight_kg is not None:
            items_sum = sum((item.net_weight_kg or 0) for item in doc.items)
            if not _weights_equal(items_sum, doc.total_net_weight_kg):
                add(
                    ValidationRuleId.RULE_NET_WEIGHT_INTERNAL,
                    Severity.MEDIUM,
                    "total_net_weight_kg",
                    f"{label} line-item net sum {items_sum} kg differs from declared total {doc.total_net_weight_kg} kg.",
                    "The document's own rows do not sum to its total, indicating missing rows or a wrong total.",
                    "Re-add the line items and correct the stated total.",
                    label, label, items_sum, doc.total_net_weight_kg,
                    _evidence(doc, "total_net_weight_kg", "net_weight"),
                )

    # R6 - Per-container gross weight consistency (PL vs BL)
    def container_map(doc: ExtractedDocument | None) -> dict[str, float | None]:
        return {
            c.container_no.strip().upper(): c.gross_weight_kg
            for c in (doc.containers if doc else [])
            if c.container_no
        }

    pl_units, bl_units = container_map(pl), container_map(bl)
    shared = set(pl_units) & set(bl_units)
    for container in sorted(shared):
        a, b = pl_units[container], bl_units[container]
        if a is not None and b is not None and not _weights_equal(a, b):
            add(
                ValidationRuleId.RULE_GROSS_WEIGHT_PER_CONTAINER,
                Severity.MEDIUM,
                f"containers[{container}].gross_weight_kg",
                f"Container {container} gross weight mismatch: PL={a} kg vs BL={b} kg.",
                "Per-container weights drive stowage and detention charges; mismatches cause port disputes.",
                "Re-weigh or re-issue the document with the verified container weight.",
                DocumentType.PACKING_LIST.value, DocumentType.BILL_OF_LADING.value, a, b,
                _evidence(pl, "containers", "container_no"),
            )

    # R7 - Container & seal set exact match (PL vs BL)
    def seal_map(doc: ExtractedDocument | None) -> dict[str, str | None]:
        return {
            c.container_no.strip().upper(): (c.seal_no or "").strip().upper()
            for c in (doc.containers if doc else [])
            if c.container_no
        }

    pl_seals, bl_seals = seal_map(pl), seal_map(bl)
    if pl and bl and (pl_seals or bl_seals):
        only_pl = sorted(set(pl_seals) - set(bl_seals))
        only_bl = sorted(set(bl_seals) - set(pl_seals))
        seal_diff = [c for c in set(pl_seals) & set(bl_seals) if pl_seals[c] != bl_seals[c]]
        if only_pl or only_bl or seal_diff:
            add(
                ValidationRuleId.RULE_CONTAINER_SEAL_MATCH,
                Severity.HIGH,
                "containers",
                f"Container/seal mismatch PL vs BL: only in PL={only_pl or []}, only in BL={only_bl or []}, seal mismatch={seal_diff or []}.",
                "A wrong container number (e.g. ending ...4327 vs ...4321) prevents release of the "
                "container at the discharge port and can incur demurrage.",
                "Confirm the physical container/seal numbers and re-issue the Bill of Lading / Packing List accordingly.",
                DocumentType.PACKING_LIST.value, DocumentType.BILL_OF_LADING.value,
                ", ".join(sorted(pl_seals)) or None, ", ".join(sorted(bl_seals)) or None,
                _evidence(pl, "containers", "container_no") or _evidence(bl, "containers", "container_no"),
            )

    # R8 - Consignee legal-name matching (allow legal-suffix differences, flag core differences)
    def party(doc: ExtractedDocument | None, attr: str = "consignee"):
        return getattr(doc, attr, None) if doc else None

    parties = [
        (DocumentType.COMMERCIAL_INVOICE.value, party(ci)),
        (DocumentType.PACKING_LIST.value, party(pl)),
        (DocumentType.BILL_OF_LADING.value, party(bl)),
    ]
    named = [(label, p.name) for label, p in parties if p and p.name]
    for i in range(len(named)):
        for j in range(i + 1, len(named)):
            label_a, name_a = named[i]
            label_b, name_b = named[j]
            if name_a == name_b:
                continue
            ratio = _similarity(name_a, name_b)
            core_a, core_b = _strip_legal_suffix(name_a), _strip_legal_suffix(name_b)
            core_match = core_a == core_b
            if core_match:
                continue  # only a legal-form suffix differs -> acceptable
            if ratio < NAME_SIMILARITY_THRESHOLD:
                add(
                    ValidationRuleId.RULE_CONSIGNEE_NAME_SIMILARITY,
                    Severity.MEDIUM,
                    "consignee.name",
                    f"Consignee name differs ({label_a} vs {label_b}, similarity={ratio:.2f}): {name_a!r} vs {name_b!r}.",
                    "Core legal name differs (e.g. extra 'S'); customs may require an amendment letter.",
                    "Request a corrected consignee name consistent across CI, PL and B/L.",
                    label_a, label_b, name_a, name_b,
                    _evidence(ci, "consignee") or _evidence(pl, "consignee"),
                )

    # R9 - Consignee address similarity (soft check)
    addrs = [
        (DocumentType.COMMERCIAL_INVOICE.value, party(ci).address if party(ci) else None),
        (DocumentType.PACKING_LIST.value, party(pl).address if party(pl) else None),
    ]
    for i in range(len(addrs)):
        for j in range(i + 1, len(addrs)):
            la, aa = addrs[i]
            lb, ab = addrs[j]
            if aa and ab:
                ratio = _similarity(aa, ab)
                if ratio < ADDRESS_SIMILARITY_THRESHOLD:
                    add(
                        ValidationRuleId.RULE_ADDRESS_SIMILARITY,
                        Severity.LOW,
                        "consignee.address",
                        f"Consignee address differs ({la} vs {lb}, similarity={ratio:.2f}).",
                        "Address mismatch may delay delivery or customs verification.",
                        "Align the consignee address on all documents.",
                        la, lb, aa, ab, _evidence(ci, "address"),
                    )

    # R10 - Port-of-delivery / discharge typo watch (CAT LAL vs CAT LAI)
    for label, value in (
        (DocumentType.BILL_OF_LADING.value, bl.place_of_delivery if bl else None),
        (DocumentType.COMMERCIAL_INVOICE.value, ci.port_of_discharge if ci else None),
    ):
        if value and re.search(r"\bCAT\s+LAL\b", value.upper()):
            add(
                ValidationRuleId.RULE_PLACE_OF_DELIVERY_TYPO,
                Severity.LOW,
                "place_of_delivery",
                f"Possible port typo on {label}: {value!r} (expected 'CAT LAI').",
                "A misspelled port may not match the port code in the manifest and can delay clearance.",
                "Correct the port name to 'CAT LAI, HO CHI MINH CITY' on the Bill of Lading.",
                label, label, value, "CAT LAI", _evidence(bl, "place_of_delivery"),
            )

    # R11 - Port consistency (loading/discharge must not contradict across CI vs BL)
    if ci and bl:
        if (
            ci.port_of_loading and bl.port_of_loading
            and _similarity(ci.port_of_loading, bl.port_of_loading) < 0.8
        ):
            add(
                ValidationRuleId.RULE_PORT_CONSISTENCY,
                Severity.MEDIUM,
                "port_of_loading",
                f"Port of loading differs: CI={ci.port_of_loading!r} vs BL={bl.port_of_loading!r}.",
                "Incorrect loading port misroutes the shipment and affects duty/freight calculations.",
                "Confirm the actual loading port and align the documents.",
                DocumentType.COMMERCIAL_INVOICE.value, DocumentType.BILL_OF_LADING.value,
                ci.port_of_loading, bl.port_of_loading, _evidence(bl, "port_of_loading"),
            )

    # R12 - Chronology: invoice should not pre-date the B/L shipped-on-board date
    bl_date = _parse_date(bl.issue_date if bl else None)
    ci_date = _parse_date(ci.issue_date if ci else None)
    pl_date = _parse_date(pl.issue_date if pl else None)
    if bl_date and ci_date and ci_date < bl_date:
        add(
            ValidationRuleId.RULE_DATE_CHRONOLOGY,
            Severity.INFO,
            "issue_date",
            f"Chronology anomaly: Invoice date {ci_date} is before B/L shipped-on-board {bl_date}.",
            "An invoice issued before goods shipped is unusual and may be flagged during LC review.",
            "Confirm the invoice was issued after shipment; correct the date if not.",
            DocumentType.COMMERCIAL_INVOICE.value, DocumentType.BILL_OF_LADING.value,
            str(ci_date), str(bl_date), _evidence(ci, "issue_date"),
        )

    return findings
