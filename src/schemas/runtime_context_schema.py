from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .agent_context_schema import AgentContext
from .routing_schema import RouteDecision


class ConversationTurn(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    role: str = Field(default="user")
    content: str = Field(default="")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConversationMemory(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    thread_id: Optional[str] = None
    source: str = Field(default="conversation_history")
    turns: List[ConversationTurn] = Field(default_factory=list)
    route_state: Dict[str, Any] = Field(default_factory=dict)
    recent_summary: str = Field(default="")
    updated_at: str = Field(default="")


class UserPreference(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    source: str = Field(default="database")
    lookup_status: str = Field(default="unavailable")
    preferred_language: Optional[str] = None
    preferred_channel: Optional[str] = None
    preferred_business_line: Optional[str] = None
    known_company_names: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


class KnowledgeSnippet(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    snippet_type: str = Field(default="knowledge")
    title: str = Field(default="")
    source_path: str = Field(default="")
    document_type: str = Field(default="")
    score: float = 0.0
    content_preview: str = Field(default="")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeContext(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    source: str = Field(default="rag")
    lookup_status: str = Field(default="not_requested")
    snippets: List[KnowledgeSnippet] = Field(default_factory=list)


class RuntimeContext(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    agent_context: AgentContext
    conversation_memory: ConversationMemory = Field(default_factory=ConversationMemory)
    user_preference: UserPreference = Field(default_factory=UserPreference)
    knowledge_context: KnowledgeContext = Field(default_factory=KnowledgeContext)


class RoutedRuntimeContext(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    runtime_context: RuntimeContext
    route: RouteDecision
