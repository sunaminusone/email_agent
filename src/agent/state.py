"""Agent loop state: tracks per-group routing + execution outcomes.

The agent iterates over IntentGroups, routing and executing each independently.
GroupOutcome captures the result for one group; AgentState aggregates all
outcomes and exposes helpers used by the service layer loop.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.common.execution_models import ExecutionResult
from src.common.models import GroupDemand, IntentGroup
from src.routing.models import ClarificationPayload, DialogueActResult, RouteDecision


GroupStatus = Literal["resolved", "needs_clarification", "needs_handoff"]


class GroupOutcome(BaseModel):
    """Result of routing + executing a single IntentGroup."""

    model_config = ConfigDict(extra="forbid")

    group: IntentGroup
    scoped_demand: GroupDemand | None = None
    action: str = "execute"
    route_decision: RouteDecision = Field(default_factory=RouteDecision)
    execution_result: ExecutionResult = Field(default_factory=ExecutionResult)
    status: GroupStatus = "resolved"


class AgentState(BaseModel):
    """Accumulated state across all intent groups in a single turn."""

    model_config = ConfigDict(extra="forbid")

    outcomes: list[GroupOutcome] = Field(default_factory=list)

    # --- Queries ---

    @property
    def resolved_outcomes(self) -> list[GroupOutcome]:
        return [o for o in self.outcomes if o.status == "resolved"]

    @property
    def clarification_outcomes(self) -> list[GroupOutcome]:
        return [o for o in self.outcomes if o.status == "needs_clarification"]

    @property
    def handoff_outcomes(self) -> list[GroupOutcome]:
        return [o for o in self.outcomes if o.status == "needs_handoff"]

    @property
    def has_any_execution(self) -> bool:
        return any(
            o.action == "execute" and o.execution_result.executed_calls
            for o in self.outcomes
        )

    @property
    def merged_execution_result(self) -> ExecutionResult:
        """Merge all resolved execution results into one for response rendering."""
        all_calls = []
        for outcome in self.resolved_outcomes:
            all_calls.extend(outcome.execution_result.executed_calls)

        if not all_calls:
            return ExecutionResult(
                final_status="empty",
                reason="No executed calls across all intent groups.",
            )

        statuses = [outcome.execution_result.final_status for outcome in self.resolved_outcomes]
        if all(s == "ok" for s in statuses):
            final_status = "ok"
        elif any(s == "ok" for s in statuses):
            final_status = "partial"
        elif any(s == "error" for s in statuses):
            final_status = "error"
        else:
            final_status = "empty"

        reasons = [o.execution_result.reason for o in self.resolved_outcomes if o.execution_result.reason]
        return ExecutionResult(
            executed_calls=all_calls,
            final_status=final_status,
            reason="; ".join(reasons),
            iteration_count=sum(
                outcome.execution_result.iteration_count
                for outcome in self.resolved_outcomes
            ),
        )

    @property
    def primary_route_decision(self) -> RouteDecision:
        """Pick the most representative route decision for the overall turn.

        Priority: handoff > clarify > execute > respond.
        When some groups executed and others need clarification, the overall
        action is still "execute" — response layer handles the mixed case.
        """
        if self.handoff_outcomes:
            return self.handoff_outcomes[0].route_decision

        if not self.resolved_outcomes and self.clarification_outcomes:
            return self.clarification_outcomes[0].route_decision

        for outcome in self.outcomes:
            if outcome.action == "execute":
                return outcome.route_decision

        return self.outcomes[0].route_decision if self.outcomes else RouteDecision()

    @property
    def primary_clarification(self) -> ClarificationPayload | None:
        if self.clarification_outcomes:
            return self.clarification_outcomes[0].route_decision.clarification
        return None

    @property
    def primary_dialogue_act(self) -> DialogueActResult:
        return self.primary_route_decision.dialogue_act

    @property
    def overall_action(self) -> str:
        """Determine the overall turn action from group outcomes.

        Rules:
        - Any handoff → handoff (safety takes priority)
        - All clarify → clarify
        - Mix of resolved + clarify → execute (partial answer + clarification)
        - All resolved → execute or respond
        """
        if self.handoff_outcomes:
            return "handoff"
        if not self.resolved_outcomes and self.clarification_outcomes:
            return "clarify"
        if self.resolved_outcomes and self.clarification_outcomes:
            return "execute"
        if self.resolved_outcomes:
            actions = [o.action for o in self.resolved_outcomes]
            if "execute" in actions:
                return "execute"
            return "respond"
        return "respond"

    def record(
        self,
        group: IntentGroup,
        route_decision: RouteDecision,
        execution_result: ExecutionResult,
        status: GroupStatus = "resolved",
        scoped_demand: GroupDemand | None = None,
    ) -> None:
        self.outcomes.append(GroupOutcome(
            group=group,
            scoped_demand=scoped_demand,
            action=route_decision.action,
            route_decision=route_decision,
            execution_result=execution_result,
            status=status,
        ))

    def debug_summary(self) -> dict[str, Any]:
        return {
            "total_groups": len(self.outcomes),
            "resolved": len(self.resolved_outcomes),
            "needs_clarification": len(self.clarification_outcomes),
            "needs_handoff": len(self.handoff_outcomes),
            "overall_action": self.overall_action,
            "groups": [
                {
                    "intent": o.group.intent,
                    "action": o.action,
                    "status": o.status,
                    "object_type": o.group.object_type,
                    "object_identifier": o.group.object_identifier,
                }
                for o in self.outcomes
            ],
        }
