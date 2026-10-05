import uuid
from enum import Enum

from pydantic import BaseModel, Field

from app.models.validation import Severity  # re-export


class ValidationRuleId(str, Enum):
    RULE_INVOICE_REF_MATCH = "RULE_INVOICE_REF_MATCH"
    RULE_GROSS_WEIGHT_MATCH = "RULE_GROSS_WEIGHT_MATCH"
    RULE_NET_WEIGHT_MATCH = "RULE_NET_WEIGHT_MATCH"
    RULE_TOTAL_PACKAGES_MATCH = "RULE_TOTAL_PACKAGES_MATCH"
    RULE_NET_WEIGHT_INTERNAL = "RULE_NET_WEIGHT_INTERNAL"
    RULE_GROSS_WEIGHT_PER_CONTAINER = "RULE_GROSS_WEIGHT_PER_CONTAINER"
    RULE_CONTAINER_SEAL_MATCH = "RULE_CONTAINER_SEAL_MATCH"
    RULE_CONSIGNEE_NAME_SIMILARITY = "RULE_CONSIGNEE_NAME_SIMILARITY"
    RULE_ADDRESS_SIMILARITY = "RULE_ADDRESS_SIMILARITY"
    RULE_PLACE_OF_DELIVERY_TYPO = "RULE_PLACE_OF_DELIVERY_TYPO"
    RULE_DATE_CHRONOLOGY = "RULE_DATE_CHRONOLOGY"
    RULE_PORT_CONSISTENCY = "RULE_PORT_CONSISTENCY"
    RULE_MISSING_DOCUMENT = "RULE_MISSING_DOCUMENT"


class ValidationResultOut(BaseModel):
    id: uuid.UUID
    rule_id: str
    severity: Severity
    risk_level: str | None = Field(default=None, description="HIGH/MEDIUM/LOW rolled up from severity")
    field_name: str | None = None
    message: str
    reason: str | None = Field(default=None, description="Business risk explanation")
    suggestion: str | None = Field(default=None, description="Actionable remediation")
    source_doc_type: str | None = None
    target_doc_type: str | None = None
    source_value: str | None = None
    target_value: str | None = None
    evidence_snippet: str | None = None

    model_config = {"from_attributes": True}
