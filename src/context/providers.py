from __future__ import annotations

from typing import List

from src.memory import SessionStore
from src.schemas import (
    AgentContext,
    ConversationMemory,
    ConversationTurn,
    KnowledgeContext,
    KnowledgeSnippet,
    UserPreference,
)


class ChatHistoryProvider:
    def __init__(self, session_store: SessionStore | None = None) -> None:
        self.session_store = session_store or SessionStore()

    def _fallback_route_state(self, raw_turns: List[dict]) -> dict:
        for message in reversed(raw_turns):
            metadata = message.get("metadata", {}) or {}
            route_state = metadata.get("route_state")
            if isinstance(route_state, dict):
                return route_state
        return {}

    def load(self, agent_context: AgentContext) -> ConversationMemory:
        session = self.session_store.load_session(agent_context.thread_id)
        session_turns = session.get("recent_turns", [])
        source = "redis_session" if session_turns else "conversation_history"
        raw_turns = session_turns or agent_context.conversation_history[-8:]
        route_state = session.get("route_state", {}) or self._fallback_route_state(raw_turns)
        turns = [
            ConversationTurn(
                role=message.get("role", "user"),
                content=message.get("content", ""),
                metadata=message.get("metadata", {}) or {},
            )
            for message in raw_turns[-20:]
        ]

        recent_summary = " | ".join(
            f"{turn.role}: {turn.content[:120]}".strip()
            for turn in turns[-4:]
            if turn.content
        )
        return ConversationMemory(
            thread_id=agent_context.thread_id,
            source=source,
            turns=turns,
            route_state=route_state,
            recent_summary=recent_summary,
            updated_at=session.get("updated_at", ""),
        )


class UserPreferenceProvider:
    def load(self, agent_context: AgentContext) -> UserPreference:
        company_names = list(agent_context.entities.company_names)
        return UserPreference(
            source="database",
            lookup_status="not_configured",
            known_company_names=company_names,
            notes=["Persistent user preference storage is not configured yet."],
        )


class KnowledgeProvider:
    def _should_lookup_documents(self, agent_context: AgentContext) -> bool:
        return bool(
            agent_context.request_flags.needs_documentation
            or agent_context.entities.document_names
        )

    def _should_lookup_technical(self, agent_context: AgentContext) -> bool:
        return bool(
            agent_context.request_flags.needs_troubleshooting
            or agent_context.request_flags.needs_protocol
            or agent_context.request_flags.needs_regulatory_info
            or agent_context.context.primary_intent in {"technical_question", "troubleshooting"}
        )

    def load(self, agent_context: AgentContext) -> KnowledgeContext:
        snippets: List[KnowledgeSnippet] = []
        lookup_status = "not_requested"

        if self._should_lookup_documents(agent_context):
            from src.documents.service import lookup_documents

            lookup_status = "completed"
            docs = lookup_documents(
                query=agent_context.retrieval_query or agent_context.effective_query or agent_context.query,
                catalog_numbers=list(agent_context.entities.catalog_numbers),
                product_names=list(agent_context.entities.product_names),
                document_names=list(agent_context.entities.document_names),
                business_line_hint=agent_context.routing_debug.business_line,
                top_k=3,
            )
            for match in docs.get("matches", []):
                snippets.append(
                    KnowledgeSnippet(
                        snippet_type="document",
                        title=match.get("file_name", ""),
                        source_path=match.get("source_path", ""),
                        document_type=match.get("document_type", ""),
                        score=float(match.get("score", 0.0)),
                        content_preview=(
                            f"Matched tokens: {', '.join(match.get('matched_tokens', []))}"
                            if match.get("matched_tokens")
                            else ""
                        ),
                        metadata={
                            "requested_document_types": docs.get("requested_document_types", []),
                        },
                    )
                )

        if self._should_lookup_technical(agent_context):
            from src.rag.service import retrieve_technical_knowledge

            lookup_status = "completed"
            technical = retrieve_technical_knowledge(
                query=agent_context.retrieval_query or agent_context.effective_query or agent_context.query,
                business_line_hint=agent_context.routing_debug.business_line,
                retrieval_hints=agent_context.retrieval_hints.model_dump(mode="json"),
                product_names=list(agent_context.entities.product_names),
                service_names=list(agent_context.entities.service_names),
                targets=list(agent_context.entities.targets),
                top_k=3,
            )
            for match in technical.get("matches", []):
                snippets.append(
                    KnowledgeSnippet(
                        snippet_type="technical",
                        title=match.get("file_name", "") or match.get("chunk_label", ""),
                        source_path=match.get("source_path", ""),
                        document_type=match.get("document_type", ""),
                        score=float(match.get("score", 0.0)),
                        content_preview=match.get("content_preview", ""),
                        metadata={
                            "business_line": match.get("business_line", "unknown"),
                            "query_variant": match.get("query_variant", ""),
                            "chunk_strategy": match.get("chunk_strategy", ""),
                        },
                    )
                )

        if not snippets and lookup_status == "completed":
            lookup_status = "empty"

        return KnowledgeContext(
            source="rag",
            lookup_status=lookup_status,
            snippets=snippets,
        )
                                    
