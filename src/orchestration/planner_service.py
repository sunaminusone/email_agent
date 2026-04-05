from typing import Any, Dict, List

from src.config.routing_config import BLOCKING_ROUTES, ROUTE_DEFAULT_ACTIONS
from src.schemas import AgentContext, ExecutionPlan, PlannedAction, RouteDecision
from src.schemas.enums import ActionType, ActionMode, RouteName

TASK_POOL = [
    ActionType.CLARIFICATION_REQUEST,
    ActionType.RETRIEVE_TECHNICAL_KNOWLEDGE,
    ActionType.LOOKUP_CATALOG_PRODUCT,
    ActionType.LOOKUP_PRICE,
    ActionType.LOOKUP_CUSTOMER,
    ActionType.LOOKUP_DOCUMENT,
    ActionType.LOOKUP_INVOICE,
    ActionType.LOOKUP_ORDER,
    ActionType.LOOKUP_SHIPPING,
    ActionType.PREPARE_CUSTOMIZATION_INTAKE,
    ActionType.ESCALATE_TO_HUMAN,
    ActionType.SUMMARIZE_CASE,
    ActionType.DRAFT_REPLY,
    ActionType.DRAFT_INTERNAL_SUMMARY,
    ActionType.RECORD_SECONDARY_FOLLOWUP,
]


def _new_action(
    action_id: str,
    action_type: str,
    title: str,
    description: str,
    *,
    mode: str = "primary",
    blocking: bool = True,
    condition: str = "",
    depends_on: List[str] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> PlannedAction:
    return PlannedAction(
        action_id=action_id,
        action_type=action_type,
        title=title,
        description=description,
        mode=ActionMode(mode),
        blocking=blocking,
        condition=condition,
        depends_on=depends_on or [],
        metadata=metadata or {},
    )


def _primary_actions(route: RouteDecision) -> List[PlannedAction]:
    default_actions = ROUTE_DEFAULT_ACTIONS.get(RouteName(route.route_name))
    if default_actions:
        actions = []
        for action in default_actions:
            metadata = dict(action.get("metadata", {}))
            if metadata.pop("include_missing_information", False):
                metadata["missing_information"] = route.missing_information_to_request
            actions.append(
                _new_action(
                    action["action_id"],
                    action["action_type"],
                    action["title"],
                    action["description"],
                    depends_on=action.get("depends_on", []),
                    metadata=metadata,
                )
            )
        return actions

    return [
        _new_action(
            "primary-draft",
            ActionType.DRAFT_REPLY,
            "Draft response",
            "Prepare the next response for the current workflow.",
        ),
    ]


def _secondary_action_for_route(route_name: str, primary_is_blocking: bool, index: int) -> PlannedAction | None:
    suffix = f"secondary-{index}"
    if primary_is_blocking:
        return _new_action(
            suffix,
            ActionType.RECORD_SECONDARY_FOLLOWUP,
            f"Record follow-up for {route_name}",
            "Do not execute this route yet; record it as a follow-up task after the blocking primary route is handled.",
            mode="secondary",
            blocking=False,
            metadata={"secondary_route": route_name, "execution_mode": "deferred"},
        )

    mapping = {
        RouteName.TECHNICAL_RAG: (ActionType.RETRIEVE_TECHNICAL_KNOWLEDGE, "Supplement with technical retrieval", "Run technical retrieval as a supporting step for the mixed-intent request."),
        RouteName.WORKFLOW_AGENT: (ActionType.PREPARE_CUSTOMIZATION_INTAKE, "Supplement with workflow intake", "Prepare workflow intake details as a supporting step."),
        RouteName.PRICING_LOOKUP: (ActionType.LOOKUP_PRICE, "Supplement with price lookup", "Retrieve pricing as a supporting step for the mixed-intent request."),
        RouteName.PRODUCT_LOOKUP: (ActionType.LOOKUP_CATALOG_PRODUCT, "Supplement with product lookup", "Retrieve matching products as a supporting step."),
        RouteName.CUSTOMER_LOOKUP: (ActionType.LOOKUP_CUSTOMER, "Supplement with customer lookup", "Retrieve matching customer or lead details as a supporting step."),
        RouteName.INVOICE_LOOKUP: (ActionType.LOOKUP_INVOICE, "Supplement with invoice lookup", "Retrieve invoice-specific billing details as a supporting step."),
        RouteName.DOCUMENTATION_LOOKUP: (ActionType.LOOKUP_DOCUMENT, "Supplement with document lookup", "Retrieve supporting documents as a supporting step."),
        RouteName.ORDER_SUPPORT: (ActionType.LOOKUP_ORDER, "Supplement with order lookup", "Retrieve order details as a supporting step."),
        RouteName.SHIPPING_SUPPORT: (ActionType.LOOKUP_SHIPPING, "Supplement with shipping lookup", "Retrieve logistics details as a supporting step."),
    }
    action = mapping.get(RouteName(route_name))
    if action is None:
        return None
    action_type, title, description = action
    return _new_action(
        suffix,
        action_type,
        title,
        description,
        mode="secondary",
        blocking=False,
        metadata={"secondary_route": route_name, "execution_mode": "supplemental"},
    )


def build_execution_plan(agent_input: AgentContext, route: RouteDecision) -> ExecutionPlan:
    primary_is_blocking = RouteName(route.route_name) in BLOCKING_ROUTES
    actions = _primary_actions(route)

    if RouteName(route.route_name) not in {
        RouteName.COMMERCIAL_AGENT,
        RouteName.OPERATIONAL_AGENT,
        RouteName.WORKFLOW_AGENT,
    }:
        for index, secondary_route in enumerate(route.secondary_routes, start=1):
            secondary_action = _secondary_action_for_route(secondary_route, primary_is_blocking, index)
            if secondary_action is not None:
                actions.append(secondary_action)

    plan_goal = route.business_goal or "Handle the current request through the selected route."
    planning_reason = route.reason or "The execution plan follows the selected route and any detected secondary routes."
    return ExecutionPlan(
        plan_goal=plan_goal,
        planning_reason=planning_reason,
        primary_route=route.route_name,
        secondary_routes=route.secondary_routes,
        task_pool_considered=TASK_POOL,
        actions=actions,
    )
