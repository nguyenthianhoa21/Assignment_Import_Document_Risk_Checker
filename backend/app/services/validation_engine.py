from __future__ import annotations

import difflib
import logging
import re
from datetime import date, datetime
from typing import Any

from app.models.validation import Severity
from app.schemas.extraction import DocumentType, ExtractedDocument
from app.schemas.validation import ValidationRuleId
from app.services.bge_matcher import BGEMatcher

logger = logging.getLogger(__name__)

# --- Tunable thresholds (deterministic layer) ------------------------------
WEIGHT_TOLERANCE_KG = 0.5
PACKAGE_TOLERANCE = 0
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


def _is_typo_port(value: str | None) -> bool:
    """True when a port name is a misspelling of CAT LAI.

    ``ECAT LAI`` and ``CAT LAL`` are the typos seen on real bills of lading.
    The leading ``E`` glitch and the trailing token are compared separately, so
    a correctly spelled ``CAT LAI, HO CHI MINH CITY`` is never flagged.
    """
    if not value:
        return False
    match = re.search(r"\b(E?CAT)\s+(\w+)", value.upper())
    if not match:
        return False
    return match.group(1) != "CAT" or match.group(2) != "LAI"


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

    # R0 - Missing document in the CI / PL / BL triplet.
    for expected, short in (
        (DocumentType.COMMERCIAL_INVOICE, "Commercial Invoice"),
        (DocumentType.PACKING_LIST, "Packing List"),
        (DocumentType.BILL_OF_LADING, "Bill of Lading"),
    ):
        if expected.value not in docs:
            add(
                ValidationRuleId.RULE_MISSING_DOCUMENT,
                Severity.HIGH,
                "document_set",
                f"Missing document: {short} was not uploaded or failed extraction.",
                "Cross-document comparison is blind without the full CI/PL/BL set; "
                "mismatches in weights, references and container ids go undetected.",
                f"Upload the missing {short} (or re-run extraction for it) before "
                "submitting the shipment for clearance.",
                None, expected.value, None, None, None,
            )

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

    # ------------------------------------------------------------------
    # R8 - Consignee legal-name matching via BGE-M3 (strict consistency).
    #
    # Legal-form suffixes (``CO., LTD.`` vs ``COMPANY LIMITED``) are stripped
    # first, because only the *core* trade name has to match word for word.
    # The cleaned core names go through :class:`BGEMatcher`, which combines a
    # dense BGE-M3 embedding with strict lexical token comparison: any single
    # differing token (``FOOD`` vs ``FOODS``) makes the pair inconsistent.
    # ------------------------------------------------------------------
    def party(doc: ExtractedDocument | None, attr: str = "consignee"):
        return getattr(doc, attr, None) if doc else None

    parties = [
        (DocumentType.COMMERCIAL_INVOICE.value, party(ci)),
        (DocumentType.PACKING_LIST.value, party(pl)),
        (DocumentType.BILL_OF_LADING.value, party(bl)),
    ]
    named = [(label, p.name) for label, p in parties if p and p.name]
    reported: set[tuple[str, str]] = set()
    for i in range(len(named)):
        for j in range(i + 1, len(named)):
            label_a, name_a = named[i]
            label_b, name_b = named[j]
            if name_a == name_b:
                continue

            # Only a legal-form suffix differs -> same legal entity, acceptable.
            core_a = _strip_legal_suffix(name_a)
            core_b = _strip_legal_suffix(name_b)
            if core_a == core_b:
                continue

            key = (label_a, label_b)
            if key in reported:
                continue

            # Strict BGE-M3 comparison on the suffix-stripped core names.
            verdict = BGEMatcher.compare(core_a, core_b)
            if verdict.is_consistent:
                continue
            reported.add(key)

            diffs = verdict.diff_tokens or ["<lexical mismatch>"]
            diff_text = ", ".join(diffs)
            add(
                ValidationRuleId.RULE_CONSIGNEE_NAME_SIMILARITY,
                Severity.MEDIUM,
                "consignee.name",
                f"Consignee core name differs ({label_a} vs {label_b}, "
                f"BGE-M3 score={verdict.score:.4f}): {core_a!r} vs {core_b!r} "
                f"[differing tokens: {diff_text}].",
                f"The core legal name is not identical word for word - differing tokens: "
                f"{diff_text} (BGE-M3 similarity {verdict.score:.4f}, threshold "
                f"{BGEMatcher.STRICT_THRESHOLD}). Under strict customs / L-C practice any "
                f"difference in the core trade name can be treated as a different consignee "
                f"and require an amendment letter.",
                "Request a corrected consignee name so the core words match exactly across "
                "CI, PL and B/L; only the legal-form suffix may differ.",
                label_a, label_b, name_a, name_b,
                _evidence(ci, "consignee") or _evidence(pl, "consignee")
                or f"consignee: {name_a!r} vs {name_b!r} (differing: {diff_text})",
            )

    # R9 - Consignee address consistency via BGE-M3 (strict, token-level).
    addrs = [
        (DocumentType.COMMERCIAL_INVOICE.value, party(ci).address if party(ci) else None),
        (DocumentType.PACKING_LIST.value, party(pl).address if party(pl) else None),
        (DocumentType.BILL_OF_LADING.value, party(bl).address if party(bl) else None),
    ]
    addr_pairs = [(la, aa) for la, aa in addrs if aa]
    reported_addr: set[tuple[str, str]] = set()
    for i in range(len(addr_pairs)):
        for j in range(i + 1, len(addr_pairs)):
            la, aa = addr_pairs[i]
            lb, ab = addr_pairs[j]
            if aa.strip().upper() == ab.strip().upper():
                continue
            if (la, lb) in reported_addr:
                continue
            verdict = BGEMatcher.compare(aa, ab)
            if verdict.is_consistent:
                continue
            reported_addr.add((la, lb))
            diffs = verdict.diff_tokens or ["<address mismatch>"]
            diff_text = ", ".join(diffs)
            add(
                ValidationRuleId.RULE_ADDRESS_SIMILARITY,
                Severity.MEDIUM,
                "consignee.address",
                f"Consignee address differs ({la} vs {lb}, BGE-M3 score={verdict.score:.4f}): "
                f"{aa!r} vs {ab!r} [differing tokens: {diff_text}].",
                f"Address tokens differ ({diff_text}, BGE-M3 similarity {verdict.score:.4f}). "
                f"A wrong street number or district delays delivery and can block "
                f"customs verification at the place of delivery.",
                f"Align the consignee address on all documents; specifically reconcile: "
                f"{diff_text}.",
                la, lb, aa, ab,
                _evidence(ci, "consignee") or _evidence(pl, "consignee")
                or f"address: {aa!r} vs {ab!r} (differing: {diff_text})",
            )

    # R10 - Port / place-of-delivery consistency via BGE-M3 (catches ECAT LAL).
    #
    # Cross-document comparison first: the place of delivery / discharge port
    # written on the Bill of Lading must match the port stated on the other
    # documents. A misspelling such as ``ECAT LAI`` or ``CAT LAL`` differs from
    # ``CAT LAI`` by one character, which the strict BGE-M3 token check flags.
    EXPECTED_CAT_LAI = "CAT LAI, HO CHI MINH CITY, VIETNAM"

    port_claims = [
        (DocumentType.COMMERCIAL_INVOICE.value, ci.port_of_discharge if ci else None),
        (DocumentType.BILL_OF_LADING.value, bl.port_of_discharge if bl else None),
        (DocumentType.BILL_OF_LADING.value, bl.place_of_delivery if bl else None),
    ]
    seen_ports: set[tuple[str, str]] = set()
    for label, value in port_claims:
        if not value:
            continue
        key = (label, value.strip().upper())
        if key in seen_ports:
            continue
        seen_ports.add(key)

        # Compare against the canonical port AND against the sibling documents.
        against_canonical = BGEMatcher.compare(EXPECTED_CAT_LAI, value)
        sibling = next(
            (other for other_label, other in port_claims
             if other_label != label and other and other.strip().upper() != value.strip().upper()),
            None,
        )
        vs_sibling = BGEMatcher.compare(sibling, value) if sibling else None

        canonical_ok = "CAT LAI" in value.upper()
        if against_canonical.is_consistent and canonical_ok:
            continue
        if vs_sibling is not None and vs_sibling.is_consistent:
            # Matches another document even if the spelling is unusual; only
            # flag if it also disagrees with the canonical discharge port.
            if canonical_ok:
                continue

        diffs = against_canonical.diff_tokens or vs_sibling.diff_tokens if vs_sibling else against_canonical.diff_tokens
        diff_text = ", ".join(diffs or ["<port mismatch>"])
        detail = (
            f"expected {EXPECTED_CAT_LAI!r}, got {value!r} "
            f"(BGE-M3 score={against_canonical.score:.4f}, differing tokens: {diff_text})"
        )
        if vs_sibling is not None and not vs_sibling.is_consistent:
            detail += f"; also differs from {sibling!r} (score={vs_sibling.score:.4f})"
        add(
            ValidationRuleId.RULE_PLACE_OF_DELIVERY_TYPO,
            Severity.MEDIUM,
            "place_of_delivery",
            f"Place of delivery / discharge port mismatch on {label}: {detail}.",
            f"The port name deviates from the canonical discharge port "
            f"(differing tokens: {diff_text}). A misspelled port does not match the port "
            f"code in the manifest, so the container can be refused or delayed at "
            f"clearance.",
            f"Correct the port to {EXPECTED_CAT_LAI!r} on the affected document.",
            label, DocumentType.COMMERCIAL_INVOICE.value, value, EXPECTED_CAT_LAI,
            _evidence(bl, "place_of_delivery")
            or f"{label}: {value!r} (differing tokens: {diff_text})",
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

    # R12 - Chronology: CI / PL must not be dated after the B/L shipped-on-board date.
    #
    # Goods cannot be invoiced or packed after they have already sailed, so an
    # invoice or packing list carrying a date later than the B/L on-board date
    # is an inconsistency customs and the LC bank may reject.
    # The opposite direction (CI/PL before sailing) is normal trade practice and
    # is therefore NOT reported.
    bl_date = _parse_date(bl.issue_date if bl else None)
    if bl_date:
        for label, doc in (
            (DocumentType.COMMERCIAL_INVOICE.value, ci),
            (DocumentType.PACKING_LIST.value, pl),
        ):
            doc_date = _parse_date(doc.issue_date if doc else None)
            if not doc_date or doc_date <= bl_date:
                continue
            add(
                ValidationRuleId.RULE_DATE_CHRONOLOGY,
                Severity.INFO,
                "issue_date",
                f"Chronology anomaly: {label} date {doc_date} is after "
                f"B/L shipped-on-board {bl_date}.",
                "An invoice or packing list dated after the goods already sailed is "
                "logically impossible; customs or the LC bank may reject the set.",
                f"Re-issue the {label} with a date on or before the B/L shipped-on-board "
                "date, or correct the B/L on-board date.",
                label, DocumentType.BILL_OF_LADING.value,
                str(doc_date), str(bl_date), _evidence(doc, "issue_date"),
            )

    return findings
