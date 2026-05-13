from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from src.config import get_hubspot_settings


logger = logging.getLogger(__name__)

CONTACT_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "hs_object_id",
]

CONTACT_INQUIRY_PROPERTIES = [
    "firstname",
    "lastname",
    "email",
    "company",
    "phone",
    "hs_object_id",
    "hubspot_owner_id",
    "lifecyclestage",
    "hs_lead_status",
    "products_of_interest",
    "service_of_interest",
    "your_message",
    "how_did_you_hera_about_us_",
    "contact_category",
    "area_of_research",
    "createdate",
]

EMAIL_PROPERTIES = [
    "hs_timestamp",
    "hs_email_direction",
    "hs_email_status",
    "hs_email_subject",
    "hs_email_text",
    "hs_email_html",
    "hs_email_from_email",
    "hs_email_to_email",
    "hs_email_from_firstname",
    "hs_email_from_lastname",
    "hubspot_owner_id",
    "hs_attachment_ids",
]

OUTBOUND_EMAIL_DIRECTIONS = {"EMAIL", "FORWARDED_EMAIL"}

_QUOTED_REPLY_PATTERNS = [
    re.compile(r"(?im)^from:\s"),
    re.compile(r"(?im)^sent:\s"),
    re.compile(r"(?im)^to:\s"),
    re.compile(r"(?im)^cc:\s"),
    re.compile(r"(?im)^subject:\s"),
    re.compile(r"(?im)^on .+ wrote:\s*$"),
    re.compile(r"(?im)^begin forwarded message:\s*$"),
    re.compile(r"(?im)^-+\s*original message\s*-+\s*$"),
]

_SIGNOFF_LINE_PATTERNS = [
    re.compile(r"(?i)^best(?: regards)?[,]?$"),
    re.compile(r"(?i)^best wishes[,]?$"),
    re.compile(r"(?i)^regards[,]?$"),
    re.compile(r"(?i)^kind regards[,]?$"),
    re.compile(r"(?i)^warm regards[,]?$"),
    re.compile(r"(?i)^sincerely[,]?$"),
    re.compile(r"(?i)^thank you[,]?$"),
    re.compile(r"(?i)^thanks[,]?$"),
]


class HubSpotConfigError(RuntimeError):
    pass


@dataclass(slots=True)
class FormInquiryResponse:
    timestamp: str
    sender_email: str
    sender_name: str
    subject: str
    text: str
    direction: str
    owner_id: str
    message_id: str
    attachment_ids: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "sender_email": self.sender_email,
            "sender_name": self.sender_name,
            "subject": self.subject,
            "text": self.text,
            "direction": self.direction,
            "owner_id": self.owner_id,
            "message_id": self.message_id,
            "attachment_ids": list(self.attachment_ids),
        }


@dataclass(slots=True)
class ThreadMessage:
    message_id: str
    timestamp: str
    role: str
    source: str
    subject: str
    text: str
    sender_name: str
    sender_email: str
    direction: str
    owner_id: str
    attachment_ids: list[str]

    def to_json(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "role": self.role,
            "source": self.source,
            "subject": self.subject,
            "text": self.text,
            "sender_name": self.sender_name,
            "sender_email": self.sender_email,
            "direction": self.direction,
            "owner_id": self.owner_id,
            "attachment_ids": list(self.attachment_ids),
        }


@dataclass(slots=True)
class FormInquiryRecord:
    contact_id: str
    submission_id: str
    submitted_at: str
    form_id: str
    form_name: str
    sender_name: str
    email: str
    institution: str
    phone: str
    message: str
    products_of_interest: str
    service_of_interest: str
    how_did_you_hear: str
    lifecycle_stage: str
    contact_owner_id: str
    contact_owner_name: str
    thread_messages: list[ThreadMessage]

    def to_json(self) -> dict[str, Any]:
        return {
            "source": "hubspot_form_inquiry",
            "contact_id": self.contact_id,
            "submission_id": self.submission_id,
            "submitted_at": self.submitted_at,
            "form_id": self.form_id,
            "form_name": self.form_name,
            "sender_name": self.sender_name,
            "email": self.email,
            "institution": self.institution,
            "phone": self.phone,
            "message": self.message,
            "products_of_interest": self.products_of_interest,
            "service_of_interest": self.service_of_interest,
            "how_did_you_hear": self.how_did_you_hear,
            "lifecycle_stage": self.lifecycle_stage,
            "contact_owner_id": self.contact_owner_id,
            "contact_owner_name": self.contact_owner_name,
            "thread_messages": [message.to_json() for message in self.thread_messages],
        }


