const form = document.getElementById("agent-form");
const submitButton = document.getElementById("submit-btn");
const clearChatButton = document.getElementById("clear-chat-btn");
const newChatButton = document.getElementById("new-chat-btn");
const parsedResult = document.getElementById("parsed_result");
const agentInput = document.getElementById("agent_input");
const replyPreview = document.getElementById("reply_preview");
const workflow = document.getElementById("workflow");
const executionPlan = document.getElementById("execution_plan");
const executionRun = document.getElementById("execution_run");
const responseResolution = document.getElementById("response_resolution");
const responseTopicSummary = document.getElementById("response_topic_summary");
const responseContentBlocks = document.getElementById("response_content_blocks");
const documentResults = document.getElementById("document_results");
const technicalResults = document.getElementById("technical_results");
const routeResult = document.getElementById("route_result");
const routingSignals = document.getElementById("routing_signals");
const routingSummary = document.getElementById("routing_summary");
const secondaryRoutesSummary = document.getElementById("secondary_routes_summary");
const chatHistory = document.getElementById("chat_history");
const historyNav = document.getElementById("history_nav");
const intentTags = document.getElementById("intent_tags");
const currentIntent = document.getElementById("current_intent");
const currentConfidence = document.getElementById("current_confidence");
const currentRoute = document.getElementById("current_route");
const currentStatus = document.getElementById("current_status");
const sessionHint = document.getElementById("session_hint");

const CHAT_STORAGE_KEY = "email_agent.chat_messages";
const THREAD_STORAGE_KEY = "email_agent.thread_id";

