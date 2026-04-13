from __future__ import annotations

from typing import Any

from src.common.execution_models import ExecutedToolCall
from src.common.messages import get_message
from src.response.models import ContentBlock, ResponseInput


def build_content_blocks(response_input: ResponseInput) -> list[ContentBlock]:
    locale = response_input.locale
    blocks: list[ContentBlock] = []

    object_block = _build_object_summary_block(response_input, locale)
    if object_block is not None:
        blocks.append(object_block)

    if response_input.action == "clarify":
        blocks.extend(_build_clarification_blocks(response_input, locale))
        return blocks

    if response_input.action == "handoff":
        blocks.append(
            ContentBlock(
                block_type="handoff_notice",
                title=get_message("block_title_handoff", locale),
                body=get_message("block_body_handoff", locale),
                data={"reason": response_input.execution_result.reason},
            )
        )
        return blocks

    # When group_outcomes are available, tag each block with its source group
    if response_input.group_outcomes:
        blocks.extend(_build_blocks_from_outcomes(response_input))
    else:
        for executed_call in response_input.execution_result.executed_calls:
            blocks.extend(_build_blocks_for_call(executed_call))

    return blocks


def _build_blocks_from_outcomes(response_input: ResponseInput) -> list[ContentBlock]:
    """Build content blocks from agent loop outcomes, tagging each with its group."""
    blocks: list[ContentBlock] = []
    for outcome in response_input.group_outcomes:
        if outcome.status != "resolved":
            continue
        group = outcome.group
        group_tag = {
            "intent": group.intent,
            "object_type": group.object_type,
            "object_identifier": group.object_identifier,
        }
        source_demand = _lookup_group_demand(response_input, group)
        for executed_call in outcome.execution_result.executed_calls:
            for block in _build_blocks_for_call(executed_call):
                block.data.setdefault("source_group", group_tag)
                if source_demand:
                    block.data.setdefault("source_demand", source_demand)
                blocks.append(block)
    return blocks


def _lookup_group_demand(response_input: ResponseInput, group) -> dict[str, Any]:
    demand_profile = response_input.demand_profile
    if demand_profile is None:
        return {}
    for group_demand in demand_profile.group_demands:
        if (
            group_demand.intent == group.intent
            and group_demand.object_type == group.object_type
            and group_demand.object_identifier == group.object_identifier
            and set(group_demand.request_flags) == set(group.request_flags)
        ):
            return {
                "primary_demand": group_demand.primary_demand,
                "secondary_demands": list(group_demand.secondary_demands),
                "request_flags": list(group_demand.request_flags),
            }
    return {}


def _build_object_summary_block(response_input: ResponseInput, locale: str) -> ContentBlock | None:
    resolved_object = None
    if response_input.resolved_object_state is not None:
        resolved_object = (
            response_input.resolved_object_state.primary_object
            or response_input.resolved_object_state.active_object
        )
    if resolved_object is None:
        return None

    body_parts = [
        part
        for part in [
            resolved_object.display_name or resolved_object.canonical_value,
            resolved_object.identifier,
            resolved_object.business_line,
        ]
        if part
    ]
    if not body_parts:
        return None

    return ContentBlock(
        block_type="object_summary",
        title=get_message("block_title_resolved_object", locale),
        body=" | ".join(body_parts),
        data={
            "object_type": resolved_object.object_type,
            "display_name": resolved_object.display_name,
            "canonical_value": resolved_object.canonical_value,
            "identifier": resolved_object.identifier,
            "business_line": resolved_object.business_line,
        },
    )


def _build_clarification_blocks(response_input: ResponseInput, locale: str) -> list[ContentBlock]:
    clarification = response_input.clarification
    if clarification is None:
        return []
    return [
        ContentBlock(
            block_type="clarification_options",
            title=get_message("block_title_clarification", locale),
            body=clarification.prompt or get_message("block_body_clarification_default", locale),
            data={
                "kind": clarification.kind,
                "reason": clarification.reason,
                "missing_information": list(clarification.missing_information),
                "options": [option.model_dump(mode="json") for option in clarification.options],
            },
        )
    ]


