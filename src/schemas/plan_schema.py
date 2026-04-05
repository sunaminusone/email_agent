from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field

from src.schemas.enums import ActionMode, ActionType


class PlannedAction(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    action_id: str = Field(default="")
    action_type: ActionType
    title: str = Field(default="")
    description: str = Field(default="")
    mode: ActionMode = Field(default="primary")
    blocking: bool = Field(default=True)
    condition: str = Field(default="")
    depends_on: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    plan_goal: str = Field(default="")
    planning_reason: str = Field(default="")
    primary_route: str = Field(default="")
    secondary_routes: List[str] = Field(default_factory=list)
    task_pool_considered: List[ActionType] = Field(default_factory=list)
    actions: List[PlannedAction] = Field(default_factory=list)


class ExecutedAction(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    action_id: str = Field(default="")
    action_type: ActionType
    status: str = Field(default="pending")
    summary: str = Field(default="")
    output: Dict[str, Any] = Field(default_factory=dict)


class ExecutionRun(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    plan_goal: str = Field(default="")
    overall_status: str = Field(default="pending")
    executed_actions: List[ExecutedAction] = Field(default_factory=list)
