import uuid
from enum import Enum

from pydantic import BaseModel

from app.models.validation import Severity  # re-export


class ValidationRuleId(str, Enum):
    RULE_INVOICE_REF_MATCH = "RULE_INVOICE_REF_MATCH"
    RULE_GROSS_WEIGHT_MATCH = "RULE_GROSS_WEIGHT_MATCH"
    RULE_NET_WEIGHT_INTERNAL = "RULE_NET_WEIGHT_INTERNAL"
    RULE_CONTAINER_SEAL_MATCH = "RULE_CONTAINER_SEAL_MATCH"
    RULE_CONSIGNEE_NAME_SIMILARITY = "RULE_CONSIGNEE_NAME_SIMILARITY"
    RULE_PLACE_OF_DELIVERY_TYPO = "RULE_PLACE_OF_DELIVERY_TYPO"


class ValidationResultOut(BaseModel):
    id: uuid.UUID
    rule_id: str
    severity: Severity
    field_name: str | None = None
    message: str
    source_doc_type: str | None = None
    target_doc_type: str | None = None
    source_value: str | None = None
    target_value: str | None = None
    evidence_snippet: str | None = None

    model_config = {"from_attributes": True}
