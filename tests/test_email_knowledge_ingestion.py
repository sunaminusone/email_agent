from __future__ import annotations

from pathlib import Path
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.email_knowledge_extraction import (
    annotate_fact_records_for_review,
    fact_record_to_documents,
    facts_to_ingestion_sections,
    load_email_knowledge_documents,
    parse_response_payload,
)


def test_facts_to_ingestion_sections_filters_unknown_business_line() -> None:
    facts = [
        {
            "category": "policy",
            "fact": "ProMab requires an MTA before transferring the cell line.",
            "tags": ["MTA", "cell line"],
            "business_line": "cell_based_assays",
            "service_name": "",
            "confidence": 0.9,
            "source_snippet": "We need an MTA signed before cell line transfer.",
        },
        {
            "category": "policy",
            "fact": "This should be dropped because the business line is invalid.",
            "tags": ["invalid"],
            "business_line": "general",
            "service_name": "",
            "confidence": 0.2,
            "source_snippet": "invalid",
        },
    ]

    sections = facts_to_ingestion_sections(facts, source_email_index=12)

    assert len(sections) == 1
    assert sections[0].section_type == "email_knowledge"
    assert sections[0].source_path == "email_index:12"
    assert "policy" in sections[0].tags
    assert "cell_based_assays" in sections[0].tags


def test_fact_record_to_documents_builds_prechunked_documents() -> None:
    record = {
        "email_index": 7,
        "facts": [
            {
                "category": "pricing_timeline",
                "fact": "ProMab can deliver a standard ELISA method development project within 4 weeks.",
                "tags": ["ELISA", "timeline"],
                "business_line": "cell_based_assays",
                "service_name": "",
                "confidence": 0.81,
                "source_snippet": "Standard ELISA development can be finished in four weeks.",
            }
        ],
    }

    documents = fact_record_to_documents(record, source_path="facts.jsonl#L1")

    assert len(documents) == 1
    document = documents[0]
    assert document.metadata["prechunked"] is True
    assert document.metadata["source_format"] == "email_knowledge_jsonl"
    assert document.metadata["source_path"] == "facts.jsonl#L1"
    assert document.metadata["section_type"] == "email_knowledge"
    assert document.metadata["business_line"] == "cell_based_assays"
    assert "body:" in document.page_content


def test_load_email_knowledge_documents_reads_jsonl_records(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "rag_email_facts.jsonl"
    rows = [
        {
            "email_index": 1,
            "facts": [
                {
                    "category": "service_capability",
                    "fact": "ProMab supports recombinant antibody production for rabbit monoclonal programs.",
                    "tags": ["recombinant antibody", "rabbit monoclonal"],
                    "business_line": "antibody",
                    "service_name": "Recombinant Antibody Production",
                    "confidence": 0.88,
                    "source_snippet": "We support recombinant antibody production for rabbit monoclonal projects.",
                }
            ],
        },
        {
            "email_index": 2,
            "facts": [
                {
                    "category": "technical_protocol",
                    "fact": "ProMab recommends 1-2 ug/mL coating concentration for this ELISA workflow.",
                    "tags": ["ELISA", "coating concentration"],
                    "business_line": "cell_based_assays",
                    "service_name": "",
                    "confidence": 0.76,
                    "source_snippet": "We typically recommend 1-2 ug/mL for coating.",
                }
            ],
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    documents = load_email_knowledge_documents(jsonl_path)

    assert len(documents) == 2
    assert all(doc.metadata["source_format"] == "email_knowledge_jsonl" for doc in documents)
    assert str(jsonl_path) in documents[0].metadata["source_path"]


def test_load_email_knowledge_documents_can_filter_unapproved_records(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "rag_email_facts.jsonl"
    rows = [
        {
            "email_index": 1,
            "approved": False,
            "facts": [
                {
                    "category": "service_capability",
                    "fact": "Pending fact.",
                    "tags": ["pending"],
                    "business_line": "antibody",
                    "service_name": "",
                    "confidence": 0.4,
                    "source_snippet": "Pending.",
                }
            ],
        },
        {
            "email_index": 2,
            "approved": True,
            "facts": [
                {
                    "category": "policy",
                    "fact": "Approved fact.",
                    "tags": ["approved"],
                    "business_line": "cell_based_assays",
                    "service_name": "",
                    "confidence": 0.9,
                    "source_snippet": "Approved.",
                }
            ],
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )

    documents = load_email_knowledge_documents(jsonl_path, approved_only=True)

    assert len(documents) == 1
    assert "Approved fact." in documents[0].page_content


def test_annotate_fact_records_for_review_sets_pending_defaults() -> None:
    records = [{"email_index": 3, "facts": [{"fact": "x"}]}]

    annotated = annotate_fact_records_for_review(records)

    assert annotated[0]["review_status"] == "pending"
    assert annotated[0]["approved"] is False


def test_parse_response_payload_handles_markdown_json_code_fence() -> None:
    raw_response = """```json
{"facts":[{"fact":"A","business_line":"antibody"}]}
```"""

    facts = parse_response_payload(raw_response)

    assert len(facts) == 1
    assert facts[0]["fact"] == "A"
