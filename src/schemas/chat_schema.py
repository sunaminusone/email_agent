# api输入输出层
# 前后端交互 负责接收用户当前问题、历史对话、附件，并把最终返回结果包装给前端。
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.schemas.agent_context_schema import AgentContext
from src.schemas.parser_schema import ParsedResult
from src.schemas.plan_schema import ExecutionPlan, ExecutionRun
from src.schemas.response_schema import AtomicContentBlock, FinalResponse, ResponseResolution
from src.schemas.routing_schema import RouteDecision

# 用于封装用户发来的消息
class ChatMessage(BaseModel):
    role: str = Field(default="user", description="Conversation role, e.g. user or assistant")
    content: str = Field(..., description="Message content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional message metadata")

# 用于封装用户发来的附件
class AttachmentPayload(BaseModel):
    file_name: str = Field(..., description="Attachment file name")
    file_type: Optional[str] = Field(default=None, description="MIME type or logical type")
    content: Optional[str] = Field(default=None, description="Optional plain-text attachment content")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional attachment metadata")

# 前端 / API 调用时传进来的请求体
class AgentRequest(BaseModel):
    thread_id: Optional[str] = Field(default=None, description="Stable conversation or thread identifier")
    user_query: str = Field(..., min_length=1, description="Current user message")
    conversation_history: List[ChatMessage] = Field(default_factory=list)
    attachments: List[AttachmentPayload] = Field(default_factory=list)

# 返回的response
class AgentPrototypeResponse(BaseModel):
    parsed: ParsedResult
    agent_input: AgentContext
    route: Optional[RouteDecision] = None
    suggested_workflow: List[str] = Field(default_factory=list)
    reply_preview: str = Field(default="")
    execution_plan: Optional[ExecutionPlan] = None
    execution_run: Optional[ExecutionRun] = None
    response_resolution: Optional[ResponseResolution] = None
    response_topic: str = Field(default="")
    response_content_blocks: List[AtomicContentBlock] = Field(default_factory=list)
    response_content_summary: str = Field(default="")
    response_path: str = Field(default="")
    legacy_fallback_used: bool = Field(default=False)
    legacy_fallback_route: str = Field(default="")
    legacy_fallback_responder: str = Field(default="")
    legacy_fallback_reason: str = Field(default="")
    final_response: Optional[FinalResponse] = None
    assistant_message: Dict[str, Any] = Field(default_factory=dict)

'''
前端按 chat_schema.AgentRequest 把消息发进来
后端调用 parser chain
parser chain 按 parser_schema.ParsedResult 输出结构化结果
后端再把它包装成 chat_schema.AgentPrototypeResponse 返回给前端
'''
