from __future__ import annotations


def rank_catalog_matches(matches: list[dict], top_k: int) -> list[dict]:
    deduped: list[dict] = []
    seen_ids: set[str] = set()

    for match in sorted(
        matches,
        key=lambda item: (
            -(int(item.get("match_rank") or 0)),
            -(float(item.get("score") or 0.0)),
            str(item.get("catalog_no") or ""),
        ),
    ):
        match_id = str(match.get("id") or "")
        if match_id and match_id in seen_ids:
            continue
        if match_id:
            seen_ids.add(match_id)
        deduped.append(match)
        if len(deduped) >= top_k:
            break

    return deduped
