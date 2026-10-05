"""Offline unit test for the cross-document validation rules.

Run manually:  python -m app.tests.test_validation_engine
"""

from app.schemas.extraction import (
    DocumentType,
    ExtractedDocument,
    ContainerInfo,
    LineItem,
    PartyInfo,
)
from app.services.validation_engine import run_validations


def main() -> None:
    ci = ExtractedDocument(
        doc_type=DocumentType.COMMERCIAL_INVOICE,
        doc_number="IV-2026-1008",
        total_gross_weight_kg=231000,
        total_net_weight_kg=220000,
        consignee=PartyInfo(name="GREENFIELD FOOD VIETNAM CO., LTD."),
        items=[
            LineItem(net_weight_kg=55000),
            LineItem(net_weight_kg=55000),
            LineItem(net_weight_kg=55000),
            LineItem(net_weight_kg=55000),
        ],
    )
    pl = ExtractedDocument(
        doc_type=DocumentType.PACKING_LIST,
        doc_number="IV-2026-100B",
        reference_numbers=["IV-2026-100B"],
        total_gross_weight_kg=232000,
        total_net_weight_kg=220000,
        consignee=PartyInfo(name="GREENFIELD FOODS VIETNAM COMPANY LIMITED"),
        items=[
            LineItem(net_weight_kg=55000),
            LineItem(net_weight_kg=55000),
            LineItem(net_weight_kg=55000),
            LineItem(net_weight_kg=55000),
        ],
        containers=[
            ContainerInfo(container_no="TGBU1234567", seal_no="RH260911"),
            ContainerInfo(container_no="OOLU7654321", seal_no="RH260912"),
        ],
    )
    bl = ExtractedDocument(
        doc_type=DocumentType.BILL_OF_LADING,
        doc_number="OBSLQDHCM2609187",
        reference_numbers=["QDO26091288"],
        total_gross_weight_kg=232000,
        consignee=PartyInfo(name="GREENFIELD FOOD VIETNAM CO., LTD."),
        containers=[
            ContainerInfo(container_no="TGBU1234567", seal_no="RH260911"),
            ContainerInfo(container_no="OOLU7654327", seal_no="RH260912"),
        ],
    )

    docs = {
        DocumentType.COMMERCIAL_INVOICE.value: ci,
        DocumentType.PACKING_LIST.value: pl,
        DocumentType.BILL_OF_LADING.value: bl,
    }
    findings = run_validations(docs)
    for finding in findings:
        print(
            finding["severity"].ljust(6),
            finding["rule_id"].ljust(34),
            finding["message"],
        )


if __name__ == "__main__":
    main()
