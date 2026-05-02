const form = document.getElementById("agent-form");
const submitButton = document.getElementById("submit-btn");
const newChatButton = document.getElementById("new-chat-btn");
const parsedResult = document.getElementById("parsed_result");
const agentInput = document.getElementById("agent_input");
const workflow = document.getElementById("workflow");
const workflowMeta = document.getElementById("workflow_meta");
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
const appShell = document.getElementById("app_shell");
const chatStage = document.getElementById("chat_stage");
const sidebarToggleButton = document.getElementById("sidebar-toggle-btn");
const composerToolsTrigger = document.getElementById("composer-tools-trigger");
const composerToolsDropdown = document.getElementById("composer-tools-dropdown");
const inspectorTabs = Array.from(document.querySelectorAll("[data-panel-target]"));
const inspectorPanels = Array.from(document.querySelectorAll(".inspector-panel"));

const CHAT_SESSIONS_STORAGE_KEY = "email_agent.chat_sessions";
const THREAD_STORAGE_KEY = "email_agent.thread_id";
const SIDEBAR_STATE_STORAGE_KEY = "email_agent.sidebar_open";

let messages = [];
let threadId = "";
let sessions = {};
let editingThreadId = "";
let editingThreadTitleDraft = "";
let sidebarOpen = true;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buildDownloadLabel(label, fileName) {
  const preferred = String(label || fileName || "").trim();
  if (!preferred) {
    return "Download files";
  }
  return `Download ${preferred}`;
}

function closeAllHistoryMenus() {
  document.querySelectorAll(".history-menu").forEach((menu) => {
    menu.classList.remove("history-menu-open");
  });
}

function setComposerToolsOpen(nextOpen) {
  composerToolsTrigger.setAttribute("aria-expanded", String(nextOpen));
  composerToolsDropdown.classList.toggle("composer-tools-dropdown-open", nextOpen);
}

function startInlineThreadRename(targetThreadId) {
  const session = sessions[targetThreadId];
  if (!targetThreadId || !session) {
    return;
  }
  editingThreadId = targetThreadId;
  editingThreadTitleDraft = String(session.title || buildSessionTitle(session.messages || []) || "New conversation");
  closeAllHistoryMenus();
  renderHistoryNav();

  window.requestAnimationFrame(() => {
    const input = historyNav.querySelector(`[data-inline-rename-input="${CSS.escape(targetThreadId)}"]`);
    if (!input) {
      return;
    }
    input.focus();
    input.select();
  });
}

function cancelInlineThreadRename() {
  editingThreadId = "";
  editingThreadTitleDraft = "";
  renderHistoryNav();
}

async function commitInlineThreadRename(targetThreadId, nextTitle) {
  const normalizedTitle = String(nextTitle || "").trim();
  if (!targetThreadId || !normalizedTitle) {
    cancelInlineThreadRename();
    return;
  }

  // A7: same logic as delete — if backend rename fails, do NOT mutate
  // localStorage, otherwise a refresh refetches the old title and the
  // user sees their rename "revert" without any error feedback.
  try {
    await renameThreadInBackend(targetThreadId, normalizedTitle);
  } catch (error) {
    sessionHint.textContent = `Rename failed (${error.message || "backend error"}); title unchanged.`;
    cancelInlineThreadRename();
    return;
  }

  ensureSessionRecord(targetThreadId);
  sessions[targetThreadId] = {
    ...(sessions[targetThreadId] || {}),
    title: normalizedTitle,
    updated_at: new Date().toISOString(),
  };
  saveStoredSessions();
  editingThreadId = "";
  editingThreadTitleDraft = "";
  renderHistoryNav();
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

function parseSseBlock(rawBlock) {
  // Each SSE event is a block of `event: <name>\ndata: <json>\n`. Multi-line
  // data lines get concatenated; the runtime here only emits single-line
  // data, but handle the spec-correct case anyway.
  const lines = rawBlock.split("\n");
  let name = "message";
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith("event:")) {
      name = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).replace(/^ /, ""));
    }
  }
  if (!dataLines.length) {
    return null;
  }
  const raw = dataLines.join("\n");
  try {
    return { name, data: JSON.parse(raw) };
  } catch (_err) {
    return { name, data: raw };
  }
}

