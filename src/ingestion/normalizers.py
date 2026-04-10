from __future__ import annotations

from typing import Any

from src.ingestion.models import AttachmentPointer, AttachmentSignals, TurnCore


def normalize_query(raw_query: str) -> str:
    return " ".join(str(raw_query or "").strip().split())


def normalize_conversation_history(
    conversation_history: list[dict[str, Any]] | None,
) -> list[dict[str, str]]:
    normalized_history: list[dict[str, str]] = []
    for message in conversation_history or []:
        role = str(message.get("role") or "").strip().lower()
        content = str(message.get("content") or message.get("text") or "").strip()
        if not role and not content:
            continue
        normalized_history.append({"role": role, "content": content})
    return normalized_history


def normalize_attachments(attachments: list[dict[str, Any]] | None) -> AttachmentSignals:
    normalized_attachments: list[AttachmentPointer] = []

    for attachment in attachments or []:
        file_name = str(attachment.get("file_name") or attachment.get("name") or "").strip()
        file_type = str(attachment.get("file_type") or attachment.get("type") or "").strip()
        attachment_id = str(attachment.get("attachment_id") or attachment.get("id") or "").strip()
        storage_uri = str(
            attachment.get("storage_uri") or attachment.get("uri") or attachment.get("path") or ""
        ).strip()
        content_type = str(
            attachment.get("content_type") or attachment.get("mime_type") or ""
        ).strip()

        raw_size = attachment.get("size_bytes")
        if raw_size is None:
            raw_size = attachment.get("size")
        try:
            size_bytes = int(raw_size) if raw_size is not None else None
        except (TypeError, ValueError):
            size_bytes = None

        normalized_attachments.append(
            AttachmentPointer(
                file_name=file_name,
                file_type=file_type,
                attachment_id=attachment_id,
                storage_uri=storage_uri,
                content_type=content_type,
                size_bytes=size_bytes,
            )
        )

    return AttachmentSignals(
        has_attachments=bool(normalized_attachments),
        attachment_count=len(normalized_attachments),
        attachment_names=[attachment.file_name for attachment in normalized_attachments if attachment.file_name],
        attachment_types=[attachment.file_type for attachment in normalized_attachments if attachment.file_type],
        attachment_ids=[
            attachment.attachment_id for attachment in normalized_attachments if attachment.attachment_id
        ],
        storage_uris=[attachment.storage_uri for attachment in normalized_attachments if attachment.storage_uri],
        attachments=normalized_attachments,
    )


def build_turn_core(
    *,
    thread_id: str | None,
    raw_query: str,
    normalized_query: str | None = None,
    language: str = "other",
    channel: str = "internal_qa",
) -> TurnCore:
    return TurnCore(
        thread_id=str(thread_id or ""),
        raw_query=str(raw_query or ""),
        normalized_query=normalized_query if normalized_query is not None else normalize_query(raw_query),
        language=language,
        channel=channel,
    )


def normalize_turn_inputs(
    *,
    thread_id: str | None,
    raw_query: str,
    conversation_history: list[dict[str, Any]] | None = None,
    attachments: list[dict[str, Any]] | None = None,
) -> tuple[TurnCore, list[dict[str, str]], AttachmentSignals]:
    normalized_query = normalize_query(raw_query)
    return (
        build_turn_core(
            thread_id=thread_id,
            raw_query=raw_query,
            normalized_query=normalized_query,
        ),
        normalize_conversation_history(conversation_history),
        normalize_attachments(attachments),
    )