let messages = [];
let threadId = "";

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function createThreadId() {
  if (window.crypto?.randomUUID) {
    return `thread-${window.crypto.randomUUID()}`;
  }

  return `thread-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function ensureThreadId() {
  if (!threadId) {
    threadId = window.localStorage.getItem(THREAD_STORAGE_KEY) || createThreadId();
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
  }
  return threadId;
}

function syncStoredMessages() {
  window.localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages));
}

function renderSessionHint() {
  const activeThreadId = ensureThreadId();
  sessionHint.textContent = `Session linked to ${activeThreadId.slice(0, 18)}...`;
}

function renderChatHistory() {
  if (!messages.length) {
    chatHistory.innerHTML = `
      <div class="chat-empty-state">
        <p class="chat-empty-title">Start a new conversation</p>
        <p class="chat-empty">Ask about a product, request a quote, or retrieve technical documentation.</p>
      </div>
    `;
    return;
  }

  chatHistory.innerHTML = messages.map((message) => {
    const roleClass = message.role === "assistant" ? "chat-message-assistant" : "chat-message-user";
    const roleLabel = message.role === "assistant" ? "Assistant" : "User";
    const metaParts = [];

    if (message.metadata?.response_type) {
      metaParts.push(`type: ${message.metadata.response_type}`);
    }
    if (message.metadata?.response_topic) {
      metaParts.push(`topic: ${message.metadata.response_topic}`);
    }
    if (message.metadata?.response_path) {
      metaParts.push(`path: ${message.metadata.response_path}`);
    }
    if (message.metadata?.route_state?.active_route) {
      metaParts.push(`route: ${message.metadata.route_state.active_route}`);
    }

    const metaLine = metaParts.length
      ? `<div class="chat-meta">${escapeHtml(metaParts.join(" | "))}</div>`
      : "";
    const documentLinks = (message.metadata?.documents || []).map((doc) => `
      <a class="document-link" href="${escapeHtml(doc.document_url || "")}" target="_blank" rel="noopener noreferrer">Open document</a>
      <a class="document-link" href="${escapeHtml(doc.document_url || "")}" download>Download document</a>
    `).join("");
    const documentSection = documentLinks
      ? `<div class="document-actions chat-document-actions">${documentLinks}</div>`
      : "";

    return `
      <div class="chat-message ${roleClass}">
        <strong>${roleLabel}</strong><br />
        ${escapeHtml(message.content || "")}
        ${documentSection}
        ${metaLine}
      </div>
    `;
  }).join("");

  chatHistory.scrollTop = chatHistory.scrollHeight;
}

function renderHistoryNav() {
  if (!messages.length) {
    historyNav.innerHTML = '<p class="history-empty">No conversation yet.</p>';
    return;
  }

  const items = [];
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    if (message.role !== "user") {
      continue;
    }

    const preview = (message.content || "").trim() || "Untitled conversation";
    const shortened = preview.length > 56 ? `${preview.slice(0, 56)}...` : preview;
    items.push(`
      <article class="history-item">
        <p class="history-item-title">${escapeHtml(shortened)}</p>
        <p class="history-item-meta">User message ${items.length + 1}</p>
      </article>
    `);
  }

  historyNav.innerHTML = items.join("") || '<p class="history-empty">No conversation yet.</p>';
}

function updateAgentOverview({ intent = "Awaiting input", confidence = "-", route = "-", status = "Idle" }) {
  currentIntent.textContent = intent;
  currentConfidence.textContent = confidence;
  currentRoute.textContent = route;
  currentStatus.textContent = status;
}

function renderIntentTags(tags = ["Product Inquiry", "Pricing", "Technical Question"]) {
  intentTags.innerHTML = tags.map((tag) => `<span class="intent-tag">${escapeHtml(tag)}</span>`).join("");
}

function resetInspectorPanels(errorMessage = "等待输入...") {
  replyPreview.textContent = errorMessage;
  executionPlan.textContent = "{}";
  executionRun.textContent = "{}";
  responseResolution.textContent = "{}";
  routeResult.textContent = "{}";
  parsedResult.textContent = "{}";
  agentInput.textContent = "{}";
  responseTopicSummary.innerHTML = '<p class="signal-state">当前没有可展示的 response topic。</p>';
  responseContentBlocks.innerHTML = '<p class="signal-state">当前没有可展示的内容块。</p>';
  documentResults.innerHTML = '<p class="signal-state">当前没有可展示的文档结果。</p>';
  technicalResults.innerHTML = '<p class="signal-state">当前没有可展示的技术检索结果。</p>';
  updateAgentOverview({});
  renderIntentTags();
  renderSecondaryRoutes({});
  renderRoutingSignals({});
  renderWorkflow([]);
}

function buildUserMessage(content) {
  return {
    role: "user",
    content,
    metadata: {},
  };
}

function normalizeAssistantMessage(output) {
  const documentAction = (output.execution_run?.executed_actions || []).find(
    (action) => action.action_type === "lookup_document",
  );
  const documents = (documentAction?.output?.matches || [])
    .filter((match) => match.document_url)
    .slice(0, 3)
    .map((match) => ({
      file_name: match.file_name || "",
      document_url: match.document_url || "",
    }));
  const baseMessage = output.assistant_message || {
    role: "assistant",
    content: output.final_response?.message || output.reply_preview || "",
    metadata: {
      response_type: output.final_response?.response_type || "answer",
    },
  };

  return {
    ...baseMessage,
    metadata: {
      ...(baseMessage.metadata || {}),
      response_type: baseMessage.metadata?.response_type || output.final_response?.response_type || "answer",
      response_topic: baseMessage.metadata?.response_topic || output.response_topic || "",
      response_path: baseMessage.metadata?.response_path || output.response_path || "",
      documents,
    },
  };
}

try {
  messages = JSON.parse(window.localStorage.getItem(CHAT_STORAGE_KEY) || "[]");
} catch (_error) {
  messages = [];
}
ensureThreadId();
renderSessionHint();
renderChatHistory();
renderHistoryNav();
renderIntentTags();
updateAgentOverview({});

function renderWorkflow(items) {
  workflow.innerHTML = "";

  if (!items.length) {
    const empty = document.createElement("li");
    empty.textContent = "暂无建议步骤";
    workflow.appendChild(empty);
    return;
  }

  items.forEach((item) => {
    const entry = document.createElement("li");
    entry.textContent = item;
    workflow.appendChild(entry);
  });
}

function renderRoutingSignals(signals) {
  routingSignals.textContent = JSON.stringify(signals || {}, null, 2);

  if (!signals || !Object.keys(signals).length) {
    routingSummary.innerHTML = '<p class="signal-state">当前没有可展示的路由证据。</p>';
    updateAgentOverview({});
    return;
  }

  const businessLine = signals.business_line || "unknown";
  const businessLineConfidence = signals.business_line_confidence || "unknown";
  const engagementType = signals.engagement_type || "unknown";
  const customizationScore = signals.customization_score ?? "n/a";
  const grayReasons = signals.gray_zone_reasons || [];
  const badgeClass = signals.is_gray_zone ? "signal-badge signal-badge-gray" : "signal-badge signal-badge-clear";
  const badgeText = signals.is_gray_zone ? "灰区，交给 LLM 仲裁" : "高置信度，规则直接通过";
  const reasonsText = grayReasons.length ? grayReasons.join(" / ") : "无";
  const intent = signals.engagement_type || signals.intent || "Routed request";
  const confidence = signals.business_line_confidence ?? signals.intent_confidence ?? "unknown";

  routingSummary.innerHTML = `
    <div class="${badgeClass}">${badgeText}</div>
    <p class="signal-line"><strong>Business Line Hint:</strong> ${businessLine}</p>
    <p class="signal-line"><strong>Hint Confidence:</strong> ${businessLineConfidence}</p>
    <p class="signal-line"><strong>Engagement Type:</strong> ${engagementType}</p>
    <p class="signal-line"><strong>Customization Score:</strong> ${customizationScore}</p>
    <p class="signal-line"><strong>灰区原因:</strong> ${reasonsText}</p>
  `;

  updateAgentOverview({
    intent,
    confidence: String(confidence),
    route: signals.active_route || signals.route_name || businessLine || "-",
    status: signals.is_gray_zone ? "Reviewing" : "Ready",
  });
}

function renderSecondaryRoutes(route) {
  const secondaryRoutes = route?.secondary_routes || [];
  const blockingPrimaryRoutes = new Set(["human_review", "complaint_review", "clarification_request"]);

  if (!secondaryRoutes.length) {
    secondaryRoutesSummary.innerHTML = '<p class="signal-state">当前没有检测到次路由。</p>';
    return;
  }

  const modeText = blockingPrimaryRoutes.has(route.route_name)
    ? "当前主路由是 blocking，次路由先挂起为待办。"
    : "当前主路由是 non-blocking，次路由可作为补充检索参考。";

  secondaryRoutesSummary.innerHTML = `
    <p class="signal-line"><strong>处理策略:</strong> ${modeText}</p>
    <p class="signal-line"><strong>Secondary Routes:</strong> ${secondaryRoutes.join(", ")}</p>
  `;
}

function renderDocumentResults(executionRunPayload) {
  const executedActions = executionRunPayload?.executed_actions || [];
  const documentAction = executedActions.find((action) => action.action_type === "lookup_document");

  if (!documentAction) {
    documentResults.innerHTML = '<p class="signal-state">当前没有执行文档检索动作。</p>';
    return;
  }

  const matches = documentAction.output?.matches || [];
  const requestedTypes = documentAction.output?.requested_document_types || [];

  if (!matches.length) {
    documentResults.innerHTML = `
      <p class="signal-line"><strong>执行状态:</strong> ${documentAction.status || "unknown"}</p>
      <p class="signal-line"><strong>请求类型:</strong> ${requestedTypes.join(", ") || "未识别"}</p>
      <p class="signal-line">没有找到匹配的文件。</p>
    `;
    return;
  }

  const items = matches.map((match) => `
    <div class="document-item">
      <p class="document-title">${match.file_name}</p>
      <p class="document-meta">类型: ${match.document_type || "general"} | 分数: ${match.score ?? "n/a"}</p>
      <p class="document-path">${match.source_path}</p>
      ${match.document_url ? `
        <p class="document-actions">
          <a class="document-link" href="${match.document_url}" target="_blank" rel="noopener noreferrer">Open document</a>
          <a class="document-link" href="${match.document_url}" download>Download document</a>
        </p>
      ` : ""}
    </div>
  `).join("");

  documentResults.innerHTML = `
    <p class="signal-line"><strong>执行状态:</strong> ${documentAction.status || "unknown"}</p>
    <p class="signal-line"><strong>请求类型:</strong> ${requestedTypes.join(", ") || "未识别"}</p>
    <div class="document-list">${items}</div>
  `;
}

function renderTechnicalResults(executionRunPayload) {
  const executedActions = executionRunPayload?.executed_actions || [];
  const technicalAction = executedActions.find((action) => action.action_type === "retrieve_technical_knowledge");

  if (!technicalAction) {
    technicalResults.innerHTML = '<p class="signal-state">当前没有执行技术检索动作。</p>';
    return;
  }

  const matches = technicalAction.output?.matches || [];
  if (!matches.length) {
    technicalResults.innerHTML = `
      <p class="signal-line"><strong>执行状态:</strong> ${technicalAction.status || "unknown"}</p>
      <p class="signal-line">没有找到匹配的技术片段。</p>
    `;
    return;
  }

  const items = matches.map((match) => `
    <div class="document-item">
      <p class="document-title">${match.file_name || "unknown source"}</p>
      <p class="document-meta">业务线: ${match.business_line || "unknown"} | 文档类型: ${match.document_type || "technical_text"}</p>
      <p class="document-meta">切块: ${match.chunk_strategy || "unknown"} / 结构标签: ${match.structural_tag || "n/a"} / 分数: ${match.score ?? "n/a"}</p>
      <p class="document-path">${match.source_path}</p>
      <p class="document-snippet">${match.content_preview || ""}</p>
    </div>
  `).join("");

  technicalResults.innerHTML = `
    <p class="signal-line"><strong>执行状态:</strong> ${technicalAction.status || "unknown"}</p>
    <p class="signal-line"><strong>Query Variants:</strong> ${(technicalAction.output?.query_variants || []).join(" | ") || "n/a"}</p>
    <div class="document-list">${items}</div>
  `;
}

function renderResponseTopic(output) {
  const topic = output.response_topic || output.response_resolution?.topic_type || "";
  const resolution = output.response_resolution || {};
  if (!topic) {
    responseTopicSummary.innerHTML = '<p class="signal-state">当前没有可展示的 response topic。</p>';
    return;
  }

  responseTopicSummary.innerHTML = `
    <p class="signal-line"><strong>Topic:</strong> ${escapeHtml(topic)}</p>
    <p class="signal-line"><strong>Style:</strong> ${escapeHtml(resolution.reply_style || "n/a")}</p>
    <p class="signal-line"><strong>Focus:</strong> ${escapeHtml(resolution.answer_focus || "n/a")}</p>
    <p class="signal-line"><strong>Primary Action:</strong> ${escapeHtml(resolution.primary_action_type || "n/a")}</p>
    <p class="signal-line"><strong>Response Path:</strong> ${escapeHtml(output.response_path || "n/a")}</p>
  `;
}

function renderResponseContentBlocks(output) {
  const blocks = output.response_content_blocks || [];
  if (!blocks.length) {
    responseContentBlocks.innerHTML = '<p class="signal-state">当前没有可展示的内容块。</p>';
    return;
  }

  responseContentBlocks.innerHTML = `
    <div class="content-block-list">
      ${blocks.map((block, index) => `
        <div class="content-block-item">
          <p class="content-block-title">${index + 1}. ${escapeHtml(block.kind || "unknown")}</p>
          <p class="content-block-text">${escapeHtml(block.text || "")}</p>
        </div>
      `).join("")}
    </div>
  `;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const userQueryField = document.getElementById("user_query");
  const userQuery = userQueryField.value.trim();

  if (!userQuery) {
    return;
  }

  submitButton.disabled = true;
  submitButton.textContent = "发送中...";

  try {
    const userMessage = buildUserMessage(userQuery);
    const payload = {
      thread_id: ensureThreadId(),
      user_query: userQuery,
      attachments: [],
    };

    messages = [...messages, userMessage];
    syncStoredMessages();
    renderChatHistory();
    renderHistoryNav();
    renderIntentTags(["Classifying intent", "Checking sources", "Preparing response"]);
    updateAgentOverview({
      intent: "Analyzing request",
      confidence: "-",
      route: "Pending",
      status: "Retrieving",
    });
    userQueryField.value = "";

    const response = await fetch("/email-agent/invoke", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ input: payload }),
    });

    if (!response.ok) {
      const message = await response.text();
      throw new Error(message || "请求失败");
    }

    const data = await response.json();
    const output = data.output || {};
    const assistantMessage = normalizeAssistantMessage(output);

    messages = [...messages, assistantMessage];
    syncStoredMessages();
    renderChatHistory();
    renderHistoryNav();
    if (output.agent_input?.thread_id) {
      threadId = output.agent_input.thread_id;
      window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
      renderSessionHint();
    }

    replyPreview.textContent = output.reply_preview || "";
    executionPlan.textContent = JSON.stringify(output.execution_plan || {}, null, 2);
    executionRun.textContent = JSON.stringify(output.execution_run || {}, null, 2);
    responseResolution.textContent = JSON.stringify(output.response_resolution || {}, null, 2);
    routeResult.textContent = JSON.stringify(output.route || {}, null, 2);
    parsedResult.textContent = JSON.stringify(output.parsed || {}, null, 2);
    agentInput.textContent = JSON.stringify(output.agent_input || {}, null, 2);
    renderResponseTopic(output);
    renderResponseContentBlocks(output);
    renderDocumentResults(output.execution_run || {});
    renderTechnicalResults(output.execution_run || {});
    renderSecondaryRoutes(output.route || {});
    renderRoutingSignals(output.agent_input?.routing_debug || {});
    renderWorkflow(output.suggested_workflow || []);

    const derivedTags = [];
    if (output.route?.route_name) {
      derivedTags.push(output.route.route_name.replaceAll("_", " "));
    }
    if (output.final_response?.response_type) {
      derivedTags.push(output.final_response.response_type.replaceAll("_", " "));
    }
    if (output.execution_run?.executed_actions?.length) {
      derivedTags.push(...output.execution_run.executed_actions.slice(0, 2).map((action) => action.action_type.replaceAll("_", " ")));
    }
    renderIntentTags(derivedTags.length ? derivedTags : undefined);
  } catch (error) {
    if (messages.length && messages[messages.length - 1].role === "user") {
      messages = messages.slice(0, -1);
      syncStoredMessages();
      renderChatHistory();
      renderHistoryNav();
    }
    resetInspectorPanels(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "发送消息";
  }
});

clearChatButton.addEventListener("click", () => {
  messages = [];
  threadId = createThreadId();
  window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
  syncStoredMessages();
  renderChatHistory();
  renderHistoryNav();
  renderSessionHint();
  resetInspectorPanels();
});

newChatButton.addEventListener("click", () => {
  messages = [];
  threadId = createThreadId();
  window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
  syncStoredMessages();
  renderChatHistory();
  renderHistoryNav();
  renderSessionHint();
  resetInspectorPanels();
  document.getElementById("user_query").focus();
});