async function streamEmailAgent(payload, onEvent) {
  const response = await fetch("/email-agent/sse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ input: payload }),
  });
  if (!response.ok || !response.body) {
    const text = response.body ? await response.text() : "";
    throw new Error(text || `stream request failed (${response.status})`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseSseBlock(block);
      if (parsed) {
        onEvent(parsed);
      }
    }
  }
  buffer += decoder.decode();
  if (buffer.trim()) {
    const parsed = parseSseBlock(buffer);
    if (parsed) {
      onEvent(parsed);
    }
  }
}

function formatStreamingTrustSection(signal) {
  const status = signal?.grounding_status || "unknown";
  const tier = signal?.retrieval_quality_tier || "unknown";
  const summary = signal?.summary || "";
  return [
    "*🧭 Grounding signal*",
    `   • status: \`${status}\``,
    `   • retrieval quality: \`${tier}\``,
    `   • ${summary}`,
  ].join("\n");
}

function renderStreamingTrust(signal) {
  if (!signal) {
    return;
  }
  const status = signal.grounding_status || "unknown";
  const tier = signal.retrieval_quality_tier || "unknown";
  const docCount = Number(signal.documents_used || 0);
  const histCount = Number(signal.historical_threads_used || 0);
  trustSummary.innerHTML = `
    <p class="signal-line"><span class="trust-tier trust-tier-${escapeHtml(tier)}">${escapeHtml(tier)}</span></p>
    <p class="signal-line"><strong>Status:</strong> ${escapeHtml(status)}</p>
    <p class="signal-line"><strong>Sources:</strong> ${histCount} similar past · ${docCount} docs</p>
  `;
}

function renderStreamingContentBlocks(blocks) {
  if (!blocks.length) {
    responseContentBlocks.innerHTML = '<p class="signal-state">Streaming references…</p>';
    return;
  }
  renderResponseContentBlocks({ response_content_blocks: blocks });
}

function composeStreamingMessage(state) {
  const parts = [];
  const draftBody = state.draftDone
    ? (state.draftText || "_(empty draft — see references below)_")
    : (state.draftText || "");
  if (draftBody) {
    parts.push(`*📝 Draft reply* _(CSR: please review & edit before sending)_\n\n${draftBody}`);
  }
  if (state.trustSection) {
    parts.push(state.trustSection);
  }
  parts.push(...state.panelSectionTexts);
  return parts.join("\n\n");
}

