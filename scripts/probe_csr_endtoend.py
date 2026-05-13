"""End-to-end probe: feed sample customer inquiries through run_email_agent and
print the parts a CSR cares about — routing decision, retrieved historical
references, tool execution, and the draft reply.

Run with:
  python scripts/probe_csr_endtoend.py
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(PROJECT_ROOT / ".env")

from src.api_models import AgentRequest  # noqa: E402
from src.app.service import run_email_agent  # noqa: E402

# Real inquiries pulled from PG `historical_threads` first-message rows.
SAMPLES = [
    {
        "label": "mRNA/LNP — research+gmp lipids + pre-tested formulations",
        "expected_service": "mRNA / LNP Production",
        "query": (
            "Hello, I am working with a Canadian National pandemic preparedness "
            "project called AVENGER and am looking for proprietary lipids that "
            "are available in research grade and gmp grade. I would also be "
            "interested in pre-tested formulations in the areas of infectious "
            "disease (bacterial) and oncology. Thank you."
        ),
    },
    {
        "label": "Lentivirus / CAR-T — CAR lentiviral particles for CD19/CD20/CD33 quote",
        "expected_service": "Lentivirus Production",
        "query": (
            "Dear ProMab Team, I am looking for CAR lentiviral particles "
            "(against CD19, CD20 or CD33). Since you offer both CAR-cells and "
            "a virus production service, I was wondering if you also offer "
            "lentiviral particles for such CARs. Could you please send me a "
            "quote if you offer CAR viruses? Thank you and kind regards."
        ),
    },
    {
        "label": "Catalog lookup — MSLN Antibody #31741 immunogen sequence",
        "expected_service": "Human Monoclonal Antibodies",
        "query": (
            "Hello ProMab Tech Support, this is Michael from Thermo Fisher "
            "Technical Support. Could you share the immunogen binding sequence "
            "of the MSLN Primary Antibody, Catalog 31741? A shared customer "
            "would like the specific amino-acid binding sequence on the "
            "mesothelin protein. Thanks for the help."
        ),
    },
    {
        "label": "Custom antibody generation — polyclonal + monoclonal vs microbial proteins",
        "expected_service": "Antibody Production",
        "query": (
            "Hello, we are interested in custom generation of antibodies "
            "(polyclonal and monoclonal) against selected proteins from a "
            "microbial source. I would like to discuss the options."
        ),
    },
]


def _fmt_section(title: str) -> str:
    bar = "=" * 78
    return f"\n{bar}\n{title}\n{bar}"


def _summarize_thread(thread: dict) -> str:
    units = thread.get("units") or []
    if not units:
        return "<empty>"
    first = units[0]
    inst = first.get("institution") or "?"
    svc = first.get("service_of_interest") or "?"
    products = first.get("products_of_interest") or "?"
    sim = thread.get("similarity") or thread.get("score") or "?"
    return f"institution={inst} | service={svc} | products={products} | similarity={sim}"


def _extract_historical_threads(execution_run: dict) -> list[dict]:
    for action in execution_run.get("executed_actions", []):
        if action.get("tool_name") != "historical_thread_tool":
            continue
        return (action.get("output") or {}).get("threads") or []
    return []


def _extract_doc_refs(content_blocks: list[dict]) -> list[dict]:
    out = []
    for block in content_blocks:
        if block.get("kind") in ("service_primary_document", "documentation_chunks"):
            out.append({"kind": block.get("kind"), "title": block.get("title", "")})
    return out


def _print_one(sample: dict) -> None:
    print(_fmt_section(f"INQUIRY: {sample['label']}"))
    print(f"Expected service hint: {sample['expected_service']}")
    print()
    print("Query:")
    print(f"  {sample['query']}")

    request = AgentRequest(
        thread_id=f"probe-{uuid.uuid4().hex[:8]}",
        user_query=sample["query"],
        locale="en",
        start_new_conversation=True,
    )
    response = run_email_agent(request)

    routing = response.agent_input.get("routing_debug", {})
    print(_fmt_section("ROUTING"))
    print(f"  semantic_intent      : {routing.get('intent')}")
    print(f"  intent_confidence    : {routing.get('intent_confidence')}")
    print(f"  dialogue_act         : {routing.get('dialogue_act')}")
    print(f"  business_line        : {routing.get('business_line')}")
    print(f"  primary_object       : {response.agent_input.get('active_service_name') or response.agent_input.get('active_product_name') or '<none>'}")
    print(f"  action               : {routing.get('action')}")
    print(f"  has_clarification    : {routing.get('has_clarification')}")

    plan = response.execution_plan or {}
    print(_fmt_section("TOOLS PLANNED & EXECUTED"))
    if not plan.get("planned_actions"):
        print("  <no tools planned>")
    for a in plan.get("planned_actions", []):
        print(f"  - {a.get('tool_name')} (role={a.get('role')})")

    run = response.execution_run or {}
    print(f"  overall_status: {run.get('overall_status')}")
    for a in run.get("executed_actions", []):
        summary = (a.get("summary") or "").strip().replace("\n", " ")[:120]
        print(f"  - {a.get('tool_name')}: status={a.get('status')} latency={a.get('latency_ms')}ms")
        if summary:
            print(f"      → {summary}")

    threads = _extract_historical_threads(run)
    print(_fmt_section(f"HISTORICAL REFERENCES ({len(threads)} retrieved)"))
    for i, t in enumerate(threads[:5], 1):
        print(f"  [{i}] {_summarize_thread(t)}")

    blocks = response.response_content_blocks or []
    docs = _extract_doc_refs(blocks)
    print(_fmt_section("DOCUMENT REFERENCES"))
    if not docs:
        print("  <none>")
    for d in docs:
        print(f"  - kind={d['kind']} title={d['title']}")

    print(_fmt_section("DRAFT REPLY"))
    print(response.final_response.message or response.reply_preview or "<empty>")


def main() -> None:
    for sample in SAMPLES:
        try:
            _print_one(sample)
        except Exception as exc:  # noqa: BLE001
            print(f"\n!!! {sample['label']} failed: {exc!r}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
