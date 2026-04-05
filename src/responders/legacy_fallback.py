from src.schemas import AgentContext
from src.responders.common import ResponseContext
from src.responders.legacy.commercial_responder import CommercialResponder
from src.responders.legacy.operational_responder import OperationalResponder


LEGACY_RESPONDER_MAP = {
    "commercial_agent": CommercialResponder(),
    "operational_agent": OperationalResponder(),
}


def render_legacy_fallback(agent_input: AgentContext, route, execution_run, response_resolution, action_types):
    responder = LEGACY_RESPONDER_MAP.get(route.route_name)
    if not responder:
        return None

    ctx = ResponseContext(
        agent_input=agent_input,
        route=route,
        execution_run=execution_run,
        response_resolution=response_resolution,
        action_types=action_types,
        language=agent_input.context.language,
        query=agent_input.query.strip(),
    )
    response = responder.render(ctx)
    if response is None:
        return None

    return {
        "response": response,
        "route_name": route.route_name,
        "responder_name": responder.__class__.__name__,
    }
