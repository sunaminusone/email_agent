const form = document.getElementById("agent-form");
const submitButton = document.getElementById("submit-btn");
const clearChatButton = document.getElementById("clear-chat-btn");
const newChatButton = document.getElementById("new-chat-btn");
const parsedResult = document.getElementById("parsed_result");
const agentInput = document.getElementById("agent_input");
const workflow = document.getElementById("workflow");
const executionPlan = document.getElementById("execution_plan");
const executionRun = document.getElementById("execution_run");
const answerFocusEl = document.getElementById("answer_focus");
const responseTopicSummary = document.getElementById("response_topic_summary");
const responseContentBlocks = document.getElementById("response_content_blocks");
const documentResults = document.getElementById("document_results");
const technicalResults = document.getElementById("technical_results");
const historicalResults = document.getElementById("historical_results");
const trustSummary = document.getElementById("trust_summary");
const routingNoteSummary = document.getElementById("routing_note_summary");
const routeResult = document.getElementById("route_result");
const chatHistory = document.getElementById("chat_history");
const historyNav = document.getElementById("history_nav");
const sessionHint = document.getElementById("session_hint");
const questionSamples = document.getElementById("question_samples");
const refreshSamplesButton = document.getElementById("refresh-samples-btn");

const CHAT_STORAGE_KEY = "email_agent.chat_messages";
const THREAD_STORAGE_KEY = "email_agent.thread_id";

const SAMPLE_QUESTIONS = {
  product: [
    "Can you tell me more about your CAR-T cell line development service?",
    "What applications is your anti-CD3 antibody validated for?",
    "Do you offer custom peptide synthesis for immunogenicity studies?",
    "Please introduce your NPM1 mutation detection workflow.",
    "Which product would you recommend for western blot detection of GFP-tagged proteins?",
  ],
  pricing: [
    "Could you provide a quote for 5 mg custom peptide synthesis with HPLC purification?",
    "What is the price range for monoclonal antibody generation in rabbits?",
    "Please share the pricing for a pilot CAR construct design project.",
    "How much would flow cytometry validation cost for three target markers?",
    "Can you prepare a budgetary quote for ELISA kit development with two antigens?",
  ],
  technical: [
    "How does your hybridoma screening workflow work after mouse immunization?",
    "What QC checkpoints are included in your lentiviral packaging service?",
    "Can you explain the difference between peptide conjugation and carrier protein coupling?",
    "What readouts do you provide in your T cell functional assay package?",
    "How do you validate specificity for a custom phospho-antibody project?",
  ],
  timeline: [
    "What is the typical turnaround time for recombinant protein expression and purification?",
    "How long does a standard monoclonal antibody project usually take?",
    "When could you deliver a small-batch peptide order if we start this week?",
    "What is the lead time for custom plasmid construction and sequence verification?",
    "How many weeks are needed for CAR-T in vitro functional testing?",
  ],
  shipping: [
    "Do you ship antibodies on dry ice to California, and what is the typical transit time?",
    "Can you arrange international shipping for frozen PBMC samples to Singapore?",
    "What shipping documents are needed for protein samples sent to the EU?",
    "Do you provide tracking and temperature monitoring for cold-chain shipments?",
    "Can you split delivery for a multi-batch peptide synthesis order?",
  ],
  documentation: [
    "Could you send the datasheet and COA for your recombinant IL-2 protein?",
    "Do you have a protocol or application note for your ELISA development service?",
    "Please share any validation report for the anti-PD-1 antibody.",
    "Can you provide technical documentation for your stable cell line generation workflow?",
    "Is there a brochure or slide deck for your antibody humanization service?",
  ],
  order: [
    "Can you check the status of order PO-20481 and confirm the expected ship date?",
    "Has invoice INV-11892 already been issued for our last peptide order?",
    "Please help confirm whether sample receipt was logged for our CRO project.",
    "Can you verify if batch 2 of our recombinant protein order passed QC?",
    "We need an update on the shipping status for our custom antibody project.",
  ],
  reply: [
    "Draft a polite customer reply explaining that technical validation data will be shared after internal review.",
    "Help me write a concise email to follow up on a pending quote for antibody development.",
    "Please draft a customer-facing reply summarizing lead time, price, and shipping constraints.",
    "Write a professional response asking the client to confirm antigen sequence and purification grade.",
    "Generate a warm reply that offers both a datasheet and a call to discuss assay design.",
  ],
};

const SAMPLE_CATEGORY_LABELS = {
  product: "Product",
  pricing: "Pricing",
  technical: "Technical",
  timeline: "Timeline",
  shipping: "Shipping",
  documentation: "Docs",
  order: "Order",
  reply: "Draft",
};

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

function formatSlackInline(escaped) {
  return escaped
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*([^*\n]+)\*/g, "<strong>$1</strong>")
    .replace(/_([^_\n]+)_/g, "<em>$1</em>");
}