function createThreadId() {
  if (window.crypto?.randomUUID) {
    return `thread-${window.crypto.randomUUID()}`;
  }

  return `thread-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function activateInspectorPanel(panelId) {
  inspectorTabs.forEach((button) => {
    const isActive = button.dataset.panelTarget === panelId;
    button.classList.toggle("inspector-tab-active", isActive);
  });
  inspectorPanels.forEach((panel) => {
    panel.classList.toggle("inspector-panel-active", panel.id === panelId);
  });
}

function syncSidebarUI() {
  appShell.classList.toggle("sidebar-open", sidebarOpen);
  appShell.classList.toggle("sidebar-closed", !sidebarOpen);
  sidebarToggleButton.setAttribute("aria-expanded", String(sidebarOpen));
  sidebarToggleButton.setAttribute("aria-label", sidebarOpen ? "Collapse sidebar" : "Expand sidebar");
  sidebarToggleButton.setAttribute("title", sidebarOpen ? "Collapse sidebar" : "Expand sidebar");
}

function initializeSidebarState() {
  const stored = window.localStorage.getItem(SIDEBAR_STATE_STORAGE_KEY);
  sidebarOpen = stored == null ? true : stored === "true";
  syncSidebarUI();
}

function toggleSidebar() {
  sidebarOpen = !sidebarOpen;
  window.localStorage.setItem(SIDEBAR_STATE_STORAGE_KEY, String(sidebarOpen));
  syncSidebarUI();
}

function ensureThreadId() {
  if (!threadId) {
    threadId = window.localStorage.getItem(THREAD_STORAGE_KEY) || createThreadId();
    window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
  }
  return threadId;
}

function loadStoredSessions() {
  try {
    sessions = JSON.parse(window.localStorage.getItem(CHAT_SESSIONS_STORAGE_KEY) || "{}");
  } catch (_error) {
    sessions = {};
  }
  if (!sessions || typeof sessions !== "object" || Array.isArray(sessions)) {
    sessions = {};
  }
  let removedEmptySessions = false;
  for (const [key, session] of Object.entries(sessions)) {
    if (!sessionHasMessages(session)) {
      delete sessions[key];
      removedEmptySessions = true;
    }
  }
  if (removedEmptySessions) {
    saveStoredSessions();
  }
}

async function loadSessionsFromBackend() {
  try {
    const response = await fetch("/api/conversations");
    if (!response.ok) {
      throw new Error(`Failed to load conversations: ${response.status}`);
    }
    const payload = await response.json();
    const nextSessions = {};
    for (const thread of payload.threads || []) {
      const key = String(thread.thread_key || "");
      if (!key) {
        continue;
      }
      nextSessions[key] = {
        thread_id: key,
        title: thread.title || "New conversation",
        updated_at: thread.updated_at || "",
        messages: [],
        message_count: Number(thread.message_count || 0),
        preview: String(thread.preview || ""),
      };
    }
    sessions = nextSessions;
    saveStoredSessions();
  } catch (_error) {
    loadStoredSessions();
  }
}

async function loadThreadMessagesFromBackend(id) {
  const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`);
  if (!response.ok) {
    throw new Error(`Failed to load thread: ${response.status}`);
  }
  const payload = await response.json();
  const loadedMessages = (payload.messages || []).map((message) => ({
    role: message.role || "user",
    content: message.content || "",
    metadata: message.metadata || {},
  }));
  ensureSessionRecord(id);
  sessions[id] = {
    ...(sessions[id] || {}),
    thread_id: id,
    messages: loadedMessages,
    updated_at: sessions[id]?.updated_at || new Date().toISOString(),
    title: sessions[id]?.title || buildSessionTitle(loadedMessages),
    message_count: loadedMessages.length,
    preview: String(loadedMessages.find((m) => m.role === "assistant")?.content || loadedMessages[0]?.content || ""),
  };
  saveStoredSessions();
  return loadedMessages;
}

async function deleteThreadFromBackend(id) {
  const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw new Error(`Failed to delete thread: ${response.status}`);
  }
  return response.json();
}

async function deleteAllThreadsFromBackend(threadIds) {
  for (const id of threadIds) {
    await deleteThreadFromBackend(id);
  }
}

