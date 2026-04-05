from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .parser_schema import (
    Constraints,
    Entities,
    OpenSlots,
    ParsedContext,
    RequestFlags,
    RetrievalHints,
    ToolHints,
)
from .payload_schema import (
    DeterministicPayload,
    InterpretedPayload,
    PersistedSessionPayload,
    ReferenceResolution,
    TurnResolution,
)
from .routing_schema import RoutingMemory


class RoutingSignals(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    primary_intent: str = Field(default="unknown")
    secondary_intents: List[str] = Field(default_factory=list)
    risk_level: str = Field(default="low")
    urgency: str = Field(default="low")
    needs_human_review: bool = False
    has_missing_information: bool = False
    requires_clarification: bool = False
    is_pricing_request: bool = False
    is_technical_request: bool = False
    is_order_request: bool = False
    is_shipping_request: bool = False
    is_document_request: bool = False


class ProductLookupKeys(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    product_names: List[str] = Field(default_factory=list)
    catalog_numbers: List[str] = Field(default_factory=list)
    ambiguous_identifiers: List[str] = Field(default_factory=list)
    service_names: List[str] = Field(default_factory=list)
    targets: List[str] = Field(default_factory=list)
    species: List[str] = Field(default_factory=list)
    applications: List[str] = Field(default_factory=list)
    quantity: Optional[str] = None
    destination: Optional[str] = None
    preferred_supplier_or_brand: Optional[str] = None
    grade_or_quality: Optional[str] = None
    format_or_size: Optional[str] = None
    needs_quote: bool = False
    needs_price: bool = False
    needs_availability: bool = False
    needs_timeline: bool = False


class ClarificationState(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    requires_clarification: bool = False
    missing_information: List[str] = Field(default_factory=list)
    blocking_missing_fields: List[str] = Field(default_factory=list)
    optional_missing_fields: List[str] = Field(default_factory=list)


class AttachmentSummary(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    attachment_count: int = 0
    has_attachments: bool = False
    file_names: List[str] = Field(default_factory=list)
    file_types: List[str] = Field(default_factory=list)


class RoutingDebugInfo(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    business_line: str = Field(default="unknown")
    engagement_type: str = Field(default="unknown")
    business_line_scores: Dict[str, int] = Field(default_factory=dict)
    business_line_top: str = Field(default="unknown")
    business_line_second: str = Field(default="unknown")
    business_line_gap: int = 0
    business_line_confidence: str = Field(default="low")
    customization_score: int = 0
    customization_signals: Dict[str, List[str]] = Field(default_factory=dict)
    gray_zone_reasons: List[str] = Field(default_factory=list)
    is_gray_zone: bool = False
    secondary_intents: List[str] = Field(default_factory=list)
    routing_memory: Dict[str, Any] = Field(default_factory=dict)


class AgentContext(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    thread_id: Optional[str] = None
    query: str = Field(default="")
    original_query: str = Field(default="")
    original_email_text: str = Field(default="")
    normalized_query: str = Field(default="")
    effective_query: str = Field(default="")
    retrieval_query: str = Field(default="")
    context: ParsedContext = Field(default_factory=ParsedContext)
    entities: Entities = Field(default_factory=Entities)
    request_flags: RequestFlags = Field(default_factory=RequestFlags)
    constraints: Constraints = Field(default_factory=Constraints)
    open_slots: OpenSlots = Field(default_factory=OpenSlots)
    retrieval_hints: RetrievalHints = Field(default_factory=RetrievalHints)
    tool_hints: ToolHints = Field(default_factory=ToolHints)
    missing_information: List[str] = Field(default_factory=list)
    routing_signals: RoutingSignals = Field(default_factory=RoutingSignals)
    routing_debug: RoutingDebugInfo = Field(default_factory=RoutingDebugInfo)
    deterministic_payload: DeterministicPayload = Field(default_factory=DeterministicPayload)
    interpreted_payload: InterpretedPayload = Field(default_factory=InterpretedPayload)
    reference_resolution: ReferenceResolution = Field(default_factory=ReferenceResolution)
    session_payload: PersistedSessionPayload = Field(default_factory=PersistedSessionPayload)
    turn_resolution: TurnResolution = Field(default_factory=TurnResolution)
    product_lookup_keys: ProductLookupKeys = Field(default_factory=ProductLookupKeys)
    clarification_state: ClarificationState = Field(default_factory=ClarificationState)
    routing_memory: RoutingMemory = Field(default_factory=RoutingMemory)
    attachment_summary: AttachmentSummary = Field(default_factory=AttachmentSummary)
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    extra_instructions: Optional[str] = None
