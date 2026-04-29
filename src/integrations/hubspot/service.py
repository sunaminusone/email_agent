from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
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
        contacts = self.search_contacts(emails=contact_emails, limit=contact_limit)
        all_examples: list[TrainingQueryExample] = []

        for contact in contacts:
            contact_id = str(contact.get("id", "")).strip()
            properties = contact.get("properties", {}) or {}
            if not contact_id:
                continue

            if include_email_engagements:
                all_examples.extend(self._collect_email_examples(contact_id, properties))
            if include_conversations:
                all_examples.extend(
                    self._collect_conversation_examples(
                        contact_id,
                        properties,
                        thread_limit=per_contact_thread_limit,
                        message_limit=per_thread_message_limit,
                    )
                )

        deduped = self._dedupe_examples(all_examples)
        deduped.sort(key=lambda item: (item.timestamp, item.contact_id, item.thread_id, item.message_id))
        return [example.to_json() for example in deduped]

    def search_contacts(self, *, emails: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        filters = []
        clean_emails = [value.strip() for value in (emails or []) if value and value.strip()]
        if clean_emails:
            filters = [{"propertyName": "email", "operator": "IN", "values": clean_emails}]

        payload: dict[str, Any] = {
            "limit": min(max(limit, 1), 100),
            "properties": CONTACT_PROPERTIES,
            "sorts": [{"propertyName": "createdate", "direction": "DESCENDING"}],
        }
        if filters:
            payload["filterGroups"] = [{"filters": filters}]

        response = self._request("POST", "/crm/v3/objects/contacts/search", json=payload)
        return list(response.get("results", []))

    def _collect_email_examples(
        self,
        contact_id: str,
        contact_properties: dict[str, Any],
    ) -> list[TrainingQueryExample]:
        email_ids = self._read_associated_ids(from_object="contacts", to_object="emails", record_ids=[contact_id])
        if not email_ids:
            return []

        inputs = [{"id": email_id} for email_id in email_ids]
        response = self._request(
            "POST",
            "/crm/v3/objects/emails/batch/read",
            json={"inputs": inputs, "properties": EMAIL_PROPERTIES},
        )
        results = list(response.get("results", []))
        examples: list[TrainingQueryExample] = []
        for email in results:
            properties = email.get("properties", {}) or {}
            direction = str(properties.get("hs_email_direction", "")).upper()
            sender_email = str(properties.get("hs_email_from_email", "")).strip().lower()
            body = _clean_text(properties.get("hs_email_text") or properties.get("hs_email_html") or "")
            if not body:
                continue
            if not _is_inbound_email(direction=direction, sender_email=sender_email, contact_email=contact_properties.get("email", "")):
                continue

            examples.append(
                TrainingQueryExample(
                    source="hubspot_email_engagement",
                    contact_id=contact_id,
                    contact_email=str(contact_properties.get("email", "")),
                    contact_name=_build_contact_name(contact_properties),
                    thread_id=f"email-contact-{contact_id}",
                    message_id=str(email.get("id", "")),
                    timestamp=_normalize_timestamp(properties.get("hs_timestamp")),
                    subject=str(properties.get("hs_email_subject", "") or ""),
                    channel="email",
                    direction="inbound",
                    owner_id=str(properties.get("hubspot_owner_id", "") or ""),
                    text=body,
                    context=[],
                )
            )
        return examples

    def _collect_conversation_examples(
        self,
        contact_id: str,
        contact_properties: dict[str, Any],
        *,
        thread_limit: int,
        message_limit: int,
    ) -> list[TrainingQueryExample]:
        try:
            threads_payload = self._paginate(
                "/conversations/v3/conversations/threads",
                params={
                    "associatedContactId": contact_id,
                    "limit": min(max(thread_limit, 1), 500),
                },
            )
        except requests.HTTPError as exc:
            logger.warning("HubSpot conversations threads fetch failed for contact %s: %s", contact_id, exc)
            return []

        examples: list[TrainingQueryExample] = []
        for thread in threads_payload:
            thread_id = str(thread.get("id", "")).strip()
            if not thread_id:
                continue

            try:
                messages = self._paginate(
                    f"/conversations/v3/conversations/threads/{thread_id}/messages",
                    params={"limit": min(max(message_limit, 1), 500)},
                )
            except requests.HTTPError as exc:
                logger.warning("HubSpot conversation messages fetch failed for thread %s: %s", thread_id, exc)
                continue

            examples.extend(
                build_training_examples_from_conversation_messages(
                    contact_id=contact_id,
                    contact_email=str(contact_properties.get("email", "") or ""),
                    contact_name=_build_contact_name(contact_properties),
                    thread_id=thread_id,
                    messages=messages,
                )
            )
        return examples

    def _read_associated_ids(
        self,
        *,
        from_object: str,
        to_object: str,
        record_ids: list[str],
    ) -> list[str]:
        if not record_ids:
            return []

        response = self._request(
            "POST",
            f"/crm/v3/associations/{from_object}/{to_object}/batch/read",
            json={"inputs": [{"id": record_id} for record_id in record_ids]},
        )
        found: list[str] = []
        for result in response.get("results", []):
            for to_item in result.get("to", []):
                value = str(to_item.get("id", "")).strip()
                if value:
                    found.append(value)
        return found

    def _paginate(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        next_after: str | None = None
        while True:
            query = dict(params or {})
            if next_after:
                query["after"] = next_after
            page = self._request("GET", path, params=query)
            results.extend(page.get("results", []))
            next_after = (((page.get("paging") or {}).get("next") or {}).get("after"))
            if not next_after:
                break
        return results

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self.session.request(
            method=method,
            url=f"{self.base_url}{path}",
            params=params,
            json=json,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise requests.HTTPError(f"Unexpected HubSpot response type for {path}: {type(payload)!r}")
        return payload

    def export_form_inquiries(
        self,
        *,
        form_guid: str,
        since: str | None = None,
        progress: bool = False,
    ) -> list[dict[str, Any]]:
        self._ensure_configured()

        def log(msg: str) -> None:
            if progress:
                print(msg, flush=True)

        log(f"[1/5] Looking up form {form_guid}...")
        form_name = self._lookup_form_name(form_guid)
        log(f"      Form name: {form_name!r}")

        log(f"[2/5] Fetching form submissions (since={since or 'beginning'})...")
        submissions = self._fetch_form_submissions(form_guid, since=since, progress=progress)
        log(f"      Total submissions: {len(submissions)}")
        if not submissions:
            return []

        log("[3/5] Loading property option labels + owners map...")
        enum_labels = {
            "products_of_interest": self._get_property_option_labels("contacts", "products_of_interest"),
            "service_of_interest": self._get_property_option_labels("contacts", "service_of_interest"),
            "how_did_you_hera_about_us_": self._get_property_option_labels("contacts", "how_did_you_hera_about_us_"),
        }
        owners = self._load_owners()
        log(f"      Owners loaded: {len(owners)}")

        emails = sorted({_extract_submission_value(s, "email").lower() for s in submissions if _extract_submission_value(s, "email")})
        log(f"[4/5] Batch-reading {len(emails)} unique contacts...")
        contacts_by_email = self._batch_read_contacts_by_email(emails)
        log(f"      Contacts resolved: {len(contacts_by_email)}/{len(emails)}")

        next_submission_at_by_key = _build_next_submission_at_by_key(submissions)

        log(f"[5/5] Collecting contact thread messages for {len(submissions)} submissions...")
        records: list[FormInquiryRecord] = []
        for idx, submission in enumerate(submissions, start=1):
            email = _extract_submission_value(submission, "email").lower()
            if not email:
                continue
            contact = contacts_by_email.get(email)
            contact_id = str((contact or {}).get("id", "")).strip()
            contact_props = (contact or {}).get("properties", {}) or {}

            submitted_at = _normalize_timestamp(submission.get("submittedAt"))
            submission_key = (str(submission.get("submittedAt", "") or ""), email)
            thread_messages = (
                self._collect_contact_thread_messages(
                    contact_id,
                    contact_email=email,
                    submitted_at=submitted_at,
                    next_submission_at=next_submission_at_by_key.get(submission_key, ""),
                    sender_name=_compose_name(
                        _extract_submission_value(submission, "firstname") or str(contact_props.get("firstname", "")),
                        _extract_submission_value(submission, "lastname") or str(contact_props.get("lastname", "")),
                    ),
                    owners=owners,
                    original_message=_extract_submission_value(submission, "message") or str(contact_props.get("your_message", "") or ""),
                )
                if contact_id
                else _build_submission_thread_messages(
                    submission_id=str(submission.get("submittedAt", "")) + "|" + email,
                    submitted_at=submitted_at,
                    sender_name=_compose_name(
                        _extract_submission_value(submission, "firstname") or str(contact_props.get("firstname", "")),
                        _extract_submission_value(submission, "lastname") or str(contact_props.get("lastname", "")),
                    ),
                    sender_email=email,
                    original_message=_extract_submission_value(submission, "message") or str(contact_props.get("your_message", "") or ""),
                )
            )
            if progress and (idx % 10 == 0 or idx == len(submissions)):
                sales_count = sum(1 for message in thread_messages if message.role == "sales")
                print(f"      [{idx}/{len(submissions)}] {email} -> {sales_count} sales messages", flush=True)

            contact_owner_id = str(contact_props.get("hubspot_owner_id", "") or "")
            original_message = _extract_submission_value(submission, "message") or str(contact_props.get("your_message", "") or "")
            sender_name = _compose_name(
                _extract_submission_value(submission, "firstname") or str(contact_props.get("firstname", "")),
                _extract_submission_value(submission, "lastname") or str(contact_props.get("lastname", "")),
            )

            records.append(
                FormInquiryRecord(
                    contact_id=contact_id,
                    submission_id=str(submission.get("submittedAt", "")) + "|" + email,
                    submitted_at=submitted_at,
                    form_id=form_guid,
                    form_name=form_name,
                    sender_name=sender_name,
                    email=email,
                    institution=_extract_submission_value(submission, "company") or str(contact_props.get("company", "") or ""),
                    phone=_extract_submission_value(submission, "phone") or str(contact_props.get("phone", "") or ""),
                    message=original_message,
                    products_of_interest=_resolve_enum(
                        _extract_submission_value(submission, "products_of_interest") or str(contact_props.get("products_of_interest", "") or ""),
                        enum_labels["products_of_interest"],
                    ),
                    service_of_interest=_resolve_enum(
                        _extract_submission_value(submission, "service_of_interest") or str(contact_props.get("service_of_interest", "") or ""),
                        enum_labels["service_of_interest"],
                    ),
                    how_did_you_hear=_resolve_enum(
                        _extract_submission_value(submission, "how_did_you_hera_about_us_")
                        or str(contact_props.get("how_did_you_hera_about_us_", "") or ""),
                        enum_labels["how_did_you_hera_about_us_"],
                    ),
                    lifecycle_stage=_extract_submission_value(submission, "lifecyclestage") or str(contact_props.get("lifecyclestage", "") or ""),
                    contact_owner_id=contact_owner_id,
                    contact_owner_name=(owners.get(contact_owner_id) or {}).get("name", ""),
                    thread_messages=thread_messages,
                )
            )

        records.sort(key=lambda item: (item.submitted_at, item.email))
        return [record.to_json() for record in records]

    def _lookup_form_name(self, form_guid: str) -> str:
        try:
            response = self._request("GET", f"/marketing/v3/forms/{form_guid}")
        except requests.HTTPError as exc:
            logger.warning("HubSpot form lookup failed for %s: %s", form_guid, exc)
            return ""
        return str(response.get("name", ""))

    def _fetch_form_submissions(
        self,
        form_guid: str,
        *,
        since: str | None = None,
        progress: bool = False,
    ) -> list[dict[str, Any]]:
        path = f"/form-integrations/v1/submissions/forms/{form_guid}"
        results: list[dict[str, Any]] = []
        after: str | None = None
        since_ms = _iso_to_epoch_ms(since) if since else None
        page_idx = 0
        while True:
            params: dict[str, Any] = {"limit": 50}
            if after:
                params["after"] = after
            page = self._request("GET", path, params=params)
            batch = list(page.get("results", []))
            if since_ms is not None:
                batch = [item for item in batch if int(item.get("submittedAt", 0)) >= since_ms]
            results.extend(batch)
            page_idx += 1
            if progress:
                print(f"      page {page_idx}: +{len(batch)} (running total: {len(results)})", flush=True)
            paging = page.get("paging") or {}
            after = ((paging.get("next") or {}).get("after"))
            if not after:
                break
        return results

    def _get_property_option_labels(self, object_type: str, property_name: str) -> dict[str, str]:
        try:
            response = self._request("GET", f"/crm/v3/properties/{object_type}/{property_name}")
        except requests.HTTPError as exc:
            logger.warning("HubSpot property lookup failed for %s.%s: %s", object_type, property_name, exc)
            return {}
        options = response.get("options") or []
        return {str(opt.get("value", "")): str(opt.get("label", "")) for opt in options if opt.get("value")}

    def _batch_read_contacts_by_email(self, emails: list[str]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        if not emails:
            return result
        chunk_size = 100
        for start in range(0, len(emails), chunk_size):
            chunk = emails[start : start + chunk_size]
            payload = {
                "properties": CONTACT_INQUIRY_PROPERTIES,
                "idProperty": "email",
                "inputs": [{"id": email} for email in chunk],
            }
            try:
                response = self._request("POST", "/crm/v3/objects/contacts/batch/read", json=payload)
            except requests.HTTPError as exc:
                logger.warning("HubSpot batch contact read failed (chunk starting %s): %s", chunk[0], exc)
                continue
            for contact in response.get("results", []):
                email = str((contact.get("properties") or {}).get("email", "")).strip().lower()
                if email:
                    result[email] = contact
        return result

    def _load_owners(self) -> dict[str, dict[str, str]]:
        try:
            owners_raw = self._paginate("/crm/v3/owners", params={"limit": 100})
        except requests.HTTPError as exc:
            logger.warning("HubSpot owners fetch failed: %s", exc)
            return {}
        result: dict[str, dict[str, str]] = {}
        for owner in owners_raw:
            owner_id = str(owner.get("id", "")).strip()
            if not owner_id:
                continue
            result[owner_id] = {
                "name": _compose_name(owner.get("firstName"), owner.get("lastName")),
                "email": str(owner.get("email", "") or ""),
            }
        return result

    def _collect_contact_thread_messages(
        self,
        contact_id: str,
        *,
        contact_email: str,
        submitted_at: str,
        next_submission_at: str,
        sender_name: str,
        owners: dict[str, dict[str, str]] | None = None,
        original_message: str,
    ) -> list[ThreadMessage]:
        email_ids = self._read_associated_ids(from_object="contacts", to_object="emails", record_ids=[contact_id])
        thread_messages = _build_submission_thread_messages(
            submission_id=f"{submitted_at}|{contact_email}",
            submitted_at=submitted_at,
            sender_name=sender_name,
            sender_email=contact_email,
            original_message=original_message,
        )
        if not email_ids:
            return thread_messages

        messages: list[ThreadMessage] = []
        chunk_size = 100
        for start in range(0, len(email_ids), chunk_size):
            chunk = email_ids[start : start + chunk_size]
            payload = {
                "inputs": [{"id": email_id} for email_id in chunk],
                "properties": EMAIL_PROPERTIES,
            }
            try:
                response = self._request("POST", "/crm/v3/objects/emails/batch/read", json=payload)
            except requests.HTTPError as exc:
                logger.warning("HubSpot outbound email read failed for contact %s: %s", contact_id, exc)
                continue
            for email in response.get("results", []):
                properties = email.get("properties", {}) or {}
                direction = str(properties.get("hs_email_direction", "")).upper()
                timestamp = _normalize_timestamp(properties.get("hs_timestamp"))
                if submitted_at and timestamp and timestamp < submitted_at:
                    continue
                if next_submission_at and timestamp and timestamp >= next_submission_at:
                    continue
                sender_email = str(properties.get("hs_email_from_email", "") or "").strip().lower()
                body = _extract_latest_email_reply(properties.get("hs_email_text") or properties.get("hs_email_html") or "")
                if not body:
                    continue
                is_sales = direction in OUTBOUND_EMAIL_DIRECTIONS
                is_customer = _is_inbound_email(
                    direction=direction,
                    sender_email=sender_email,
                    contact_email=contact_email,
                )
                if not is_sales and not is_customer:
                    continue
                owner_id = str(properties.get("hubspot_owner_id", "") or "")
                message_sender_name = _compose_name(
                    properties.get("hs_email_from_firstname"),
                    properties.get("hs_email_from_lastname"),
                )
                if owners and owner_id in owners and is_sales:
                    owner_info = owners[owner_id]
                    if not message_sender_name:
                        message_sender_name = owner_info.get("name", "")
                    if not sender_email:
                        sender_email = owner_info.get("email", "")
                attachment_ids = _parse_attachment_ids(properties.get("hs_attachment_ids"))
                messages.append(
                    ThreadMessage(
                        message_id=str(email.get("id", "")),
                        timestamp=timestamp,
                        role="sales" if is_sales else "customer",
                        source="crm_email",
                        subject=str(properties.get("hs_email_subject", "") or ""),
                        text=body,
                        sender_name=message_sender_name,
                        sender_email=sender_email,
                        direction=direction,
                        owner_id=owner_id,
                        attachment_ids=attachment_ids,
                    )
                )
        thread_messages.extend(messages)
        thread_messages.sort(key=lambda item: (item.timestamp, item.message_id))
        return thread_messages

    def _ensure_configured(self) -> None:
        if not self.is_configured():
            raise HubSpotConfigError("HubSpot env vars are incomplete. Set HUBSPOT_ACCESS_TOKEN.")

    @staticmethod
    def _dedupe_examples(examples: list[TrainingQueryExample]) -> list[TrainingQueryExample]:
        deduped: list[TrainingQueryExample] = []
        seen: set[tuple[str, str, str, str]] = set()
        for example in examples:
            signature = (example.source, example.contact_id, example.thread_id, example.message_id)
            if signature in seen:
                continue
            seen.add(signature)
            deduped.append(example)
        return deduped


def build_training_examples_from_conversation_messages(
    *,
    contact_id: str,
    contact_email: str,
    contact_name: str,
    thread_id: str,
    messages: list[dict[str, Any]],
) -> list[TrainingQueryExample]:
    ordered_messages = sorted(
        messages,
        key=lambda item: _normalize_timestamp(
            item.get("createdAt")
            or item.get("timestamp")
            or ((item.get("createdAt") or item.get("created_at")) if isinstance(item, dict) else "")
        ),
    )

    examples: list[TrainingQueryExample] = []
    rolling_context: list[dict[str, str]] = []
    for message in ordered_messages:
        text = _clean_text(message.get("text") or message.get("richText") or "")
        if not text:
            continue

        sender = message.get("sender") or {}
        actor_id = str(sender.get("actorId", "") or sender.get("actor_id", "")).strip()
        direction = "agent" if actor_id.startswith("A-") else "customer"
        if direction == "customer":
            examples.append(
                TrainingQueryExample(
                    source="hubspot_conversation",
                    contact_id=contact_id,
                    contact_email=contact_email,
                    contact_name=contact_name,
                    thread_id=thread_id,
                    message_id=str(message.get("id", "")).strip(),
                    timestamp=_normalize_timestamp(message.get("createdAt") or message.get("timestamp")),
                    text=text,
                    subject=str(message.get("subject", "") or ""),
                    channel=str(message.get("channelId", "") or ""),
                    direction="inbound",
                    context=list(rolling_context[-5:]),
                )
            )

        rolling_context.append({"role": "assistant" if direction == "agent" else "user", "content": text})
    return examples


def _extract_submission_value(submission: dict[str, Any], name: str) -> str:
    for entry in submission.get("values", []) or []:
        if str(entry.get("name", "")) == name:
            value = entry.get("value", "")
            if isinstance(value, list):
                return ";".join(str(v) for v in value)
            return str(value or "")
    return ""


def _build_submission_thread_messages(
    *,
    submission_id: str,
    submitted_at: str,
    sender_name: str,
    sender_email: str,
    original_message: str,
) -> list[ThreadMessage]:
    text = _clean_text(original_message)
    if not text:
        return []
    return [
        ThreadMessage(
            message_id=f"{submission_id}:form_submission",
            timestamp=submitted_at,
            role="customer",
            source="form_submission",
            subject="",
            text=text,
            sender_name=sender_name,
            sender_email=sender_email,
            direction="FORM_SUBMISSION",
            owner_id="",
            attachment_ids=[],
        )
    ]


def _build_next_submission_at_by_key(submissions: list[dict[str, Any]]) -> dict[tuple[str, str], str]:
    by_email: dict[str, list[str]] = {}
    for submission in submissions:
        email = _extract_submission_value(submission, "email").lower()
        submitted_at_raw = str(submission.get("submittedAt", "") or "")
        if not email or not submitted_at_raw:
            continue
        by_email.setdefault(email, []).append(submitted_at_raw)

    next_by_key: dict[tuple[str, str], str] = {}
    for email, timestamps in by_email.items():
        ordered = sorted(timestamps, key=lambda value: _normalize_timestamp(value))
        for index, submitted_at_raw in enumerate(ordered):
            next_value = ordered[index + 1] if index + 1 < len(ordered) else ""
            next_by_key[(submitted_at_raw, email)] = _normalize_timestamp(next_value)
    return next_by_key


def _resolve_enum(raw_value: str, labels: dict[str, str]) -> str:
    if not raw_value:
        return ""
    if not labels:
        return raw_value
    parts = [part.strip() for part in raw_value.split(";") if part.strip()]
    return ", ".join(labels.get(part, part) for part in parts)


def _compose_name(first: Any, last: Any) -> str:
    parts = [str(first or "").strip(), str(last or "").strip()]
    return " ".join(part for part in parts if part).strip()


def _parse_attachment_ids(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(";") if part.strip()]


def _iso_to_epoch_ms(value: str) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return int(datetime.fromisoformat(text).timestamp() * 1000)
    except ValueError:
        logger.warning("Invalid ISO timestamp for --since: %s", value)
        return None


def _build_contact_name(properties: dict[str, Any]) -> str:
    parts = [str(properties.get("firstname", "")).strip(), str(properties.get("lastname", "")).strip()]
    return " ".join(part for part in parts if part).strip()


def _normalize_timestamp(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    if text.isdigit():
        return datetime.utcfromtimestamp(int(text) / 1000).isoformat() + "Z"
    return text


def _is_inbound_email(*, direction: str, sender_email: str, contact_email: str) -> bool:
    normalized_contact = str(contact_email or "").strip().lower()
    if direction == "INCOMING_EMAIL":
        return True
    if normalized_contact and sender_email and sender_email == normalized_contact:
        return True
    return False


def _clean_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\r", "\n")
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def _extract_latest_email_reply(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""

    text = _strip_quoted_email_history(text)
    text = _strip_signature_block(text)
    return _clean_text(text)


def _strip_quoted_email_history(text: str) -> str:
    cutoff_positions = [match.start() for pattern in _QUOTED_REPLY_PATTERNS for match in [pattern.search(text)] if match]
    if not cutoff_positions:
        return text
    return text[: min(cutoff_positions)].rstrip()


def _strip_signature_block(text: str) -> str:
    lines = text.split("\n")
    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue
        if not any(pattern.match(line) for pattern in _SIGNOFF_LINE_PATTERNS):
            continue

        content_before = "\n".join(lines[:index]).strip()
        if not content_before:
            return text

        substantive_lines = [item.strip() for item in lines[:index] if item.strip()]
        # Keep ultra-short replies like "Thanks, Tim" intact.
        if len(substantive_lines) <= 1 and len(content_before) < 40:
            return text
        return content_before
    return text