@dataclass(slots=True)
class TrainingQueryExample:
    source: str
    contact_id: str
    contact_email: str
    contact_name: str
    thread_id: str
    message_id: str
    timestamp: str
    text: str
    subject: str = ""
    channel: str = ""
    direction: str = "inbound"
    owner_id: str = ""
    context: list[dict[str, str]] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "contact_id": self.contact_id,
            "contact_email": self.contact_email,
            "contact_name": self.contact_name,
            "thread_id": self.thread_id,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "subject": self.subject,
            "channel": self.channel,
            "direction": self.direction,
            "owner_id": self.owner_id,
            "input_text": self.text,
            "context": list(self.context or []),
        }


class HubSpotClient:
    def __init__(self) -> None:
        self.settings = get_hubspot_settings()
        self.base_url = self.settings["base_url"]
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {self.settings['access_token']}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
        )

    def is_configured(self) -> bool:
        return bool(self.settings.get("is_configured"))

    def get_connection_status(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured(),
            "base_url": self.base_url,
            "missing": [] if self.is_configured() else ["HUBSPOT_ACCESS_TOKEN"],
        }

    def get_file_metadata(self, file_id: str) -> dict[str, Any] | None:
        """Resolve a HubSpot file_id to its metadata (name, url, type).

        Returns None when the file is not found (404) so callers can record
        the gap and continue. Other HTTP errors propagate so transient
        failures are visible.
        """
        self._ensure_configured()
        if not file_id:
            return None
        try:
            return self._request("GET", f"/files/v3/files/{file_id}")
        except requests.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status == 404:
                return None
            raise

    def export_training_queries(
        self,
        *,
        contact_emails: list[str] | None = None,
        contact_limit: int = 100,
        per_contact_thread_limit: int = 50,
        per_thread_message_limit: int = 100,
        include_email_engagements: bool = True,
        include_conversations: bool = True,
    ) -> list[dict[str, Any]]:
        self._ensure_configured()
        contact_emails = [email.strip().lower() for email in (contact_emails or []) if email and email.strip()]

        contacts = self._fetch_contacts(
            contact_emails=contact_emails,
            contact_limit=contact_limit,
        )
        examples: list[TrainingQueryExample] = []

        for contact in contacts:
            contact_id = str(contact.get("id", "") or "")
            properties = contact.get("properties", {}) or {}
            email = str(properties.get("email", "") or "").strip()
            name = _compose_name(properties.get("firstname"), properties.get("lastname"))

            if include_email_engagements:
                email_messages = self._fetch_email_engagements(contact_id, per_contact_thread_limit)
                examples.extend(
                    build_training_examples_from_email_messages(
                        contact_id=contact_id,
                        contact_email=email,
                        contact_name=name,
                        messages=email_messages,
                    )
                )

            if include_conversations:
                thread_ids = self._fetch_conversation_thread_ids(email=email, limit=per_contact_thread_limit)
                for thread_id in thread_ids:
                    messages = self._fetch_conversation_messages(thread_id, per_thread_message_limit)
                    examples.extend(
                        build_training_examples_from_conversation_messages(
                            contact_id=contact_id,
                            contact_email=email,
                            contact_name=name,
                            thread_id=thread_id,
                            messages=messages,
                        )
                    )

        examples.sort(key=lambda item: item.timestamp)
        return [item.to_json() for item in examples]

    def export_form_inquiries(
        self,
        *,
        form_guid: str,
        since: str | None = None,
        progress: bool = False,
    ) -> list[dict[str, Any]]:
        self._ensure_configured()
        submissions = self._fetch_form_submissions(form_guid=form_guid, since=since)
        total = len(submissions)
        results: list[dict[str, Any]] = []

        for index, submission in enumerate(submissions, start=1):
            if progress and index % 25 == 0:
                logger.info("HubSpot form export progress: %s/%s", index, total)

            contact = self._fetch_contact_for_submission(submission)
            record = self._build_form_inquiry_record(submission, contact)
            if record is not None:
                results.append(record.to_json())

        return results

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
    ) -> Any:
        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            json=json_payload,
            timeout=30,
        )
        response.raise_for_status()
        if response.status_code == 204:
            return None
        return response.json()

    def _ensure_configured(self) -> None:
        if not self.is_configured():
            raise HubSpotConfigError("HubSpot env vars are incomplete. Set HUBSPOT_ACCESS_TOKEN.")

    def _fetch_contacts(
        self,
        *,
        contact_emails: list[str],
        contact_limit: int,
    ) -> list[dict[str, Any]]:
        if contact_emails:
            contacts: list[dict[str, Any]] = []
            for email in contact_emails:
                payload = self._request(
                    "POST",
                    "/crm/v3/objects/contacts/search",
                    json_payload={
                        "filterGroups": [
                            {
                                "filters": [
                                    {
                                        "propertyName": "email",
                                        "operator": "EQ",
                                        "value": email,
                                    }
                                ]
                            }
                        ],
                        "properties": CONTACT_PROPERTIES,
                        "limit": 1,
                    },
                )
                contacts.extend(payload.get("results", []) or [])
            return contacts

        payload = self._request(
            "POST",
            "/crm/v3/objects/contacts/search",
            json_payload={
                "filterGroups": [],
                "properties": CONTACT_PROPERTIES,
                "sorts": [{"propertyName": "lastmodifieddate", "direction": "DESCENDING"}],
                "limit": contact_limit,
            },
        )
        return payload.get("results", []) or []

    def _fetch_email_engagements(self, contact_id: str, limit: int) -> list[dict[str, Any]]:
        if not contact_id:
            return []
        payload = self._request(
            "POST",
            "/crm/v3/objects/emails/search",
            json_payload={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "associations.contact",
                                "operator": "EQ",
                                "value": contact_id,
                            }
                        ]
                    }
                ],
                "properties": EMAIL_PROPERTIES,
                "sorts": [{"propertyName": "hs_timestamp", "direction": "ASCENDING"}],
                "limit": limit,
            },
        )
        return payload.get("results", []) or []

    def _fetch_conversation_thread_ids(self, *, email: str, limit: int) -> list[str]:
        if not email:
            return []
        payload = self._request(
            "GET",
            "/conversations/v3/conversations/threads",
            params={"associatedContact": email, "limit": limit},
        )
        threads = payload.get("results", []) or []
        return [str(thread.get("id", "") or "") for thread in threads if thread.get("id")]

    def _fetch_conversation_messages(self, thread_id: str, limit: int) -> list[dict[str, Any]]:
        if not thread_id:
            return []
        payload = self._request(
            "GET",
            f"/conversations/v3/conversations/threads/{thread_id}/messages",
            params={"limit": limit},
        )
        return payload.get("results", []) or []

    def _fetch_form_submissions(self, *, form_guid: str, since: str | None) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        offset: str | None = None
        threshold = _parse_dt(since) if since else None

        while True:
            params: dict[str, Any] = {"limit": 50}
            if offset:
                params["offset"] = offset
            payload = self._request(
                "GET",
                f"/form-integrations/v1/submissions/forms/{form_guid}",
                params=params,
            )
            batch = payload.get("results", []) or []
            for record in batch:
                normalized = _normalize_form_submission(record, form_guid=form_guid)
                submitted_at = str(normalized.get("submitted_at", "") or "").strip()
                if threshold is not None and submitted_at and _parse_dt(submitted_at) < threshold:
                    continue
                results.append(normalized)

            if not payload.get("hasMore"):
                break
            next_offset = payload.get("offset")
            if next_offset in (None, "", offset):
                break
            offset = str(next_offset)

        results.sort(key=lambda item: str(item.get("submitted_at", "") or ""), reverse=True)
        return results

    def _fetch_contact_for_submission(self, submission: dict[str, Any]) -> dict[str, Any]:
        email = str(submission.get("email", "") or "").strip().lower()
        if not email:
            return {}
        payload = self._request(
            "POST",
            "/crm/v3/objects/contacts/search",
            json_payload={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "email",
                                "operator": "EQ",
                                "value": email,
                            }
                        ]
                    }
                ],
                "properties": CONTACT_INQUIRY_PROPERTIES,
                "limit": 1,
            },
        )
        results = payload.get("results", []) or []
        return results[0] if results else {}

    def _build_form_inquiry_record(self, submission: dict[str, Any], contact: dict[str, Any]) -> FormInquiryRecord | None:
        properties = contact.get("properties", {}) or {}
        submission_values = submission.get("values", {}) or {}
        contact_id = str(contact.get("id", "") or "")
        email = str(properties.get("email") or submission_values.get("email") or "").strip()
        if not email:
            return None

        sender_name = _compose_name(
            properties.get("firstname") or submission_values.get("firstname"),
            properties.get("lastname") or submission_values.get("lastname"),
        )
        owner_id = str(properties.get("hubspot_owner_id", "") or "")
        owner = self._fetch_owner(owner_id) if owner_id else {}
        owner_name = _compose_name(owner.get("firstName"), owner.get("lastName"))
        submission_id = str(submission.get("submission_id", "") or contact_id or email)

        thread_messages = self._build_form_thread_messages(contact_id, email) if contact_id else []

        return FormInquiryRecord(
            contact_id=contact_id,
            submission_id=submission_id,
            submitted_at=str(submission.get("submitted_at", "") or ""),
            form_id=str(submission.get("form_id", "") or ""),
            form_name=str(submission.get("form_name", "") or ""),
            sender_name=sender_name,
            email=email,
            institution=str(properties.get("company") or submission_values.get("company") or ""),
            phone=str(properties.get("phone") or submission_values.get("phone") or ""),
            message=str(
                properties.get("your_message")
                or submission_values.get("your_message")
                or submission_values.get("message")
                or ""
            ),
            products_of_interest=str(properties.get("products_of_interest") or submission_values.get("products_of_interest") or ""),
            service_of_interest=str(properties.get("service_of_interest") or submission_values.get("service_of_interest") or ""),
            how_did_you_hear=str(properties.get("how_did_you_hera_about_us_") or submission_values.get("how_did_you_hera_about_us_") or ""),
            lifecycle_stage=str(properties.get("lifecyclestage") or submission_values.get("lifecyclestage") or ""),
            contact_owner_id=owner_id,
            contact_owner_name=owner_name,
            thread_messages=thread_messages,
        )

    def _fetch_owner(self, owner_id: str) -> dict[str, Any]:
        if not owner_id:
            return {}
        try:
            return self._request("GET", f"/crm/v3/owners/{owner_id}")
        except Exception:
            return {}

    def _build_form_thread_messages(self, contact_id: str, email: str) -> list[ThreadMessage]:
        email_messages = self._fetch_email_engagements(contact_id, limit=100)
        thread_messages: list[ThreadMessage] = []
        for message in email_messages:
            properties = message.get("properties", {}) or {}
            direction = str(properties.get("hs_email_direction", "") or "")
            sender_email = str(properties.get("hs_email_from_email", "") or "")
            role = "customer" if _is_inbound_email(direction=direction, sender_email=sender_email, contact_email=email) else "sales"
            text = _extract_latest_email_reply(
                properties.get("hs_email_text") or properties.get("hs_email_html") or ""
            )
            thread_messages.append(
                ThreadMessage(
                    message_id=str(message.get("id", "") or ""),
                    timestamp=str(properties.get("hs_timestamp", "") or ""),
                    role=role,
                    source="hubspot_email_engagement",
                    subject=str(properties.get("hs_email_subject", "") or ""),
                    text=text,
                    sender_name=_compose_name(
                        properties.get("hs_email_from_firstname"),
                        properties.get("hs_email_from_lastname"),
                    ),
                    sender_email=sender_email,
                    direction=direction,
                    owner_id=str(properties.get("hubspot_owner_id", "") or ""),
                    attachment_ids=_split_attachment_ids(properties.get("hs_attachment_ids", "")),
                )
            )
        thread_messages.sort(key=lambda item: item.timestamp)
        return thread_messages


