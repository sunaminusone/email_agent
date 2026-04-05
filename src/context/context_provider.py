from __future__ import annotations

from src.context.providers import ChatHistoryProvider, KnowledgeProvider, UserPreferenceProvider
from src.schemas import AgentContext, RuntimeContext


class ContextProvider:
    def __init__(
        self,
        *,
        chat_history_provider: ChatHistoryProvider | None = None,
        user_preference_provider: UserPreferenceProvider | None = None,
        knowledge_provider: KnowledgeProvider | None = None,
    ) -> None:
        self.chat_history_provider = chat_history_provider or ChatHistoryProvider()
        self.user_preference_provider = user_preference_provider or UserPreferenceProvider()
        self.knowledge_provider = knowledge_provider or KnowledgeProvider()

    def build(self, agent_context: AgentContext) -> RuntimeContext:
        conversation_memory = self.chat_history_provider.load(agent_context)
        user_preference = self.user_preference_provider.load(agent_context)
        knowledge_context = self.knowledge_provider.load(agent_context)
        return RuntimeContext(
            agent_context=agent_context,
            conversation_memory=conversation_memory,
            user_preference=user_preference,
            knowledge_context=knowledge_context,
        )
