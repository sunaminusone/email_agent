from typing import Any, Callable, Dict

from src.integrations import QuickBooksClient, QuickBooksConfigError
from src.schemas import ExecutedAction
from src.tools.action_utils import make_blocked_action, make_failed_action


DEFAULT_NOT_CONFIGURED_STEP = "Set QB_CLIENT_ID, QB_CLIENT_SECRET, and QB_REDIRECT_URI in .env."
DEFAULT_NOT_CONNECTED_STEP = "Open /qb/connect in the browser and finish the QuickBooks OAuth consent flow."


def execute_quickbooks_lookup(
    *,
    action: Any,
    lookup_mode: str,
    status_key: str,
    request_payload: Dict[str, Any],
    lookup_label: str,
    perform_lookup: Callable[[QuickBooksClient], Dict[str, Any]],
) -> ExecutedAction:
    client = QuickBooksClient()

    if not client.is_configured():
        output = {
            "lookup_mode": lookup_mode,
            **request_payload,
            status_key: "not_configured",
            "next_step": DEFAULT_NOT_CONFIGURED_STEP,
        }
        return make_blocked_action(
            action=action,
            action_type=action.action_type,
            summary=f"QuickBooks {lookup_label} lookup is not configured yet.",
            output=output,
        )

    connection_status = client.get_connection_status()
    if not connection_status.get("connected"):
        output = {
            "lookup_mode": lookup_mode,
            **request_payload,
            status_key: "not_connected",
            "next_step": DEFAULT_NOT_CONNECTED_STEP,
        }
        return make_blocked_action(
            action=action,
            action_type=action.action_type,
            summary=f"QuickBooks {lookup_label} lookup is configured but not connected yet.",
            output=output,
        )

    try:
        output = perform_lookup(client)
        output["lookup_mode"] = lookup_mode
        output[status_key] = output.get("status")
    except QuickBooksConfigError as exc:
        output = {
            "lookup_mode": lookup_mode,
            **request_payload,
            status_key: "error",
            "error": str(exc),
        }
        return make_failed_action(
            action=action,
            action_type=action.action_type,
            summary=f"QuickBooks {lookup_label} lookup could not start.",
            output=output,
        )
    except Exception as exc:
        output = {
            "lookup_mode": lookup_mode,
            **request_payload,
            status_key: "error",
            "error": str(exc),
        }
        return make_failed_action(
            action=action,
            action_type=action.action_type,
            summary=f"QuickBooks returned an error during {lookup_label} lookup.",
            output=output,
        )

    match_count = len(output.get("matches", []))
    return ExecutedAction(
        action_id=action.action_id,
        action_type=action.action_type,
        status="completed" if match_count else "not_found",
        summary=(
            f"Retrieved {match_count} QuickBooks {lookup_label} match(es)."
            if match_count
            else f"No matching QuickBooks {lookup_label} records were found."
        ),
        output=output,
    )
