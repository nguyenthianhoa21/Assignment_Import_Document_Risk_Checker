"""End-to-end pipeline test against the three real sample PDFs.

Runs the offline deterministic extractor over
``Sample/Sample_Commercial_Invoice.pdf``, ``Sample/Sample_Packing_List.pdf``
and ``Sample/Sample_Bill_of_Lading.pdf`` and asserts that the validation
engine reports the seeded defects instead of a false PASSED verdict.

Run:  pytest tests/test_sample_pipeline.py -v -s
"""

from __future__ import annotations

import pathlib
import sys

import pytest

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.schemas.extraction import DocumentType, ExtractedDocument  # noqa: E402
from app.services.extraction_offline import extract_document_offline  # noqa: E402
from app.services.pdf_parser import extract_text  # noqa: E402
from app.services.validation_engine import run_validations  # noqa: E402

SAMPLE_DIR = BACKEND_ROOT.parent / "Sample"
INVOICE_PDF = SAMPLE_DIR / "Sample_Commercial_Invoice.pdf"
PACKING_LIST_PDF = SAMPLE_DIR / "Sample_Packing_List.pdf"
BILL_OF_LADING_PDF = SAMPLE_DIR / "Sample_Bill_of_Lading.pdf"

HIGH_SEVERITIES = {"CRITICAL", "HIGH"}


def _extract(path: pathlib.Path) -> ExtractedDocument:
    assert path.exists(), f"Missing sample PDF: {path}"
    return extract_document_offline(extract_text(str(path)), str(path))


@pytest.fixture(scope="module")
def documents() -> dict[str, ExtractedDocument]:
    invoice = _extract(INVOICE_PDF)
    packing_list = _extract(PACKING_LIST_PDF)
    bill_of_lading = _extract(BILL_OF_LADING_PDF)
    return {
        invoice.doc_type.value: invoice,
        packing_list.doc_type.value: packing_list,
        bill_of_lading.doc_type.value: bill_of_lading,
    }


# --- Extraction ----------------------------------------------------------
def test_commercial_invoice_fields(documents: dict[str, ExtractedDocument]) -> None:
    ci = documents[DocumentType.COMMERCIAL_INVOICE.value]
    assert ci.doc_number == "IV-2026-1008"
    assert ci.total_gross_weight_kg == 231000.0
    assert ci.total_net_weight_kg == 220000.0
    assert ci.total_packages == 1000.0
    assert ci.issue_date == "18 SEP 2026"


def test_packing_list_fields(documents: dict[str, ExtractedDocument]) -> None:
    pl = documents[DocumentType.PACKING_LIST.value]
    assert "IV-2026-100B" in pl.reference_numbers
    assert pl.total_gross_weight_kg == 232000.0
    container_nos = {c.container_no for c in pl.containers}
    assert {"TGBU1234567", "OOLU7654321"} <= container_nos


def test_bill_of_lading_fields(documents: dict[str, ExtractedDocument]) -> None:
    bl = documents[DocumentType.BILL_OF_LADING.value]
    assert bl.total_gross_weight_kg == 232000.0
    container_nos = {c.container_no for c in bl.containers}
    assert {"TGBU1234567", "OOLU7654327"} <= container_nos


def test_container_seal_pairs_are_parsed(documents: dict[str, ExtractedDocument]) -> None:
    """The UI showed ``? / ?`` when container/seal parsing failed."""
    expected = {
        DocumentType.PACKING_LIST.value: {
            "TGBU1234567": "RH260911",
            "OOLU7654321": "RH260912",
        },
        DocumentType.BILL_OF_LADING.value: {
            "TGBU1234567": "RH260911",
            "OOLU7654327": "RH260912",
        },
    }
    for doc_type, mapping in expected.items():
        parsed = {
            c.container_no: c.seal_no for c in documents[doc_type].containers if c.container_no
        }
        for container_no, seal_no in mapping.items():
            assert parsed.get(container_no) == seal_no, (
                f"{doc_type}: expected {container_no}/{seal_no}, got "
                f"{container_no}/{parsed.get(container_no)!r}"
            )


