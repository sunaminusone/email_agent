# src/schemas/parser_schema.py
from typing import List, Optional, Literal
from pydantic import BaseModel, Field

# =========================
# 1. Shared literal types
# =========================

PrimaryIntent = Literal[
    "product_inquiry",
    "technical_question",
    "pricing_question",
    "timeline_question",
    "customization_request",
    "documentation_request",
    "shipping_question",
    "troubleshooting",
    "order_support",
    "complaint",
    "follow_up",
    "partnership_request",
    "general_info",
    "unknown",
]

LanguageType = Literal["zh", "en", "other"]
ChannelType = Literal["internal_qa", "email", "chat", "unknown"]
QueryType = Literal["question", "request", "unclear"]
UrgencyType = Literal["low", "medium", "high"]
RiskLevelType = Literal["low", "medium", "high"]


class ParsedContext(BaseModel):
    language: LanguageType = "other"
    channel: ChannelType = "internal_qa"
    primary_intent: PrimaryIntent = "unknown"
    secondary_intents: List[PrimaryIntent] = Field(default_factory=list)
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    query_type: QueryType = "question"
    urgency: UrgencyType = "low"
    risk_level: RiskLevelType = "low"
    needs_human_review: bool = False
    reasoning_note: str = ""


class Entities(BaseModel):
    product_names: List[str] = Field(default_factory=list)
    catalog_numbers: List[str] = Field(default_factory=list)
    service_names: List[str] = Field(default_factory=list)
    targets: List[str] = Field(default_factory=list)
    species: List[str] = Field(default_factory=list)
    applications: List[str] = Field(default_factory=list)
    order_numbers: List[str] = Field(default_factory=list)
    document_names: List[str] = Field(default_factory=list)
    company_names: List[str] = Field(default_factory=list)


class RequestFlags(BaseModel):
    needs_price: bool = False
    needs_timeline: bool = False
    needs_protocol: bool = False
    needs_customization: bool = False
    needs_order_status: bool = False
    needs_shipping_info: bool = False
    needs_documentation: bool = False
    needs_troubleshooting: bool = False
    needs_quote: bool = False
    needs_availability: bool = False
    needs_recommendation: bool = False
    needs_comparison: bool = False
    needs_invoice: bool = False
    needs_refund_or_cancellation: bool = False
    needs_sample: bool = False
    needs_regulatory_info: bool = False


class Constraints(BaseModel):
    budget: Optional[str] = None
    timeline_requirement: Optional[str] = None
    destination: Optional[str] = None
    quantity: Optional[str] = None
    grade_or_quality: Optional[str] = None
    usage_context: Optional[str] = None
    format_or_size: Optional[str] = None
    comparison_target: Optional[str] = None
    preferred_supplier_or_brand: Optional[str] = None


class OpenSlots(BaseModel):
    customer_goal: Optional[str] = None
    experiment_type: Optional[str] = None
    pain_point: Optional[str] = None
    requested_action: Optional[str] = None
    referenced_prior_context: Optional[str] = None
    delivery_or_logistics_note: Optional[str] = None
    regulatory_or_compliance_note: Optional[str] = None
    other_notes: List[str] = Field(default_factory=list)


class RetrievalHints(BaseModel):
    keywords: List[str] = Field(default_factory=list)
    expanded_queries: List[str] = Field(default_factory=list)
    filters: List[str] = Field(default_factory=list)


class ToolHints(BaseModel):
    suggested_tools: List[str] = Field(default_factory=list)
    requires_database_lookup: bool = False
    requires_file_lookup: bool = False
    requires_order_system: bool = False


class ParsedResult(BaseModel):
    normalized_query: str = ""
    context: ParsedContext = Field(default_factory=ParsedContext)
    entities: Entities = Field(default_factory=Entities)
    request_flags: RequestFlags = Field(default_factory=RequestFlags)
    constraints: Constraints = Field(default_factory=Constraints)
    open_slots: OpenSlots = Field(default_factory=OpenSlots)
    retrieval_hints: RetrievalHints = Field(default_factory=RetrievalHints)
    tool_hints: ToolHints = Field(default_factory=ToolHints)
    missing_information: List[str] = Field(default_factory=list)
    extra_instructions: Optional[str] = None