def _split_attachment_ids(raw: str) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _submission_values_map(raw_submission: dict[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for item in raw_submission.get("values", []) or []:
        name = str(item.get("name", "") or "").strip()
        if not name:
            continue
        values[name] = str(item.get("value", "") or "").strip()
    return values


def _millis_to_iso8601(raw: Any) -> str:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return ""
    return (
        datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _normalize_form_submission(raw_submission: dict[str, Any], *, form_guid: str) -> dict[str, Any]:
    values = _submission_values_map(raw_submission)
    sender_name = _compose_name(values.get("firstname"), values.get("lastname"))
    page_url = str(raw_submission.get("pageUrl", "") or "").strip()
    form_name = "Contact Us"
    if page_url:
        form_name = page_url.rsplit("/", 1)[-1] or "Contact Us"

    return {
        "submission_id": str(raw_submission.get("conversionId", "") or "").strip(),
        "submitted_at": _millis_to_iso8601(raw_submission.get("submittedAt")),
        "form_id": form_guid,
        "form_name": form_name,
        "sender_name": sender_name,
        "email": values.get("email", ""),
        "values": values,
        "page_url": page_url,
    }


def _parse_dt(raw: str) -> datetime:
    value = str(raw or "").strip()
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _compose_name(first: Any, last: Any) -> str:
    parts = [str(first or "").strip(), str(last or "").strip()]
    return " ".join(part for part in parts if part).strip()


def _clean_text(raw: Any) -> str:
    text = str(raw or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</p\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    compact: list[str] = []
    blank_run = 0
    for line in lines:
        if not line:
            blank_run += 1
            if blank_run <= 1:
                compact.append("")
            continue
        blank_run = 0
        compact.append(line)
    return "\n".join(compact).strip()


def _extract_latest_email_reply(raw: Any) -> str:
    text = _clean_text(raw)
    if not text:
        return ""

    lines = text.split("\n")
    cut_index = len(lines)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if any(pattern.search(stripped) for pattern in _QUOTED_REPLY_PATTERNS):
            cut_index = index
            break
    lines = lines[:cut_index]

    while lines and not lines[-1].strip():
        lines.pop()

    for index in range(len(lines) - 1, -1, -1):
        stripped = lines[index].strip()
        if any(pattern.match(stripped) for pattern in _SIGNOFF_LINE_PATTERNS):
            trailing = [line.strip() for line in lines[index + 1:] if line.strip()]
            if index > 0 and trailing and len(trailing) <= 3:
                lines = lines[:index]
            break

    return "\n".join(lines).strip()


def _is_inbound_email(*, direction: str, sender_email: str, contact_email: str) -> bool:
    normalized_direction = str(direction or "").strip().upper()
    if normalized_direction and normalized_direction not in OUTBOUND_EMAIL_DIRECTIONS:
        return True
    return (
        bool(sender_email)
        and bool(contact_email)
        and str(sender_email).strip().lower() == str(contact_email).strip().lower()
    )


def build_training_examples_from_email_messages(
    *,
    contact_id: str,
    contact_email: str,
    contact_name: str,
    messages: list[dict[str, Any]],
) -> list[TrainingQueryExample]:
    examples: list[TrainingQueryExample] = []
    context: list[dict[str, str]] = []

    def sort_key(message: dict[str, Any]) -> str:
        properties = message.get("properties", {}) or {}
        return str(properties.get("hs_timestamp", "") or "")

    for message in sorted(messages, key=sort_key):
        properties = message.get("properties", {}) or {}
        direction = str(properties.get("hs_email_direction", "") or "")
        sender_email = str(properties.get("hs_email_from_email", "") or "")
        text = _extract_latest_email_reply(
            properties.get("hs_email_text") or properties.get("hs_email_html") or ""
        )
        if not text:
            continue

        is_inbound = _is_inbound_email(
            direction=direction,
            sender_email=sender_email,
            contact_email=contact_email,
        )

        if is_inbound:
            examples.append(
                TrainingQueryExample(
                    source="hubspot_email_engagement",
                    contact_id=contact_id,
                    contact_email=contact_email,
                    contact_name=contact_name,
                    thread_id=contact_id,
                    message_id=str(message.get("id", "") or ""),
                    timestamp=str(properties.get("hs_timestamp", "") or ""),
                    text=text,
                    subject=str(properties.get("hs_email_subject", "") or ""),
                    channel="email",
                    direction="inbound",
                    owner_id=str(properties.get("hubspot_owner_id", "") or ""),
                    context=list(context),
                )
            )
            context.append({"role": "user", "content": text})
        else:
            context.append({"role": "assistant", "content": text})

    return examples


def build_training_examples_from_conversation_messages(
    *,
    contact_id: str,
    contact_email: str,
    contact_name: str,
    thread_id: str,
    messages: list[dict[str, Any]],
) -> list[TrainingQueryExample]:
    examples: list[TrainingQueryExample] = []
    context: list[dict[str, str]] = []

    def is_customer_message(message: dict[str, Any]) -> bool:
        sender = message.get("sender", {}) or {}
        actor_id = str(sender.get("actorId", "") or "")
        return actor_id.startswith("V-")

    def sort_key(message: dict[str, Any]) -> str:
        return str(message.get("createdAt", "") or "")

    for message in sorted(messages, key=sort_key):
        text = _clean_text(message.get("text", ""))
        if not text:
            continue
        if is_customer_message(message):
            examples.append(
                TrainingQueryExample(
                    source="hubspot_conversation",
                    contact_id=contact_id,
                    contact_email=contact_email,
                    contact_name=contact_name,
                    thread_id=thread_id,
                    message_id=str(message.get("id", "") or ""),
                    timestamp=str(message.get("createdAt", "") or ""),
                    text=text,
                    channel="conversation",
                    direction="inbound",
                    context=list(context),
                )
            )
            context.append({"role": "user", "content": text})
        else:
            context.append({"role": "assistant", "content": text})

    return examples
