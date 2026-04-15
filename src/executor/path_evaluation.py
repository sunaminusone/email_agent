"""Path evaluation: assess candidate execution paths after tool selection.

Sits between tool_selector.select_tools() and engine.dispatch.
Determines whether the system should execute or clarify.

Three-layer model:
  1. Primary Plan — tool_selector picks the primary tool (upstream).
  2. Readiness Plan — check_readiness evaluates full / degraded / insufficient.
  3. Resolution Plan — find_resolution_provider tries one-step provider lookup.
"""
from __future__ import annotations

import logging

from src.executor.models import (
    CandidatePath,
    ClarificationFromPaths,
    PathEvaluation,
    ToolSelection,
)
from src.tools.models import ToolReadiness
from src.tools.readiness import check_readiness
from src.tools.registry import get_registry_entry, list_registry_entries

logger = logging.getLogger(__name__)

_QUALITY_WEIGHT = {"full": 1.0, "degraded": 0.6, "insufficient": 0.0}


def evaluate_execution_paths(
    selections: list[ToolSelection],
    object_type: str,
    available_params: dict[str, str],
) -> PathEvaluation:
    """Evaluate readiness for each selected tool and produce a PathEvaluation.

    The *object_type* parameter is accepted for interface compatibility but is
    no longer used in readiness evaluation — identifiers are checked directly
    against available_params without object_type dispatch.
    """
    paths: list[CandidatePath] = []

    for sel in selections:
        entry = get_registry_entry(sel.tool_name)
        if entry.capability is None:
            paths.append(CandidatePath(
                tool_name=sel.tool_name,
                readiness=ToolReadiness(
                    tool_name=sel.tool_name,
                    can_execute=True,
                    quality="full",
                    reason="No capability declared; assuming executable.",
                ),
                selection_score=sel.match_score,
                effective_priority=sel.match_score,
                role=sel.role,
            ))
            continue

        readiness = check_readiness(entry.capability, available_params)
        weight = _QUALITY_WEIGHT.get(readiness.quality, 0.0)
        paths.append(CandidatePath(
            tool_name=sel.tool_name,
            readiness=readiness,
            selection_score=sel.match_score,
            effective_priority=round(sel.match_score * weight, 4),
            role=sel.role,
        ))

    executable = [p for p in paths if p.readiness.can_execute]
    blocked = [p for p in paths if not p.readiness.can_execute]

    executable.sort(key=lambda p: -p.effective_priority)
    blocked.sort(key=lambda p: -p.selection_score)

    if executable:
        return PathEvaluation(
            recommended_action="execute",
            executable_paths=executable,
            blocked_paths=blocked,
        )

    clarification_ctx = _build_clarification_context(blocked)
    return PathEvaluation(
        recommended_action="clarify",
        executable_paths=[],
        blocked_paths=blocked,
        clarification_context=clarification_ctx,
    )


def _build_clarification_context(
    blocked_paths: list[CandidatePath],
) -> ClarificationFromPaths:
    """Aggregate missing identifiers from blocked paths."""
    missing_by_path: dict[str, list[str]] = {}
    for path in blocked_paths:
        missing_by_path[path.tool_name] = list(path.readiness.missing_identifiers)
    return ClarificationFromPaths(missing_by_path=missing_by_path)


# ---------------------------------------------------------------------------
# Resolution chain (one-step only)
# ---------------------------------------------------------------------------


def find_resolution_provider(
    path_eval: PathEvaluation,
    available_params: dict[str, str],
) -> str | None:
    """Find a provider tool that can run and whose results may unblock a blocked path.

    Constraints:
    1. Only one level of resolution (no recursion).
    2. Provider must be *full* readiness (no degraded providers).
    3. Provider must not be one of the blocked tools.
    """
    needed_params: set[str] = set()
    for path in path_eval.blocked_paths:
        needed_params.update(path.readiness.missing_identifiers)

    if not needed_params:
        return None

    blocked_tool_names = {p.tool_name for p in path_eval.blocked_paths}

    for entry in list_registry_entries():
        if entry.capability is None:
            continue
        provides = entry.capability.provides_params
        if not provides or not (set(provides) & needed_params):
            continue
        if entry.tool_name in blocked_tool_names:
            continue

        provider_readiness = check_readiness(entry.capability, available_params)
        if provider_readiness.quality == "full":
            logger.info(
                "Resolution chain: %s can provide %s (readiness=%s)",
                entry.tool_name,
                set(provides) & needed_params,
                provider_readiness.quality,
            )
            return entry.tool_name

    return None