function formatSlackMessage(text) {
  const lines = String(text || "").split("\n");
  const out = [];
  for (const raw of lines) {
    const trimmed = raw.replace(/^\s+/, "");
    if (trimmed.startsWith(">")) {
      const inner = trimmed.replace(/^>\s?/, "");
      out.push(`<blockquote>${formatSlackInline(escapeHtml(inner))}</blockquote>`);
    } else if (trimmed.startsWith("•")) {
      const inner = trimmed.replace(/^•\s?/, "");
      out.push(`<div class="msg-bullet">${formatSlackInline(escapeHtml(inner))}</div>`);
    } else if (raw.trim() === "") {
      out.push("<br />");
    } else {
      out.push(`<div>${formatSlackInline(escapeHtml(raw))}</div>`);
    }
  }
  return out.join("");
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

function shuffleArray(items) {
  const copy = [...items];
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    [copy[index], copy[swapIndex]] = [copy[swapIndex], copy[index]];
  }
  return copy;
}

function pickSampleQuestions(count = 6) {
  const categories = shuffleArray(Object.keys(SAMPLE_QUESTIONS)).slice(0, count);
  return categories.map((category) => {
    const options = SAMPLE_QUESTIONS[category] || [];
    const question = options[Math.floor(Math.random() * options.length)] || "";
    return {
      category,
      label: SAMPLE_CATEGORY_LABELS[category] || category,
      question,
    };
  });
}

function applySampleQuestion(question) {
  const userQueryField = document.getElementById("user_query");
  userQueryField.value = question;
  userQueryField.focus();
  userQueryField.setSelectionRange(userQueryField.value.length, userQueryField.value.length);
}

