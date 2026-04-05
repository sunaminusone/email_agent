from typing import List

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.enums import (
    BusinessLine,
    ContinuityMode,
    EngagementType,
    RouteName,
    RoutePhase,
)
from .payload_schema import PersistedSessionPayload, TurnResolution


class RoutingMemory(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    active_route: RouteName | None = Field(default=None, description="Route currently in progress for this thread")
    pending_route_after_clarification: RouteName | None = Field(
        default=None,
        description="Business route to resume once the user provides missing clarification details",
    )
    active_secondary_routes: List[RouteName] = Field(default_factory=list)
    route_phase: RoutePhase = Field(default="unknown")
    continuity_mode: ContinuityMode = Field(default="unknown")
    continuity_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    should_stick_to_active_route: bool = Field(default=False)
    should_resume_pending_route: bool = Field(default=False)
    last_assistant_prompt_type: str = Field(default="", description="High-level label like clarification_request or order_followup")
    active_business_line: str = Field(default="")
    active_engagement_type: str = Field(default="")
    carried_missing_information: List[str] = Field(default_factory=list)
    pending_identifiers: List[str] = Field(default_factory=list)
    session_payload: PersistedSessionPayload = Field(default_factory=PersistedSessionPayload)
    turn_resolution: TurnResolution = Field(default_factory=TurnResolution)
    state_reason: str = Field(default="", description="Short explanation for why the state was inferred")


class RouteDecision(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    route_name: RouteName = Field(..., description="Primary route selected for this request")
    secondary_routes: List[RouteName] = Field(default_factory=list, description="Secondary routes detected in the same message")
    business_line: BusinessLine = Field(default="unknown")
    engagement_type: EngagementType = Field(default="unknown")
    route_confidence: float = Field(..., ge=0.0, le=1.0)
    business_goal: str = Field(default="", description="Short statement of what the agent should achieve next")
    reason: str = Field(default="", description="Short factual reason tied to the agent input")
    required_capabilities: List[str] = Field(default_factory=list)
    recommended_next_steps: List[str] = Field(default_factory=list)
    missing_information_to_request: List[str] = Field(default_factory=list)
    should_write_draft: bool = Field(default=True)
    should_retrieve_knowledge: bool = Field(default=False)
    should_call_tools: bool = Field(default=False)
    should_escalate_to_human: bool = Field(default=False)
