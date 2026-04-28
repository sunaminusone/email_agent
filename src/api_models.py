from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationMessage(_ApiModel):
    role: str = "user"
    content: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RequestAttachment(_ApiModel):
    file_name: str = ""
    file_type: str = ""
    attachment_id: str = ""
    storage_uri: str = ""
    content_type: str = ""
    size_bytes: int | None = None


class AgentRequest(_ApiModel):
    thread_id: str = ""
    user_query: str
    locale: str = "en"
    conversation_history: list[ConversationMessage] = Field(default_factory=list)
    attachments: list[RequestAttachment] = Field(default_factory=list)


class FinalResponsePayload(_ApiModel):
    message: str = ""
    response_type: str = "answer"
    grounded_action_types: list[str] = Field(default_factory=list)
    missing_information_requested: list[str] = Field(default_factory=list)


class AgentPrototypeResponse(_ApiModel):
    parsed: dict[str, Any] = Field(default_factory=dict)
    agent_input: dict[str, Any] = Field(default_factory=dict)
    route: dict[str, Any] = Field(default_factory=dict)
    suggested_workflow: list[str] = Field(default_factory=list)
    reply_preview: str = ""
    execution_plan: dict[str, Any] = Field(default_factory=dict)
    execution_run: dict[str, Any] = Field(default_factory=dict)
    answer_focus: str = ""
    response_topic: str = ""
    response_content_blocks: list[dict[str, Any]] = Field(default_factory=list)
    response_content_summary: str = ""
    response_path: str = "csr_renderer_direct"
    final_response: FinalResponsePayload = Field(default_factory=FinalResponsePayload)
    assistant_message: dict[str, Any] = Field(default_factory=dict)
