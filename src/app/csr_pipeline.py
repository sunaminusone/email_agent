"""CSR-mode pipeline: retrieval + (Day 2) drafting for the agent's pivot.

The traditional `run_email_agent` in src/app/service.py builds a customer-
facing reply through clarify / handoff / route_decision logic. CSR mode is
different: the consumer is a customer-service rep, not the customer. So we
bypass routing, run both knowledge sources in parallel, and return raw
material the rep can use to draft a reply themselves.

Day 1 ships retrieve-only output. Day 2 adds an LLM composer that produces
a Slack-style draft reply alongside the references.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class CSRBundle:
    query: str
    historical_threads: list[dict[str, Any]] = field(default_factory=list)
    document_matches: list[dict[str, Any]] = field(default_factory=list)
    draft_reply: str = ""
    debug: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_csr_pipeline(query: str, *, top_k_docs: int = 5) -> CSRBundle:
    """Fetch both knowledge sources for a CSR-facing inquiry.

    Both retrievals run with the raw query — no parser scope, no clarify
    routing. The CSR sees everything; they decide what's relevant.
    """
    query = (query or "").strip()
    bundle = CSRBundle(query=query)

    if not query:
        return bundle

    from src.rag.historical_threads import retrieve_historical_threads
    from src.rag.service import retrieve_technical_knowledge

    historical = retrieve_historical_threads(query=query, top_k=8, thread_limit=3)
    bundle.historical_threads = historical.get("threads", [])
    bundle.debug["historical_matches_total"] = len(historical.get("matches", []))

    technical = retrieve_technical_knowledge(query=query, top_k=top_k_docs)
    bundle.document_matches = technical.get("matches", [])
    bundle.debug["technical_documents_found"] = technical.get("documents_found", 0)
    bundle.debug["technical_retrieval_confidence"] = technical.get("confidence", {})

    # Day 2: composer fills bundle.draft_reply
    return bundle


__all__ = ["CSRBundle", "run_csr_pipeline"]
