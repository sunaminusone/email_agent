from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.integrations.hubspot.service import (
    build_training_examples_from_conversation_messages,
    _clean_text,
    _extract_latest_email_reply,
    _is_inbound_email,
)


def test_clean_text_strips_html_and_extra_whitespace():
    raw = "<p>Hello team,</p><p>I need a quote.<br>Thanks</p>"
    assert _clean_text(raw) == "Hello team,\nI need a quote.\nThanks"


def test_extract_latest_email_reply_drops_quoted_history_and_signature():
    raw = """
    <p>Hi Matthew,</p>
    <p>Please use the privnote below for the login details.</p>
    <p>https://privnote.example/test</p>
    <p>Best regards,<br>Timothy Nguyen<br>ProMab Biotechnologies</p>
    <p>From: Matthew Manobianco</p>
    <p>Sent: Tuesday, January 31, 2023 2:03 PM</p>
    <p>Subject: HubSpot Access and Integrations</p>
    <p>Hi Tim, Please see the attached document for my HubSpot access.</p>
    """
    assert _extract_latest_email_reply(raw) == (
        "Hi Matthew,\n\nPlease use the privnote below for the login details.\n\nhttps://privnote.example/test"
    )


def test_extract_latest_email_reply_keeps_short_acknowledgement():
    raw = "Thanks,\nTim"
    assert _extract_latest_email_reply(raw) == "Thanks,\nTim"


def test_inbound_email_detects_direction_or_sender_match():
    assert _is_inbound_email(direction="INCOMING_EMAIL", sender_email="", contact_email="")
    assert _is_inbound_email(
        direction="EMAIL",
        sender_email="customer@example.com",
        contact_email="customer@example.com",
    )
    assert not _is_inbound_email(
        direction="EMAIL",
        sender_email="sales@promab.com",
        contact_email="customer@example.com",
    )


def test_build_training_examples_from_conversation_messages_keeps_customer_queries():
    messages = [
        {
            "id": "m1",
            "createdAt": "2026-04-01T10:00:00Z",
            "text": "Hi, how can we help?",
            "sender": {"actorId": "A-123"},
        },
        {
            "id": "m2",
            "createdAt": "2026-04-01T10:01:00Z",
            "text": "Can you quote 5mg antibody production?",
            "sender": {"actorId": "V-456"},
        },
        {
            "id": "m3",
            "createdAt": "2026-04-01T10:02:00Z",
            "text": "Sure, what species do you need?",
            "sender": {"actorId": "A-123"},
        },
        {
            "id": "m4",
            "createdAt": "2026-04-01T10:03:00Z",
            "text": "Human IgG1, and what is the lead time?",
            "sender": {"actorId": "V-456"},
        },
    ]

    examples = build_training_examples_from_conversation_messages(
        contact_id="42",
        contact_email="customer@example.com",
        contact_name="Ada Lovelace",
        thread_id="thread-1",
        messages=messages,
    )

    assert [item.message_id for item in examples] == ["m2", "m4"]
    assert examples[0].context == [{"role": "assistant", "content": "Hi, how can we help?"}]
    assert examples[1].context == [
        {"role": "assistant", "content": "Hi, how can we help?"},
        {"role": "user", "content": "Can you quote 5mg antibody production?"},
        {"role": "assistant", "content": "Sure, what species do you need?"},
    ]
