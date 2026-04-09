from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class DeterministicPayload(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    catalog_numbers: List[str] = Field(default_factory=list)
    invoice_numbers: List[str] = Field(default_factory=list)
    order_numbers: List[str] = Field(default_factory=list)
    document_types: List[str] = Field(default_factory=list)
    quantity: Optional[str] = None
    destination: Optional[str] = None


class InterpretedPayload(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    user_goal: str = Field(default="")
    confirmed_identifier_type: str = Field(default="")
    reference_resolution: str = Field(default="")
    reference_resolutions: List[str] = Field(default_factory=list)


class ReferenceResolution(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    resolved_identifier: str = Field(default="")
    resolved_identifiers: List[str] = Field(default_factory=list)
    resolved_identifier_type: str = Field(default="")
    resolved_display_name: str = Field(default="")
    resolved_business_line: str = Field(default="")
    resolution_mode: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = Field(default="")


class TurnResolution(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    turn_type: str = Field(default="")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    should_reuse_active_route: bool = False
    should_resume_pending_route: bool = False
    should_reuse_active_entity: bool = False
    should_reuse_pending_identifier: bool = False
    should_reset_route_context: bool = False
    payload_usable: bool = False
    payload_usable_fields: List[str] = Field(default_factory=list)
    resolved_identifier: str = Field(default="")
    resolved_identifier_type: str = Field(default="")
    resolved_business_line: str = Field(default="")
    resolved_user_goal: str = Field(default="")
    reason: str = Field(default="")


class ActiveEntityPayload(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    identifier: str = Field(default="")
    identifier_type: str = Field(default="")
    entity_kind: str = Field(default="")
    display_name: str = Field(default="")
    business_line: str = Field(default="")


class PendingClarificationPayload(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    field: str = Field(default="")
    candidate_identifier: str = Field(default="")
    candidate_options: List[str] = Field(default_factory=list)
    question: str = Field(default="")


class PersistedSessionPayload(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    active_entity: ActiveEntityPayload = Field(default_factory=ActiveEntityPayload)
    recent_entities: List[ActiveEntityPayload] = Field(default_factory=list)
    active_service_name: str = Field(default="")
    active_product_name: str = Field(default="")
    active_target: str = Field(default="")
    pending_clarification: PendingClarificationPayload = Field(default_factory=PendingClarificationPayload)
    active_business_line: str = Field(default="")
    last_user_goal: str = Field(default="")
    revealed_attributes: List[str] = Field(default_factory=list)
