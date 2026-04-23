from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.flatten_hubspot_form_inquiries import expand_record


def test_expand_record_sets_customer_message_to_original_for_first_reply():
    record = {
        "submission_id": "sub-1",
        "contact_id": "42",
        "submitted_at": "2026-04-01T10:00:00Z",
        "sender_name": "Ada",
        "email": "ada@example.com",
        "institution": "Example Lab",
        "phone": "123",
        "message": "Can you quote a rabbit monoclonal project?",
        "thread_messages": [
            {
                "timestamp": "2026-04-01T10:00:00Z",
                "message_id": "form-1",
                "role": "customer",
                "source": "form_submission",
                "text": "Can you quote a rabbit monoclonal project?",
            },
            {
                "timestamp": "2026-04-01T11:00:00Z",
                "message_id": "r1",
                "role": "sales",
                "source": "crm_email",
                "sender_name": "Sales Rep",
                "sender_email": "sales@example.com",
                "subject": "Re: Quote request",
                "direction": "EMAIL",
                "attachment_ids": [],
                "text": "Yes, can you share your target sequence?",
            }
        ],
    }

    rows = expand_record(record, skip_empty=False)

    assert len(rows) == 1
    assert rows[0]["original_message"] == "Can you quote a rabbit monoclonal project?"
    assert rows[0]["customer_message"] == "Can you quote a rabbit monoclonal project?"
    assert rows[0]["customer_message_source"] == "form_submission"
    assert rows[0]["reply_message"] == "Yes, can you share your target sequence?"


def test_expand_record_leaves_customer_message_empty_for_follow_up_replies():
    record = {
        "submission_id": "sub-2",
        "message": "Need pricing for CAR-T service.",
        "thread_messages": [
            {
                "timestamp": "2026-04-01T10:00:00Z",
                "message_id": "form-2",
                "role": "customer",
                "source": "form_submission",
                "text": "Need pricing for CAR-T service.",
            },
            {
                "timestamp": "2026-04-01T11:00:00Z",
                "message_id": "r1",
                "role": "sales",
                "source": "crm_email",
                "sender_name": "Sales Rep",
                "sender_email": "sales@example.com",
                "subject": "Re: CAR-T service",
                "direction": "EMAIL",
                "attachment_ids": [],
                "text": "Happy to help. What construct do you need?",
            },
            {
                "timestamp": "2026-04-03T11:00:00Z",
                "message_id": "r2",
                "role": "sales",
                "source": "crm_email",
                "sender_name": "Sales Rep",
                "sender_email": "sales@example.com",
                "subject": "Follow-up on CAR-T service",
                "direction": "EMAIL",
                "attachment_ids": [],
                "text": "Following up in case this project is still active.",
            },
        ],
    }

    rows = expand_record(record, skip_empty=False)

    assert len(rows) == 2
    assert rows[0]["customer_message"] == "Need pricing for CAR-T service."
    assert rows[0]["customer_message_source"] == "form_submission"
    assert rows[1]["customer_message"] == ""
    assert rows[1]["customer_message_source"] == ""
    assert rows[1]["reply_message"] == "Following up in case this project is still active."


def test_expand_record_uses_latest_customer_reply_when_present():
    record = {
        "submission_id": "sub-3",
        "message": "Interested in a CAR-T quote.",
        "thread_messages": [
            {
                "timestamp": "2026-04-01T10:00:00Z",
                "message_id": "form-3",
                "role": "customer",
                "source": "form_submission",
                "text": "Interested in a CAR-T quote.",
            },
            {
                "timestamp": "2026-04-01T11:00:00Z",
                "message_id": "r1",
                "role": "sales",
                "source": "crm_email",
                "text": "Can you share the target and species?",
            },
            {
                "timestamp": "2026-04-01T12:00:00Z",
                "message_id": "c1",
                "role": "customer",
                "source": "crm_email",
                "text": "Target is CD19 and species is human.",
            },
            {
                "timestamp": "2026-04-01T13:00:00Z",
                "message_id": "r2",
                "role": "sales",
                "source": "crm_email",
                "text": "Perfect, I will prepare the quote.",
            },
        ],
    }

    rows = expand_record(record, skip_empty=False)

    assert len(rows) == 2
    assert rows[0]["customer_message"] == "Interested in a CAR-T quote."
    assert rows[0]["customer_message_source"] == "form_submission"
    assert rows[1]["customer_message"] == "Target is CD19 and species is human."
    assert rows[1]["customer_message_source"] == "customer_email"
    assert rows[1]["reply_message"] == "Perfect, I will prepare the quote."


def test_expand_record_clears_customer_message_for_second_sales_after_same_customer_reply():
    record = {
        "submission_id": "sub-4",
        "message": "Initial inquiry.",
        "thread_messages": [
            {
                "timestamp": "2026-04-01T10:00:00Z",
                "message_id": "form-4",
                "role": "customer",
                "source": "form_submission",
                "text": "Initial inquiry.",
            },
            {
                "timestamp": "2026-04-01T11:00:00Z",
                "message_id": "r1",
                "role": "sales",
                "source": "crm_email",
                "text": "First reply.",
            },
            {
                "timestamp": "2026-04-01T12:00:00Z",
                "message_id": "c1",
                "role": "customer",
                "source": "crm_email",
                "text": "Customer follow-up.",
            },
            {
                "timestamp": "2026-04-01T13:00:00Z",
                "message_id": "r2",
                "role": "sales",
                "source": "crm_email",
                "text": "Reply to follow-up.",
            },
            {
                "timestamp": "2026-04-01T13:05:00Z",
                "message_id": "r3",
                "role": "sales",
                "source": "crm_email",
                "text": "Additional follow-up without customer reply.",
            },
        ],
    }

    rows = expand_record(record, skip_empty=False)

    assert len(rows) == 3
    assert rows[1]["customer_message"] == "Customer follow-up."
    assert rows[1]["customer_message_source"] == "customer_email"
    assert rows[2]["customer_message"] == ""
    assert rows[2]["customer_message_source"] == ""


def test_expand_record_emits_placeholder_row_for_submissions_without_replies():
    record = {
        "submission_id": "sub-5",
        "message": "Do you offer mRNA-LNP formulation?",
        "thread_messages": [],
    }

    rows = expand_record(record, skip_empty=False)

    assert len(rows) == 1
    assert rows[0]["original_message"] == "Do you offer mRNA-LNP formulation?"
    assert rows[0]["customer_message"] == ""
    assert rows[0]["customer_message_source"] == ""
    assert rows[0]["reply_message"] == ""
    assert rows[0]["reply_total"] == 0
