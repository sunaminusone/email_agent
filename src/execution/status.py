from __future__ import annotations


STATUS_PRIORITY = {
    "error": 4,
    "partial": 3,
    "ok": 2,
    "empty": 1,
}


def final_status_for_calls(statuses: list[str]) -> str:
    if not statuses:
        return "empty"
    if any(status == "error" for status in statuses):
        return "error"
    if any(status == "partial" for status in statuses):
        return "partial"
    if any(status == "ok" for status in statuses):
        return "ok"
    return "empty"
