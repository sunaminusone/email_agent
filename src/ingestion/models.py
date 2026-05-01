from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from src.common.models import (
    IntentGroup,
    SourceAttribution as CommonSourceAttribution,
    ValueSignal as CommonValueSignal,
)
from src.memory.models import ClarificationMemory, MemoryContext, MemoryContribution, ThreadMemory


class _IngestionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


RecencyType = Literal["CURRENT_TURN", "CONTEXTUAL"]
SourceType = Literal["deterministic", "parser", "attachment", "recent_object", "pending_option"]


SEMANTIC_INTENT_VALUES: tuple[str, ...] = (
    "product_inquiry",
    "technical_question",
    "workflow_question",
    "model_support_question",
    "service_plan_question",
    "pricing_question",
    "timeline_question",
    "customization_request",
    "documentation_request",
    "shipping_question",
    "troubleshooting",
    "order_support",
    "complaint",
    "follow_up",
    "general_info",
    "unknown",
)


class SourceAttribution(CommonSourceAttribution):
    pass


class ValueSignal(CommonValueSignal):
    attribution: SourceAttribution = Field(default_factory=SourceAttribution)


class EntitySpan(_IngestionModel):
    text: str = ""
    raw: str = ""
    normalized_value: str | None = None
    start: int = Field(default=-1, ge=-1)
    end: int = Field(default=-1, ge=-1)
    attribution: SourceAttribution = Field(default_factory=SourceAttribution)


class ParserEntityOutputSpan(_IngestionModel):
    text: str = ""
    raw: str = ""
    start: int = Field(default=-1, ge=-1)
    end: int = Field(default=-1, ge=-1)


class AttributeConstraint(_IngestionModel):
    attribute: str = ""
    operator: str = "equals"
    value: str = ""
    raw: str = ""
    attribution: SourceAttribution = Field(default_factory=SourceAttribution)


class TurnCore(_IngestionModel):
    thread_id: str = ""
    raw_query: str = ""
    normalized_query: str = ""
    language: str = "other"
    channel: str = "internal_qa"


class ParserContext(_IngestionModel):
    language: str = "other"
    channel: str = "internal_qa"
    semantic_intent: str = "unknown"
    intent_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    query_type: str = "question"
    urgency: str = "low"
    risk_level: str = "low"
    needs_human_review: bool = False
    reasoning_note: str = ""
    dialogue_act_hint: str = "inquiry"


class ParserRequestFlags(_IngestionModel):
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


class ParserConstraints(_IngestionModel):
    budget: str | None = None
    timeline_requirement: str | None = None
    destination: str | None = None
    quantity: str | None = None
    grade_or_quality: str | None = None
    usage_context: str | None = None
    format_or_size: str | None = None
    comparison_target: str | None = None
    preferred_supplier_or_brand: str | None = None


class ParserOpenSlots(_IngestionModel):
    customer_goal: str | None = None
    experiment_type: str | None = None
    pain_point: str | None = None
    requested_action: str | None = None
    referenced_prior_context: str | None = None
    delivery_or_logistics_note: str | None = None
    regulatory_or_compliance_note: str | None = None
    other_notes: list[str] = Field(default_factory=list)


class ParserRetrievalHints(_IngestionModel):
    keywords: list[str] = Field(default_factory=list)
    expanded_queries: list[str] = Field(default_factory=list)
    filters: list[str] = Field(default_factory=list)


class ParserEntitySignals(_IngestionModel):
    product_names: list[EntitySpan] = Field(default_factory=list)
    catalog_numbers: list[EntitySpan] = Field(default_factory=list)
    service_names: list[EntitySpan] = Field(default_factory=list)
    targets: list[EntitySpan] = Field(default_factory=list)
    species: list[EntitySpan] = Field(default_factory=list)
    applications: list[EntitySpan] = Field(default_factory=list)
    isotypes: list[EntitySpan] = Field(default_factory=list)
    costim_domains: list[EntitySpan] = Field(default_factory=list)
    car_t_groups: list[EntitySpan] = Field(default_factory=list)
    order_numbers: list[EntitySpan] = Field(default_factory=list)
    invoice_numbers: list[EntitySpan] = Field(default_factory=list)
    document_names: list[EntitySpan] = Field(default_factory=list)
    company_names: list[EntitySpan] = Field(default_factory=list)
    customer_names: list[EntitySpan] = Field(default_factory=list)


class ParserOutputEntities(_IngestionModel):
    product_names: list[ParserEntityOutputSpan] = Field(default_factory=list)
    catalog_numbers: list[ParserEntityOutputSpan] = Field(default_factory=list)
    service_names: list[ParserEntityOutputSpan] = Field(default_factory=list)
    targets: list[ParserEntityOutputSpan] = Field(default_factory=list)
    species: list[ParserEntityOutputSpan] = Field(default_factory=list)
    applications: list[ParserEntityOutputSpan] = Field(default_factory=list)
    isotypes: list[ParserEntityOutputSpan] = Field(default_factory=list)
    costim_domains: list[ParserEntityOutputSpan] = Field(default_factory=list)
    car_t_groups: list[ParserEntityOutputSpan] = Field(default_factory=list)
    order_numbers: list[ParserEntityOutputSpan] = Field(default_factory=list)
    invoice_numbers: list[ParserEntityOutputSpan] = Field(default_factory=list)
    document_names: list[ParserEntityOutputSpan] = Field(default_factory=list)
    company_names: list[ParserEntityOutputSpan] = Field(default_factory=list)
    customer_names: list[ParserEntityOutputSpan] = Field(default_factory=list)