function renderQuestionSamples() {
  const samples = pickSampleQuestions();
  questionSamples.innerHTML = samples.map((sample) => `
    <button type="button" class="question-sample-card" data-question="${escapeHtml(sample.question)}">
      <span class="question-sample-tag">${escapeHtml(sample.label)}</span>
      <span class="question-sample-text">${escapeHtml(sample.question)}</span>
    </button>
  `).join("");

  questionSamples.querySelectorAll(".question-sample-card").forEach((button) => {
    button.addEventListener("click", () => {
      applySampleQuestion(button.dataset.question || "");
    });
  });
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
    const isAssistant = message.role === "assistant";
    const roleClass = isAssistant ? "chat-message-assistant" : "chat-message-user";
    const roleLabel = isAssistant ? "Assistant" : "CSR";
    const metaParts = [];

    if (message.metadata?.response_type) {
      metaParts.push(`type: ${message.metadata.response_type}`);
    }
    if (message.metadata?.response_path) {
      metaParts.push(`path: ${message.metadata.response_path}`);
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

    const body = isAssistant
      ? `<div class="message-formatted">${formatSlackMessage(message.content || "")}</div>`
      : escapeHtml(message.content || "");

    return `
      <div class="chat-message ${roleClass}">
        <strong>${roleLabel}</strong>
        ${body}
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

function resetInspectorPanels(errorMessage = "等待输入...") {
  executionPlan.textContent = "{}";
  executionRun.textContent = "{}";
  routeResult.textContent = "{}";
  parsedResult.textContent = "{}";
  agentInput.textContent = "{}";
  answerFocusEl.textContent = "";
  responseTopicSummary.innerHTML = `<p class="signal-state">${escapeHtml(errorMessage)}</p>`;
  responseContentBlocks.innerHTML = `<p class="signal-state">${escapeHtml(errorMessage)}</p>`;
  documentResults.innerHTML = `<p class="signal-state">${escapeHtml(errorMessage)}</p>`;
  technicalResults.innerHTML = `<p class="signal-state">${escapeHtml(errorMessage)}</p>`;
  historicalResults.innerHTML = `<p class="signal-state">${escapeHtml(errorMessage)}</p>`;
  trustSummary.innerHTML = `<p class="signal-state">${escapeHtml(errorMessage)}</p>`;
  routingNoteSummary.innerHTML = '<p class="signal-state">No routing flag yet.</p>';
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
renderQuestionSamples();

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

function renderTrust(executionRunPayload) {
  const actions = executionRunPayload?.executed_actions || [];
  const tech = actions.find((a) => a.action_type === "retrieve_technical_knowledge");
  const hist = actions.find((a) => a.tool_name === "historical_thread_tool");
  const conf = tech?.output?.retrieval_confidence || {};
  const level = String(conf.level || "n/a").toLowerCase();
  const tierLabels = { high: "📈 High", medium: "📊 Medium", low: "⚠️ Low", "n/a": "—" };
  const tierLabel = tierLabels[level] || level;

  const docCount = (tech?.output?.matches || []).length;
  const histCount = (hist?.output?.threads || []).length;

  const fmt = (n) => Number.isFinite(n) ? Number(n).toFixed(2) : "n/a";

  trustSummary.innerHTML = `
    <p class="signal-line"><span class="trust-tier trust-tier-${level}">${tierLabel}</span></p>
    <p class="signal-line"><strong>Top score:</strong> ${fmt(conf.top_final_score)} · margin ${fmt(conf.top_margin)}</p>
    <p class="signal-line"><strong>Sources:</strong> ${histCount} similar past · ${docCount} docs</p>
  `;
}

function renderRoutingNote(output) {
  const reason = output?.route?.reason || "";
  if (!reason.startsWith("AI_ROUTING_NOTE")) {
    routingNoteSummary.innerHTML = '<p class="signal-state">No routing flag — agent took the confident execute path.</p>';
    return;
  }
  routingNoteSummary.innerHTML = `<p class="signal-line">${escapeHtml(reason)}</p>`;
}

function renderHistoricalThreads(executionRunPayload) {
  const actions = executionRunPayload?.executed_actions || [];
  const action = actions.find((a) => a.tool_name === "historical_thread_tool");
  if (!action) {
    historicalResults.innerHTML = '<p class="signal-state">No historical-thread retrieval ran.</p>';
    return;
  }
  const threads = action.output?.threads || [];
  if (!threads.length) {
    historicalResults.innerHTML = `
      <p class="signal-line"><strong>Status:</strong> ${escapeHtml(action.status || "unknown")}</p>
      <p class="signal-line">No similar past inquiries returned.</p>
    `;
    return;
  }

  const items = threads.slice(0, 3).map((thread, index) => {
    const units = thread.units || [];
    const first = units[0] || {};
    const inst = first.institution || "unknown";
    const sender = first.sender_name || "unknown sender";
    const service = first.service_of_interest || "—";
    const date = (first.submitted_at || "").slice(0, 10);
    const score = Number(thread.best_score || 0).toFixed(2);
    const replies = units
      .map((u) => (u.page_content || "").trim())
      .filter(Boolean)
      .join("\n\n")
      .slice(0, 600);
    const allAttachments = units.flatMap((u) => u.attachments || []);
    const attachmentsHTML = allAttachments.length ? `
        <div class="thread-attachments">
          <span class="thread-attachments-label">📎 Attachments (${allAttachments.length}):</span>
          ${allAttachments.map((att) => {
            const name = att.name || att.id || "file";
            const ext = att.extension || "";
            const label = ext && !String(name).toLowerCase().endsWith("." + String(ext).toLowerCase())
              ? `${name}.${ext}` : name;
            return att.url
              ? `<a class="document-link" href="${escapeHtml(att.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(label)}</a>`
              : `<span class="document-link document-link-disabled">${escapeHtml(label)}</span>`;
          }).join(" · ")}
        </div>
      ` : "";
    return `
      <div class="thread-card">
        <p class="thread-title">[${index + 1}] ${escapeHtml(sender)} — ${escapeHtml(inst)}</p>
        <p class="thread-meta">${escapeHtml(date)} · service: ${escapeHtml(service)} · score ${score} · ${units.length} reply unit(s)</p>
        <pre class="thread-snippet">${escapeHtml(replies)}</pre>
        ${attachmentsHTML}
      </div>
    `;
  }).join("");

  historicalResults.innerHTML = `<div class="document-list">${items}</div>`;
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
  const topic = output.response_topic || "";
  const focus = output.answer_focus || "";
  if (!topic && !focus) {
    responseTopicSummary.innerHTML = '<p class="signal-state">当前没有可展示的 response topic。</p>';
    return;
  }

  responseTopicSummary.innerHTML = `
    <p class="signal-line"><strong>Topic:</strong> ${escapeHtml(topic)}</p>
    <p class="signal-line"><strong>Focus:</strong> ${escapeHtml(focus || "n/a")}</p>
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
    trustSummary.innerHTML = '<p class="signal-state">Retrieving similar threads + docs…</p>';
    routingNoteSummary.innerHTML = '<p class="signal-state">Routing in progress…</p>';
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

    executionPlan.textContent = JSON.stringify(output.execution_plan || {}, null, 2);
    executionRun.textContent = JSON.stringify(output.execution_run || {}, null, 2);
    answerFocusEl.textContent = output.answer_focus || "";
    routeResult.textContent = JSON.stringify(output.route || {}, null, 2);
    parsedResult.textContent = JSON.stringify(output.parsed || {}, null, 2);
    agentInput.textContent = JSON.stringify(output.agent_input || {}, null, 2);
    renderTrust(output.execution_run || {});
    renderRoutingNote(output);
    renderHistoricalThreads(output.execution_run || {});
    renderResponseTopic(output);
    renderResponseContentBlocks(output);
    renderDocumentResults(output.execution_run || {});
    renderTechnicalResults(output.execution_run || {});
    renderWorkflow(output.suggested_workflow || []);
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

refreshSamplesButton.addEventListener("click", () => {
  renderQuestionSamples();
});
