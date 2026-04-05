const form = document.getElementById("agent-form");
const submitButton = document.getElementById("submit-btn");
const parsedResult = document.getElementById("parsed_result");
const agentInput = document.getElementById("agent_input");
const replyPreview = document.getElementById("reply_preview");
const workflow = document.getElementById("workflow");
const routeResult = document.getElementById("route_result");

function parseJsonField(value, fallback) {
  if (!value.trim()) {
    return fallback;
  }

  try {
    return JSON.parse(value);
  } catch (error) {
    throw new Error(`JSON 解析失败: ${error.message}`);
  }
}

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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  submitButton.disabled = true;
  submitButton.textContent = "运行中...";

  try {
    const payload = {
      user_query: document.getElementById("user_query").value,
      conversation_history: parseJsonField(
        document.getElementById("conversation_history").value,
        [],
      ),
      attachments: parseJsonField(
        document.getElementById("attachments").value,
        [],
      ),
    };

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

    replyPreview.textContent = output.reply_preview || "";
    routeResult.textContent = JSON.stringify(output.route || {}, null, 2);
    parsedResult.textContent = JSON.stringify(output.parsed || {}, null, 2);
    agentInput.textContent = JSON.stringify(output.agent_input || {}, null, 2);
    renderWorkflow(output.suggested_workflow || []);
  } catch (error) {
    replyPreview.textContent = error.message;
    routeResult.textContent = "{}";
    parsedResult.textContent = "{}";
    agentInput.textContent = "{}";
    renderWorkflow([]);
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = "运行原型";
  }
});