def _build_blocks_for_call(executed_call: ExecutedToolCall) -> list[ContentBlock]:
    result = executed_call.result
    if result is None:
        return []

    blocks: list[ContentBlock] = []
    tool_name = executed_call.tool_name

    facts_block = _build_structured_facts_block(tool_name, result.structured_facts, result.primary_records)
    if facts_block is not None:
        blocks.append(facts_block)

    snippet_block = _build_technical_snippets_block(tool_name, result.unstructured_snippets)
    if snippet_block is not None:
        blocks.append(snippet_block)

    artifact_block = _build_artifacts_block(tool_name, result.artifacts)
    if artifact_block is not None:
        blocks.append(artifact_block)

    supporting_block = _build_supporting_records_block(tool_name, result.supporting_records)
    if supporting_block is not None:
        blocks.append(supporting_block)

    return blocks


def _build_structured_facts_block(
    tool_name: str,
    structured_facts: dict[str, Any],
    primary_records: list[dict[str, Any]],
) -> ContentBlock | None:
    facts = dict(structured_facts)
    if primary_records:
        facts.setdefault("matches", list(primary_records[:5]))
    if not facts:
        return None

    summary_parts: list[str] = []
    labels = [_best_label(record) for record in primary_records[:3]]
    labels = [label for label in labels if label]
    if labels:
        summary_parts.append(", ".join(labels))

    for key, value in facts.items():
        if key == "matches":
            continue
        formatted = _format_scalar(value)
        if formatted:
            summary_parts.append(f"{key}: {formatted}")
        if len(summary_parts) >= 4:
            break

    return ContentBlock(
        block_type="structured_facts",
        title=tool_name,
        body=". ".join(summary_parts),
        data=facts,
    )


def _build_technical_snippets_block(tool_name: str, snippets: list[dict[str, Any]]) -> ContentBlock | None:
    if not snippets:
        return None

    previews: list[str] = []
    for snippet in snippets[:5]:
        content = str(snippet.get("content") or snippet.get("content_preview") or "").strip()
        title = str(snippet.get("title") or snippet.get("chunk_label") or "").strip()
        section = str(snippet.get("section_type") or "").strip()

        if not content:
            continue

        # Structure each snippet with its source context
        if title and section:
            previews.append(f"[{title} ({section})] {content}")
        elif title:
            previews.append(f"[{title}] {content}")
        else:
            previews.append(content)

    if not previews:
        return None

    return ContentBlock(
        block_type="technical_snippets",
        title=tool_name,
        body="\n\n".join(previews),
        data={"snippets": list(snippets[:5])},
    )


def _build_artifacts_block(tool_name: str, artifacts: list[dict[str, Any]]) -> ContentBlock | None:
    if not artifacts:
        return None

    names = []
    for artifact in artifacts[:5]:
        name = str(
            artifact.get("file_name")
            or artifact.get("document_name")
            or artifact.get("title")
            or artifact.get("name")
            or ""
        ).strip()
        if name:
            names.append(name)

    if not names:
        return None

    return ContentBlock(
        block_type="document_artifacts",
        title=tool_name,
        body=", ".join(names),
        data={"artifacts": list(artifacts[:5])},
    )


def _build_supporting_records_block(tool_name: str, supporting_records: list[dict[str, Any]]) -> ContentBlock | None:
    if not supporting_records:
        return None

    labels = [_best_label(record) for record in supporting_records[:3]]
    labels = [label for label in labels if label]
    if not labels:
        return None

    return ContentBlock(
        block_type="supporting_records",
        title=tool_name,
        body=", ".join(labels),
        data={"supporting_records": list(supporting_records[:5])},
    )


def _best_label(record: dict[str, Any]) -> str:
    for key in (
        "display_name",
        "name",
        "catalog_no",
        "catalog_number",
        "service_name",
        "order_no",
        "invoice_no",
        "tracking_no",
        "file_name",
        "document_name",
    ):
        value = str(record.get(key) or "").strip()
        if value:
            return value
    return ""


def _format_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        formatted_items = [str(item).strip() for item in value[:3] if str(item).strip()]
        return ", ".join(formatted_items)
    if isinstance(value, dict):
        return ""
    return str(value).strip()
