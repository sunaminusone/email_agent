from __future__ import annotations

from src.schemas import FinalResponse


class RendererUnavailableError(RuntimeError):
    pass


class InsufficientContentError(RendererUnavailableError):
    pass


def answer(message: str, grounded_action_types: list[str]) -> FinalResponse:
    return FinalResponse(
        message=message,
        response_type="answer",
        grounded_action_types=grounded_action_types,
    )
