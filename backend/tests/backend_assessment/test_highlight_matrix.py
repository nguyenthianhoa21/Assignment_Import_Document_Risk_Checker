from __future__ import annotations

# Auto-generated from the live frontend RULE_CELLS map. Do not hand-edit.
CELLS = {'RULE_INVOICE_REF_MATCH': ['COMMERCIAL_INVOICE:doc_number', 'PACKING_LIST:references'], 'RULE_GROSS_WEIGHT_MATCH': ['COMMERCIAL_INVOICE:total_gross_weight_kg', 'PACKING_LIST:total_gross_weight_kg', 'BILL_OF_LADING:total_gross_weight_kg'], 'RULE_NET_WEIGHT_MATCH': ['COMMERCIAL_INVOICE:total_net_weight_kg', 'PACKING_LIST:total_net_weight_kg'], 'RULE_NET_WEIGHT_INTERNAL': ['COMMERCIAL_INVOICE:total_net_weight_kg', 'PACKING_LIST:total_net_weight_kg'], 'RULE_TOTAL_PACKAGES_MATCH': ['COMMERCIAL_INVOICE:total_packages', 'PACKING_LIST:total_packages', 'BILL_OF_LADING:total_packages'], 'RULE_GROSS_WEIGHT_PER_CONTAINER': ['COMMERCIAL_INVOICE:containers', 'PACKING_LIST:containers', 'BILL_OF_LADING:containers'], 'RULE_CONTAINER_SEAL_MATCH': ['COMMERCIAL_INVOICE:containers', 'PACKING_LIST:containers', 'BILL_OF_LADING:containers'], 'RULE_CONSIGNEE_NAME_SIMILARITY': ['COMMERCIAL_INVOICE:consignee_name', 'PACKING_LIST:consignee_name', 'BILL_OF_LADING:consignee_name'], 'RULE_ADDRESS_SIMILARITY': ['COMMERCIAL_INVOICE:consignee_address', 'PACKING_LIST:consignee_address'], 'RULE_PLACE_OF_DELIVERY_TYPO': ['COMMERCIAL_INVOICE:port_of_discharge', 'BILL_OF_LADING:place_of_delivery'], 'RULE_PORT_CONSISTENCY': ['COMMERCIAL_INVOICE:port_of_loading', 'BILL_OF_LADING:port_of_loading'], 'RULE_DATE_CHRONOLOGY': ['COMMERCIAL_INVOICE:issue_date', 'PACKING_LIST:issue_date', 'BILL_OF_LADING:issue_date'], 'RULE_MISSING_DOCUMENT': []}

DOC_COLS = ["COMMERCIAL_INVOICE", "PACKING_LIST", "BILL_OF_LADING"]

def expand(cell_id: str) -> list[str]:
    if cell_id == "containers":
        return [f"{c}:containers" for c in DOC_COLS]
    return [cell_id]

def flagged_cells(findings):
    m: dict[str, str] = {}
    for f in findings:
        raw = CELLS.get(f["rule_id"], [])
        if raw and raw:
            ids = [x for cell in raw for x in expand(cell)]
        elif f.get("field_name"):
            base = expand(f["field_name"])
            ids = []
            for c in base:
                if ":" in c:
                    ids.append(c)
                else:
                    ids.extend([f"{d}:{c}" for d in DOC_COLS])
        else:
            ids = []
        for cell in ids:
            m[cell] = f["severity"]
    return m

def _findings() -> list[dict]:
    return [
        {'rule_id': 'RULE_INVOICE_REF_MATCH', 'severity': 'HIGH', 'field_name': 'invoice_no'},
        {'rule_id': 'RULE_GROSS_WEIGHT_MATCH', 'severity': 'HIGH', 'field_name': 'total_gross_weight_kg'},
        {'rule_id': 'RULE_CONTAINER_SEAL_MATCH', 'severity': 'HIGH', 'field_name': 'containers'},
        {'rule_id': 'RULE_CONSIGNEE_NAME_SIMILARITY', 'severity': 'MEDIUM', 'field_name': 'consignee.name'},
        {'rule_id': 'RULE_PLACE_OF_DELIVERY_TYPO', 'severity': 'LOW', 'field_name': 'place_of_delivery'},
        {'rule_id': 'RULE_DATE_CHRONOLOGY', 'severity': 'INFO', 'field_name': 'issue_date'},
    ]

def test_issue_date_highlights_on_click():
    m = flagged_cells(_findings())
    for doc in DOC_COLS:
        cell = f"{doc}:issue_date"
        assert cell in m, f"Issue Date column {doc} must highlight for RULE_DATE_CHRONOLOGY"

def test_container_seal_list_highlights():
    m = flagged_cells(_findings())
    for doc in DOC_COLS:
        cell = f"{doc}:containers"
        assert cell in m, f"Container/Seal column {doc} must highlight for RULE_CONTAINER_SEAL_MATCH"

def test_all_reported_rules_have_cells():
    for f in _findings():
        assert CELLS.get(f["rule_id"]) is not None, f"Missing RULE_CELLS entry for {f['rule_id']}"
        assert len(CELLS[f["rule_id"]]) > 0, f"Empty mapping for {f['rule_id']}"

def test_no_highlight_without_finding():
    m = flagged_cells([])
    assert m == {}

def test_legacy_containers_shorthand_still_highlights():
    m = flagged_cells([{"rule_id": "RULE_CONTAINER_SEAL_MATCH", "severity": "HIGH", "field_name": "containers"}])
    for doc in DOC_COLS:
        assert f"{doc}:containers" in m
