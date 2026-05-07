const state = {
  result: null,
  reports: [],
};

const elements = {
  statusText: document.getElementById("statusText"),
  questionInput: document.getElementById("questionInput"),
  scenarioSelect: document.getElementById("scenarioSelect"),
  maxStepsInput: document.getElementById("maxStepsInput"),
  taskIdInput: document.getElementById("taskIdInput"),
  mockInput: document.getElementById("mockInput"),
  runButton: document.getElementById("runButton"),
  exampleBar: document.getElementById("exampleBar"),
  answerOutput: document.getElementById("answerOutput"),
  verificationOutput: document.getElementById("verificationOutput"),
  verifierBadge: document.getElementById("verifierBadge"),
  evidenceList: document.getElementById("evidenceList"),
  evidenceFilter: document.getElementById("evidenceFilter"),
  trajectoryList: document.getElementById("trajectoryList"),
  stepCount: document.getElementById("stepCount"),
  reportSelect: document.getElementById("reportSelect"),
  reportOutput: document.getElementById("reportOutput"),
  refreshReportsButton: document.getElementById("refreshReportsButton"),
};

async function init() {
  bindEvents();
  await loadExamples();
  await loadReports();
}

function bindEvents() {
  elements.runButton.addEventListener("click", runAsk);
  elements.evidenceFilter.addEventListener("change", renderEvidence);
  elements.reportSelect.addEventListener("change", renderSelectedReport);
  elements.refreshReportsButton.addEventListener("click", loadReports);
}

async function loadExamples() {
  const data = await getJson("/api/examples");
  elements.exampleBar.innerHTML = "";
  data.examples.forEach((example) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = example.label;
    button.className = "secondary";
    button.addEventListener("click", () => applyExample(example));
    elements.exampleBar.appendChild(button);
  });
}

function applyExample(example) {
  elements.questionInput.value = example.question;
  elements.scenarioSelect.value = example.mock_scenario;
  elements.maxStepsInput.value = example.max_steps;
  elements.taskIdInput.value = example.task_id;
}

async function loadReports() {
  const data = await getJson("/api/reports");
  state.reports = data.reports || [];
  elements.reportSelect.innerHTML = "";
  state.reports.forEach((report, index) => {
    const option = document.createElement("option");
    option.value = String(index);
    option.textContent = report.type;
    elements.reportSelect.appendChild(option);
  });
  renderSelectedReport();
}

async function runAsk() {
  setBusy(true);
  setStatus("Running");
  const payload = {
    question: elements.questionInput.value,
    mock: elements.mockInput.checked,
    mock_scenario: elements.scenarioSelect.value,
    max_steps: Number(elements.maxStepsInput.value || 6),
    task_id: elements.taskIdInput.value,
  };
  try {
    const result = await postJson("/api/ask", payload);
    state.result = result;
    renderResult();
    setStatus(`Done: ${result.task_id}`);
  } catch (error) {
    elements.answerOutput.textContent = String(error.message || error);
    elements.verificationOutput.textContent = "";
    setBadge("failed", false);
    setStatus("Failed");
  } finally {
    setBusy(false);
  }
}

function renderResult() {
  const result = state.result || {};
  elements.answerOutput.textContent = result.answer || "";
  elements.verificationOutput.textContent = JSON.stringify(result.verification || {}, null, 2);
  const passed = Boolean(result.verification && result.verification.passed);
  setBadge(passed ? "passed" : "failed", passed);
  renderEvidence();
  renderTrajectory();
}

function renderEvidence() {
  const result = state.result || {};
  const filter = elements.evidenceFilter.value;
  const evidence = (result.evidence || []).filter((item) => filter === "all" || item.source_type === filter);
  elements.evidenceList.innerHTML = "";
  evidence.forEach((item) => {
    const node = document.createElement("article");
    node.className = `item source-${item.source_type}`;
    node.innerHTML = `
      <div class="item-head">
        <div class="item-title">${escapeHtml(item.evidence_id)} · ${escapeHtml(item.source_type)}</div>
        <span class="badge ${item.used_in_final ? "pass" : "neutral"}">${item.used_in_final ? "used" : "stored"}</span>
      </div>
      <div class="item-meta">${escapeHtml(formatSource(item))}</div>
      <pre>${escapeHtml(shorten(item.content || "", 700))}</pre>
    `;
    elements.evidenceList.appendChild(node);
  });
}

function renderTrajectory() {
  const result = state.result || {};
  const trajectory = result.trajectory || [];
  elements.stepCount.textContent = `${trajectory.length} steps`;
  elements.trajectoryList.innerHTML = "";
  trajectory.forEach((step) => {
    const node = document.createElement("article");
    node.className = "item";
    node.innerHTML = `
      <div class="item-head">
        <div class="item-title">Step ${escapeHtml(step.step)} · ${escapeHtml(step.action)}</div>
        <span class="badge ${step.success ? "pass" : "fail"}">${step.success ? "ok" : "fail"}</span>
      </div>
      <div class="item-meta">${escapeHtml(step.phase || "")} · ${escapeHtml(String(step.latency_ms || 0))} ms · ${escapeHtml((step.evidence_ids || []).join(", "))}</div>
      <pre>${escapeHtml(shorten(step.observation_summary || "", 900))}</pre>
    `;
    elements.trajectoryList.appendChild(node);
  });
}

function renderSelectedReport() {
  const index = Number(elements.reportSelect.value || 0);
  const report = state.reports[index];
  if (!report) {
    elements.reportOutput.textContent = "";
    return;
  }
  elements.reportOutput.textContent = report.exists ? report.content : `${report.path} missing`;
}

function formatSource(item) {
  const parts = [item.source || ""];
  if (item.line_range) parts.push(item.line_range);
  if (item.metadata && item.metadata.page) parts.push(`page ${item.metadata.page}`);
  if (item.metadata && item.metadata.block_type) parts.push(item.metadata.block_type);
  return parts.filter(Boolean).join(" · ");
}

function setBadge(text, passed) {
  elements.verifierBadge.textContent = text;
  elements.verifierBadge.className = `badge ${passed ? "pass" : "fail"}`;
}

function setBusy(isBusy) {
  elements.runButton.disabled = isBusy;
}

function setStatus(text) {
  elements.statusText.textContent = text;
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || response.statusText);
  return data;
}

function shorten(text, maxLength) {
  const value = String(text);
  return value.length <= maxLength ? value : `${value.slice(0, maxLength).trim()}...`;
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

init();
