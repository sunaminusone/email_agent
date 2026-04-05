from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


class FinalResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    message: str = Field(default="", description="The assistant's final chat-style reply.")
    response_type: str = Field(
        default="answer",
        description="High-level reply type such as answer, clarification, handoff, or status_update.",
    )
    needs_human_handoff: bool = Field(
        default=False,
        description="Whether the case should be handed off to a human after this response.",
    )
    missing_information_requested: List[str] = Field(
        default_factory=list,
        description="Only the missing details explicitly requested in the reply.",
    )
    grounded_action_types: List[str] = Field(
        default_factory=list,
        description="Execution action types that materially supported the response.",
    )


class ResponseTopic(str, Enum):
    TECHNICAL_DOC = "technical_doc"
    COMMERCIAL_QUOTE = "commercial_quote"
    PRODUCT_INFO = "product_info"
    DOCUMENT_DELIVERY = "document_delivery"
    CLARIFICATION = "clarification"
    OPERATIONAL_STATUS = "operational_status"
    WORKFLOW_STATUS = "workflow_status"
    HANDOFF = "handoff"
    GENERAL_CHAT = "general_chat"


class AtomicContentBlock(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    kind: str = Field(default="summary", description="Atomic content block kind such as product_identity, price, lead_time, or documents.")
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured grounded payload for renderers to transform into final language.",
    )
    text: str = Field(
        default="",
        description="Short human-readable preview of the block for debugging and fallback summarization.",
    )


class ResponseResolution(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    topic_type: ResponseTopic = Field(
        default=ResponseTopic.GENERAL_CHAT,
        description="High-level response topic used to select the downstream response chain.",
    )

    answer_focus: str = Field(
        default="summary",
        description="Primary answer focus such as pricing, lead_time, documentation, product_identity, or summary.",
    )
    primary_action_type: str = Field(
        default="",
        description="The action type that should anchor the final reply.",
    )
    supporting_action_types: List[str] = Field(
        default_factory=list,
        description="Other action types that can support the main answer focus.",
    )
    preferred_route_name: str = Field(
        default="",
        description="Responder route name to use for rendering the reply.",
    )
    reply_style: str = Field(
        default="concise",
        description="Reply style profile such as concise, sales, technical, or customer_friendly.",
    )
    content_priority: List[str] = Field(
        default_factory=list,
        description="Ordered content blocks that should appear in the final answer.",
    )
    include_product_identity: bool = False
    include_price: bool = False
    include_lead_time: bool = False
    include_documents: bool = False
    include_technical_context: bool = False
    include_target_antigen: bool = False
    include_application: bool = False
    include_species_reactivity: bool = False
    include_next_step_guidance: bool = False
    should_use_summary_responder: bool = False
    should_ask_clarification: bool = False
    should_suppress_generic_summary: bool = False
    reason: str = Field(default="", description="Short explanation for the selected answer focus.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
