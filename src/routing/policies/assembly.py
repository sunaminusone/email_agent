from __future__ import annotations

from src.routing.models import ModalityDecision


def build_result_assembly_policy(
    modality_decision: ModalityDecision,
    selected_tools: list[str],
) -> str:
    if modality_decision.primary_modality == "hybrid" and selected_tools:
        return "Hybrid execution should keep one primary answer spine and merge the rest as supporting material."
    if selected_tools:
        return "The selected tools define the execution-facing answer assembly policy."
    return "No result assembly policy is needed because no executable tools were selected."