async function renameThreadInBackend(id, title) {
  const response = await fetch(`/api/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ title }),
  });
  if (!response.ok) {
    throw new Error(`Failed to rename thread: ${response.status}`);
  }
  return response.json();
}

function saveStoredSessions() {
  window.localStorage.setItem(CHAT_SESSIONS_STORAGE_KEY, JSON.stringify(sessions));
}

function sessionHasMessages(session) {
  if (!session || typeof session !== "object") {
    return false;
  }
  const storedMessages = Array.isArray(session.messages) ? session.messages.length : 0;
  const countedMessages = Number(session.message_count || 0);
  return storedMessages > 0 || countedMessages > 0;
}

function buildSessionTitle(sessionMessages) {
  const firstUserMessage = (sessionMessages || []).find((message) => message.role === "user");
  const preview = (firstUserMessage?.content || "").trim();
  if (!preview) {
    return "New conversation";
  }
  return preview.length > 56 ? `${preview.slice(0, 56)}...` : preview;
}

function formatSessionTimestamp(value) {
  const raw = String(value || "").trim();
  if (!raw) {
    return "No activity yet";
  }

  const parsed = new Date(raw);
  if (Number.isNaN(parsed.getTime())) {
    return raw.replace("T", " ").slice(5, 16) || "No activity yet";
  }

  return parsed.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).replace(",", "");
}

function ensureSessionRecord(id) {
  if (!id) {
    return;
  }
  if (!sessions[id]) {
    sessions[id] = {
      thread_id: id,
      messages: [],
      updated_at: new Date().toISOString(),
      title: "New conversation",
    };
    saveStoredSessions();
  }
}

function syncCurrentSession() {
  const activeThreadId = ensureThreadId();
  if (!messages.length) {
    if (sessions[activeThreadId]) {
      delete sessions[activeThreadId];
      saveStoredSessions();
    }
    return;
  }
  sessions[activeThreadId] = {
    thread_id: activeThreadId,
    messages: [...messages],
    updated_at: new Date().toISOString(),
    title: buildSessionTitle(messages),
    message_count: messages.length,
    preview: String(messages.find((message) => message.role === "assistant")?.content || messages[0]?.content || ""),
  };
  saveStoredSessions();
}

function loadThreadSession(id) {
  threadId = id;
  window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
  messages = [...(sessions[id]?.messages || [])];
}

function createAndSwitchToNewThread() {
  syncCurrentSession();
  threadId = createThreadId();
  window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
  messages = [];
}

function renderSessionHint() {
  const activeThreadId = ensureThreadId();
  sessionHint.textContent = `Session linked to ${activeThreadId.slice(0, 18)}...`;
}

function syncChatStageLayout() {
  const isEmpty = !messages.length;
  chatStage.classList.toggle("chat-stage-empty-mode", isEmpty);
}

function playChatStageTransition() {
  chatStage.classList.remove("chat-stage-switching");
  void chatStage.offsetWidth;
  chatStage.classList.add("chat-stage-switching");
}

function renderChatHistory(options = {}) {
  const { forceScroll = false } = options;
  const autoScrollThreshold = 48;
  const shouldStickToBottom =
    forceScroll
    || (chatHistory.scrollHeight - chatHistory.scrollTop - chatHistory.clientHeight <= autoScrollThreshold);

  syncChatStageLayout();

  if (!messages.length) {
    chatHistory.innerHTML = `
      <div class="chat-empty-state">
        <p class="chat-empty-title">Where should we start?</p>
        <p class="chat-empty">Ask about a product, request a quote, or retrieve technical documentation.</p>
      </div>
    `;
    return;
  }

  chatHistory.innerHTML = messages.map((message) => {
    const isAssistant = message.role === "assistant";
    const isStreaming = Boolean(message.metadata?.streaming);
    const roleClass = isAssistant ? "chat-message-assistant" : "chat-message-user";
    const roleLabel = isAssistant ? "Assistant" : "CSR";
    const plainContent = String(message.content || "");
    const streamingLabel = String(message.metadata?.streaming_label || "");
    const normalizedUserLength = plainContent.replace(/\s+/g, " ").trim().length;
    let userBubbleSizeClass = "";
    if (!isAssistant) {
      if (normalizedUserLength <= 24) {
        userBubbleSizeClass = "chat-message-user-compact";
      } else if (normalizedUserLength <= 72) {
        userBubbleSizeClass = "chat-message-user-medium";
      } else {
        userBubbleSizeClass = "chat-message-user-wide";
      }
    }
    const streamingIndicator = isStreaming
      ? `
        <div class="chat-streaming-indicator">
          <div class="honeycomb">
            <div></div>
            <div></div>
            <div></div>
            <div></div>
            <div></div>
            <div></div>
            <div></div>
          </div>
          ${streamingLabel ? `
            <span class="chat-streaming-label">
              ${escapeHtml(streamingLabel)}<span class="chat-streaming-dots" aria-hidden="true">...</span>
            </span>
          ` : ""}
        </div>
      `
      : "";
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
      <a class="download-file-btn" href="${escapeHtml(doc.document_url || "")}" target="_blank" rel="noopener noreferrer" download>
        ${escapeHtml(buildDownloadLabel(doc.label, doc.file_name))}
      </a>
    `).join("");
    const documentSection = documentLinks
      ? `<div class="document-actions chat-document-actions">${documentLinks}</div>`
      : "";

    const body = isAssistant
      ? `
        <div class="${isStreaming ? "chat-streaming-shell" : ""}">
          ${streamingIndicator}
          <div class="message-formatted">${formatSlackMessage(message.content || "")}</div>
        </div>
      `
      : escapeHtml(message.content || "");

    return `
      <div class="chat-message-row ${roleClass}">
        ${isAssistant ? "" : `
          <div class="chat-message ${roleClass} ${userBubbleSizeClass}">
            <div class="chat-message-header">
              <strong>${roleLabel}</strong>
            </div>
            ${body}
            ${documentSection}
            ${metaLine}
          </div>
          <div class="chat-avatar">${escapeHtml(roleLabel)}</div>
        `}
        ${isAssistant ? `
        <div class="chat-message ${roleClass}">
          <div class="chat-message-header">
            <strong>${roleLabel}</strong>
          </div>
          ${body}
          ${documentSection}
          ${metaLine}
        </div>
        ` : ""}
      </div>
    `;
  }).join("");

  if (shouldStickToBottom) {
    chatHistory.scrollTop = chatHistory.scrollHeight;
  }
}

