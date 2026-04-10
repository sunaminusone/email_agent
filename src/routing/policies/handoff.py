from __future__ import annotations

def decide_handoff(*, risk_level: str, needs_human_review: bool) -> tuple[bool, str]:
    if needs_human_review:
        return True, "Handoff is required because the upstream context explicitly requested human review."
    if risk_level in {"high", "critical"}:
        return True, "Handoff is required because the request risk exceeds the automated routing path."
    return False, ""