class SelectionResolution(_IngestionModel):
    """LLM-resolved selection when the user responds to a prior clarification."""
    selected_index: int | None = None
    selected_value: str = ""
    selection_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    carries_new_intent: bool = False
    reason: str = ""


class ParserSignals(_IngestionModel):
    context: ParserContext = Field(default_factory=ParserContext)
    entities: ParserEntitySignals = Field(default_factory=ParserEntitySignals)
    request_flags: ParserRequestFlags = Field(default_factory=ParserRequestFlags)
    constraints: ParserConstraints = Field(default_factory=ParserConstraints)
    open_slots: ParserOpenSlots = Field(default_factory=ParserOpenSlots)
    retrieval_hints: ParserRetrievalHints = Field(default_factory=ParserRetrievalHints)
    missing_information: list[str] = Field(default_factory=list)
    extra_instructions: str | None = None
    selection_resolution: SelectionResolution | None = None
    asked_focus: str | None = None


class ParserOutput(_IngestionModel):
    normalized_query: str = ""
    context: ParserContext = Field(default_factory=ParserContext)
    entities: ParserOutputEntities = Field(default_factory=ParserOutputEntities)
    request_flags: ParserRequestFlags = Field(default_factory=ParserRequestFlags)
    constraints: ParserConstraints = Field(default_factory=ParserConstraints)
    open_slots: ParserOpenSlots = Field(default_factory=ParserOpenSlots)
    retrieval_hints: ParserRetrievalHints = Field(default_factory=ParserRetrievalHints)
    missing_information: list[str] = Field(default_factory=list)
    extra_instructions: str | None = None
    selection_resolution: SelectionResolution | None = None
    asked_focus: str | None = None


class DeterministicSignals(_IngestionModel):
    catalog_numbers: list[EntitySpan] = Field(default_factory=list)
    order_numbers: list[EntitySpan] = Field(default_factory=list)
    invoice_numbers: list[EntitySpan] = Field(default_factory=list)
    ambiguous_identifiers: list[ValueSignal] = Field(default_factory=list)
    document_types: list[ValueSignal] = Field(default_factory=list)


ReferenceMode = Literal["active", "other", "first", "second", "previous", "all", "none"]


class ReferenceSignals(_IngestionModel):
    is_context_dependent: bool = False
    reference_mode: ReferenceMode = "none"
    referenced_prior_context: ValueSignal | None = None
    attribute_constraints: list[AttributeConstraint] = Field(default_factory=list)
    requires_active_context_for_safe_resolution: bool = False


class AttachmentPointer(_IngestionModel):
    file_name: str = ""
    file_type: str = ""
    attachment_id: str = ""
    storage_uri: str = ""
    content_type: str = ""
    size_bytes: int | None = Field(default=None, ge=0)


class AttachmentSignals(_IngestionModel):
    has_attachments: bool = False
    attachment_count: int = 0
    attachment_names: list[str] = Field(default_factory=list)
    attachment_types: list[str] = Field(default_factory=list)
    attachment_ids: list[str] = Field(default_factory=list)
    storage_uris: list[str] = Field(default_factory=list)
    attachments: list[AttachmentPointer] = Field(default_factory=list)


class TurnSignals(_IngestionModel):
    parser_signals: ParserSignals = Field(default_factory=ParserSignals)
    deterministic_signals: DeterministicSignals = Field(default_factory=DeterministicSignals)
    reference_signals: ReferenceSignals = Field(default_factory=ReferenceSignals)
    attachment_signals: AttachmentSignals = Field(default_factory=AttachmentSignals)


class IngestionBundle(_IngestionModel):
    turn_core: TurnCore = Field(default_factory=TurnCore)
    turn_signals: TurnSignals = Field(default_factory=TurnSignals)
    memory_context: MemoryContext = Field(default_factory=MemoryContext)

    @property
    def thread_memory(self) -> ThreadMemory:
        return self.memory_context.snapshot.thread_memory

    @property
    def clarification_memory(self) -> ClarificationMemory:
        return self.memory_context.snapshot.clarification_memory

    @property
    def has_recent_memory_context(self) -> bool:
        return bool(self.memory_context.recent_objects_by_relevance)


def build_ingestion_memory_contribution(
    intent_groups: list[IntentGroup],
) -> MemoryContribution:
    return MemoryContribution(
        source="ingestion",
        intent_groups=list(intent_groups),
        reason=f"ingestion: assembled {len(intent_groups)} intent group(s)",
    )