function renderHistoryNav() {
  const entries = Object.values(sessions)
    .filter((entry) => sessionHasMessages(entry))
    .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));

  if (!entries.length) {
    historyNav.innerHTML = '<p class="history-empty">No conversation yet.</p>';
    return;
  }

  historyNav.innerHTML = entries.map((entry) => {
    const sessionMessages = entry.messages || [];
    const title = entry.title || buildSessionTitle(sessionMessages);
    const updated = formatSessionTimestamp(entry.updated_at);
    const isActive = entry.thread_id === ensureThreadId();
    const messageCount = Number(entry.message_count || sessionMessages.length || 0);
    const isEditing = entry.thread_id === editingThreadId;
    const titleMarkup = isEditing
      ? `
        <input
          type="text"
          class="history-inline-edit-input"
          value="${escapeHtml(editingThreadTitleDraft || title)}"
          data-inline-rename-input="${escapeHtml(entry.thread_id || "")}"
          aria-label="Rename thread"
        />
      `
      : `<p class="history-item-title">${escapeHtml(title)}</p>`;
    return `
      <div class="history-row ${isActive ? "history-row-active" : ""}">
        <button type="button" class="history-item ${isActive ? "history-item-active" : ""}" data-thread-id="${escapeHtml(entry.thread_id || "")}">
          <div class="history-item-marker-wrap">
            <span class="history-item-marker">${isActive ? "●" : "#"}<\/span>
            <div class="history-item-copy">
              <div class="history-item-topline">
                <div class="history-item-title-wrap">
                  ${titleMarkup}
                </div>
                <span class="history-item-time">${escapeHtml(updated)}</span>
              </div>
              <p class="history-item-meta">${messageCount} msg</p>
            </div>
          </div>
        </button>
        <div class="history-actions">
          <button
            type="button"
            class="history-menu-btn"
            data-menu-thread-id="${escapeHtml(entry.thread_id || "")}"
            aria-label="Thread actions"
            title="Thread actions"
          >
            &#8942;
          </button>
          <div class="history-menu" data-menu-for-thread-id="${escapeHtml(entry.thread_id || "")}">
            <button type="button" class="history-menu-item" data-rename-thread-id="${escapeHtml(entry.thread_id || "")}">
              Rename
            </button>
            <button type="button" class="history-menu-item history-menu-item-danger" data-delete-thread-id="${escapeHtml(entry.thread_id || "")}">
              Delete
            </button>
          </div>
        </div>
      </div>
    `;
  }).join("");

  historyNav.querySelectorAll("[data-thread-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const nextThreadId = button.dataset.threadId || "";
      if (!nextThreadId || nextThreadId === threadId || editingThreadId) {
        return;
      }
      try {
        syncCurrentSession();
        messages = await loadThreadMessagesFromBackend(nextThreadId);
        loadThreadSession(nextThreadId);
        renderChatHistory({ forceScroll: true });
        playChatStageTransition();
        renderHistoryNav();
        renderSessionHint();
        resetInspectorPanels("Loaded prior conversation. Submit a new message to continue this thread.");
      } catch (_error) {
        loadThreadSession(nextThreadId);
        renderChatHistory({ forceScroll: true });
        playChatStageTransition();
        renderHistoryNav();
        renderSessionHint();
        resetInspectorPanels("Loaded prior conversation from local cache.");
      }
    });
  });

  historyNav.querySelectorAll("[data-menu-thread-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const targetId = button.dataset.menuThreadId || "";
      historyNav.querySelectorAll(".history-menu").forEach((menu) => {
        const shouldOpen = menu.dataset.menuForThreadId === targetId;
        menu.classList.toggle("history-menu-open", shouldOpen && !menu.classList.contains("history-menu-open"));
        if (!shouldOpen) {
          menu.classList.remove("history-menu-open");
        }
      });
    });
  });

  historyNav.querySelectorAll("[data-rename-thread-id]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const renameThreadId = button.dataset.renameThreadId || "";
      if (!renameThreadId) {
        return;
      }
      startInlineThreadRename(renameThreadId);
    });
  });

  historyNav.querySelectorAll("[data-inline-rename-input]").forEach((input) => {
    const inputEl = input;
    const targetThreadId = inputEl.dataset.inlineRenameInput || "";
    let hasCommitted = false;

    inputEl.addEventListener("click", (event) => {
      event.stopPropagation();
    });

    inputEl.addEventListener("input", () => {
      editingThreadTitleDraft = inputEl.value;
    });

    inputEl.addEventListener("keydown", async (event) => {
      event.stopPropagation();
      if (event.key === "Enter") {
        event.preventDefault();
        hasCommitted = true;
        await commitInlineThreadRename(targetThreadId, inputEl.value);
      } else if (event.key === "Escape") {
        event.preventDefault();
        hasCommitted = true;
        cancelInlineThreadRename();
      }
    });

    inputEl.addEventListener("blur", async () => {
      if (hasCommitted) {
        return;
      }
      await commitInlineThreadRename(targetThreadId, inputEl.value);
    });
  });

  historyNav.querySelectorAll("[data-delete-thread-id]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const deleteThreadId = button.dataset.deleteThreadId || "";
      if (!deleteThreadId) {
        return;
      }
      const confirmed = window.confirm("Delete this thread?");
      if (!confirmed) {
        return;
      }
      // A7: do not delete localStorage if backend write fails — otherwise a
      // refresh re-fetches the row from PG and the thread "comes back",
      // confusing the CSR. Surface the error and bail.
      try {
        await deleteThreadFromBackend(deleteThreadId);
      } catch (error) {
        sessionHint.textContent = `Delete failed (${error.message || "backend error"}); thread kept.`;
        return;
      }
      delete sessions[deleteThreadId];
      saveStoredSessions();

      if (deleteThreadId === threadId) {
        // A4: pick the most recently updated remaining thread, not Object.keys[0]
        // which is insertion-order and unrelated to recency.
        const remainingThreadId =
          Object.values(sessions)
            .filter((s) => s && s.thread_id && s.thread_id !== deleteThreadId)
            .sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")))
            .map((s) => s.thread_id)[0]
          || createThreadId();
        threadId = remainingThreadId;
        window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
        if (sessions[threadId]) {
          try {
            messages = await loadThreadMessagesFromBackend(threadId);
          } catch (_error) {
            loadThreadSession(threadId);
          }
        } else {
          messages = [];
        }
        renderChatHistory({ forceScroll: true });
        renderSessionHint();
        resetInspectorPanels("Thread deleted.");
      }

      renderHistoryNav();
    });
  });
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
  workflowMeta.innerHTML = `<p class="signal-state">${escapeHtml(errorMessage)}</p>`;
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
      label: match.file_name || "Document",
      source: "document_lookup",
    }));
  const servicePrimaryDocuments = (output.response_content_blocks || [])
    .filter((block) => block.kind === "service_primary_document")
    .map((block) => ({
      file_name: block.data?.file_name || "",
      document_url: block.data?.presigned_url || "",
      label: block.data?.title || block.data?.file_name || "Download files",
      source: "service_primary_document",
    }))
    .filter((doc) => doc.document_url);
  const mergedDocuments = [...servicePrimaryDocuments, ...documents].filter(
    (doc, index, all) => all.findIndex((item) => item.document_url === doc.document_url) === index,
  );
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
      documents: mergedDocuments,
    },
  };
}