# --- Validation ----------------------------------------------------------
def test_validation_reports_seeded_defects(
    documents: dict[str, ExtractedDocument],
) -> None:
    findings = run_validations(documents)
    by_rule = {f["rule_id"] for f in findings}

    expected_rules = {
        "RULE_INVOICE_REF_MATCH",
        "RULE_GROSS_WEIGHT_MATCH",
        "RULE_CONTAINER_SEAL_MATCH",
        "RULE_CONSIGNEE_NAME_SIMILARITY",
        "RULE_PLACE_OF_DELIVERY_TYPO",
    }
    missing = expected_rules - by_rule
    assert not missing, f"Validation engine missed rules: {sorted(missing)}"


def test_high_severity_defects_exist(
    documents: dict[str, ExtractedDocument],
) -> None:
    findings = run_validations(documents)
    high = [f for f in findings if f["severity"] in HIGH_SEVERITIES]
    high_rules = {f["rule_id"] for f in high}

    for rule_id in (
        "RULE_INVOICE_REF_MATCH",
        "RULE_GROSS_WEIGHT_MATCH",
        "RULE_CONTAINER_SEAL_MATCH",
    ):
        assert rule_id in high_rules, f"Expected HIGH severity for {rule_id}"

    assert len(high) >= 3, f"Expected at least 3 HIGH findings, got {len(high)}"


def test_not_passed_empty_findings(documents: dict[str, ExtractedDocument]) -> None:
    """Regression guard: the sample set must never validate to zero findings."""
    assert run_validations(documents), "Sample set validated to PASSED with 0 findings"


# --- Missing-document rule ----------------------------------------------
def test_missing_document_is_flagged() -> None:
    """A B/L without an Invoice must not pass silently."""
    bl = _extract(BILL_OF_LADING_PDF)
    findings = run_validations({bl.doc_type.value: bl})

    missing = [f for f in findings if f["rule_id"] == "RULE_MISSING_DOCUMENT"]
    assert missing, "RULE_MISSING_DOCUMENT was not raised for an incomplete set"
    assert all(f["severity"] == "HIGH" for f in missing)
    flagged = {f["target_doc_type"] for f in missing}
    assert DocumentType.COMMERCIAL_INVOICE.value in flagged
    assert DocumentType.PACKING_LIST.value in flagged


def test_verdict_is_rejected_for_samples(
    documents: dict[str, ExtractedDocument],
) -> None:
    """Mirror the API verdict logic: any HIGH finding rejects the shipment."""
    findings = run_validations(documents)
    verdict = (
        "REJECTED"
        if any(f["severity"] in HIGH_SEVERITIES for f in findings)
        else "WARNING"
        if any(f["severity"] == "MEDIUM" for f in findings)
        else "PASSED"
    )
    assert verdict == "REJECTED"


def test_report_findings(capsys: pytest.CaptureFixture[str]) -> None:
    """Print the full finding list for manual inspection."""
    docs = {
        _extract(INVOICE_PDF).doc_type.value: _extract(INVOICE_PDF),
        _extract(PACKING_LIST_PDF).doc_type.value: _extract(PACKING_LIST_PDF),
        _extract(BILL_OF_LADING_PDF).doc_type.value: _extract(BILL_OF_LADING_PDF),
    }
    findings = run_validations(docs)
    print("\n=== Validation findings on the 3 sample PDFs ===")
    for finding in findings:
        print(
            f"{finding['severity']:<8} {finding['rule_id']:<34} {finding['message']}"
        )
    print(f"total={len(findings)}  high={sum(1 for f in findings if f['severity'] in HIGH_SEVERITIES)}")
    with capsys.disabled():
        print("")