async function initializeWorkspace() {
  await loadSessionsFromBackend();
  initializeSidebarState();
  threadId = createThreadId();
  window.localStorage.setItem(THREAD_STORAGE_KEY, threadId);
  messages = [];
  renderSessionHint();
  renderChatHistory({ forceScroll: true });
  playChatStageTransition();
  renderHistoryNav();
  activateInspectorPanel("docs_panel");

  inspectorTabs.forEach((button) => {
    button.addEventListener("click", () => {
      activateInspectorPanel(button.dataset.panelTarget || "docs_panel");
    });
  });

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".history-actions")) {
      closeAllHistoryMenus();
    }
    if (!event.target.closest(".composer-tools-menu")) {
      setComposerToolsOpen(false);
    }
  });
}

initializeWorkspace();

sidebarToggleButton.addEventListener("click", () => {
  toggleSidebar();
});

composerToolsTrigger.addEventListener("click", (event) => {
  event.stopPropagation();
  const nextOpen = composerToolsTrigger.getAttribute("aria-expanded") !== "true";
  setComposerToolsOpen(nextOpen);
});

composerToolsDropdown.querySelectorAll(".composer-tool-item").forEach((button) => {
  button.addEventListener("click", () => {
    setComposerToolsOpen(false);
    sessionHint.textContent = `${button.textContent.trim()} is coming soon.`;
  });
});

function renderWorkflow(items, executionPlanPayload = {}) {
  workflow.innerHTML = "";
  const rounds = Number(executionPlanPayload?.iterations || 0);
  const plannedActions = executionPlanPayload?.planned_actions || [];

  if (rounds > 1) {
    workflowMeta.innerHTML = `
      <p class="signal-line"><strong>Execution rounds:</strong> ${rounds}</p>
      <p class="signal-line">The agent used multiple observe-decide-act passes to add tools or recover from an incomplete result.</p>
    `;
  } else if (rounds === 1) {
    workflowMeta.innerHTML = `
      <p class="signal-line"><strong>Execution rounds:</strong> 1</p>
      <p class="signal-line">The agent completed the workflow in a single pass.</p>
    `;
  } else if (plannedActions.length) {
    workflowMeta.innerHTML = `
      <p class="signal-line"><strong>Execution rounds:</strong> n/a</p>
      <p class="signal-line">Workflow steps are available, but the round count was not returned.</p>
    `;
  } else {
    workflowMeta.innerHTML = '<p class="signal-state">Submit a query to see execution rounds.</p>';
  }

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
      ${blocks.map((block, index) => {
        if (block.kind === "service_primary_document") {
          const title = block.data?.title || block.data?.file_name || "Primary service document";
          const fileName = block.data?.file_name || "";
          const url = block.data?.presigned_url || "";
          return `
            <div class="content-block-item content-block-item-download">
              <p class="content-block-title">${index + 1}. ${escapeHtml(block.kind || "unknown")}</p>
              <p class="content-block-text">${escapeHtml(title)}</p>
              ${fileName ? `<p class="content-block-text">${escapeHtml(fileName)}</p>` : ""}
              ${url ? `
                <a class="download-file-btn" href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer" download>
                  ${escapeHtml(buildDownloadLabel(title, fileName))}
                </a>
              ` : ""}
            </div>
          `;
        }

        return `
          <div class="content-block-item">
            <p class="content-block-title">${index + 1}. ${escapeHtml(block.kind || "unknown")}</p>
            <p class="content-block-text">${escapeHtml(block.text || "")}</p>
          </div>
        `;
      }).join("")}
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
  submitButton.classList.add("is-loading");
  submitButton.setAttribute("aria-busy", "true");

  try {
    const userMessage = buildUserMessage(userQuery);
    const payload = {
      thread_id: ensureThreadId(),
      user_query: userQuery,
      attachments: [],
    };

    messages = [...messages, userMessage];
    const placeholderAssistant = {
      role: "assistant",
      content: "",
      metadata: { response_type: "streaming", streaming: true, streaming_label: "thinking" },
    };
    messages = [...messages, placeholderAssistant];
    const placeholderIndex = messages.length - 1;
    syncCurrentSession();
    renderChatHistory({ forceScroll: true });
    renderHistoryNav();
    trustSummary.innerHTML = '<p class="signal-state">Retrieving similar threads + docs…</p>';
    routingNoteSummary.innerHTML = '<p class="signal-state">Routing in progress…</p>';
    responseContentBlocks.innerHTML = '<p class="signal-state">Waiting for evidence…</p>';
    userQueryField.value = "";

    const streamState = {
      trustSignal: null,
      trustSection: "",
      panelSectionTexts: [],
      panelBlocks: [],
      draftText: "",
      draftStarted: false,
      draftDone: false,
    };

    const refreshPlaceholder = () => {
      messages[placeholderIndex] = {
        ...messages[placeholderIndex],
        content: composeStreamingMessage(streamState),
        metadata: {
          ...(messages[placeholderIndex].metadata || {}),
          streaming: true,
          streaming_label: "thinking",
        },
      };
      renderChatHistory();
    };

    const handleStreamEvent = ({ name, data }) => {
      if (name === "trust") {
        streamState.trustSignal = data;
        streamState.trustSection = formatStreamingTrustSection(data);
        renderStreamingTrust(data);
        refreshPlaceholder();
      } else if (name === "section") {
        const block = data;
        streamState.panelBlocks = [...streamState.panelBlocks, block];
        if (block.body || block.text) {
          streamState.panelSectionTexts.push(block.body || block.text);
        }
        renderStreamingContentBlocks(streamState.panelBlocks);
        refreshPlaceholder();
      } else if (name === "draft_start") {
        streamState.draftStarted = true;
        refreshPlaceholder();
      } else if (name === "draft_chunk") {
        streamState.draftText += String(data?.text || "");
        refreshPlaceholder();
      } else if (name === "draft_end") {
        streamState.draftText = String(data?.draft || streamState.draftText || "");
        streamState.draftDone = true;
        refreshPlaceholder();
      } else if (name === "done") {
        const output = data || {};
        const assistantMessage = normalizeAssistantMessage(output);
        messages[placeholderIndex] = assistantMessage;
        syncCurrentSession();
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
        renderWorkflow(output.suggested_workflow || [], output.execution_plan || {});
      } else if (name === "error") {
        throw new Error(data?.message || "stream error");
      }
    };

    await streamEmailAgent(payload, handleStreamEvent);
  } catch (error) {
    // Drop both the user message and the streaming placeholder we appended.
    if (messages.length && messages[messages.length - 1].role === "assistant" && messages[messages.length - 1].metadata?.streaming) {
      messages = messages.slice(0, -1);
    }
    if (messages.length && messages[messages.length - 1].role === "user") {
      messages = messages.slice(0, -1);
    }
    syncCurrentSession();
    renderChatHistory();
    renderHistoryNav();
    resetInspectorPanels(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.classList.remove("is-loading");
    submitButton.setAttribute("aria-busy", "false");
  }
});

document.getElementById("user_query").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey) {
    return;
  }
  event.preventDefault();
  if (submitButton.disabled) {
    return;
  }
  form.requestSubmit();
});

newChatButton.addEventListener("click", () => {
  createAndSwitchToNewThread();
  renderChatHistory({ forceScroll: true });
  playChatStageTransition();
  renderHistoryNav();
  renderSessionHint();
  resetInspectorPanels();
  document.getElementById("user_query").focus();
});
