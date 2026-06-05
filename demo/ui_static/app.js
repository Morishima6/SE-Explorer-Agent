const state = {
  result: null,
  reports: [],
  project: {
    name: "",
    root: "",
    files: [],
    fileMap: new Map(),
    selectedFile: null,
    searchResults: [],
  },
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
  selectProjectButton: document.getElementById("selectProjectButton"),
  projectDirectoryInput: document.getElementById("projectDirectoryInput"),
  applyProjectPromptButton: document.getElementById("applyProjectPromptButton"),
  projectName: document.getElementById("projectName"),
  projectRoot: document.getElementById("projectRoot"),
  projectFileCount: document.getElementById("projectFileCount"),
  projectIndexedCount: document.getElementById("projectIndexedCount"),
  projectStatus: document.getElementById("projectStatus"),
  projectTreeCount: document.getElementById("projectTreeCount"),
  projectTree: document.getElementById("projectTree"),
  projectSearchInput: document.getElementById("projectSearchInput"),
  projectSearchButton: document.getElementById("projectSearchButton"),
  projectSearchResults: document.getElementById("projectSearchResults"),
  projectFilePath: document.getElementById("projectFilePath"),
  projectFilePreview: document.getElementById("projectFilePreview"),
};

const TEXT_EXTENSIONS = new Set([
  ".c",
  ".cpp",
  ".cs",
  ".css",
  ".go",
  ".h",
  ".html",
  ".java",
  ".js",
  ".json",
  ".jsx",
  ".md",
  ".properties",
  ".py",
  ".rs",
  ".ts",
  ".tsx",
  ".txt",
  ".xml",
  ".yaml",
  ".yml",
]);

const SKIP_DIRS = new Set([
  ".git",
  ".idea",
  ".vscode",
  "__pycache__",
  "build",
  "coverage",
  "dist",
  "node_modules",
  "target",
  "venv",
]);

const MAX_TEXT_FILE_BYTES = 512 * 1024;

async function init() {
  console.log("[ui] init");
  bindEvents();
  await loadExamples();
  await loadReports();
  renderEmptyState();
}

function bindEvents() {
  elements.runButton.addEventListener("click", runAsk);
  elements.evidenceFilter.addEventListener("change", renderEvidence);
  elements.reportSelect.addEventListener("change", renderSelectedReport);
  elements.refreshReportsButton.addEventListener("click", loadReports);
  elements.selectProjectButton.addEventListener("click", selectProjectDirectory);
  elements.projectDirectoryInput.addEventListener("change", readProjectFromInput);
  elements.projectSearchButton.addEventListener("click", searchProjectCode);
  elements.projectSearchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") searchProjectCode();
  });
  elements.applyProjectPromptButton.addEventListener("click", applyProjectPrompt);
}

async function loadExamples() {
  console.log("[ui] load examples");
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
  console.log("[ui] apply example", example.id);
  elements.questionInput.value = example.question;
  elements.scenarioSelect.value = example.mock_scenario;
  elements.maxStepsInput.value = example.max_steps;
  elements.taskIdInput.value = example.task_id;
}

async function selectProjectDirectory() {
  console.log("[ui] select project directory");
  try {
    const selected = await selectProjectRootFromBackend();
    if (selected.project_root) {
      await loadProjectFromBackendRoot(selected);
      return;
    }
  } catch (error) {
    console.log("[ui] backend project root selection unavailable", error);
    setProjectStatus("Backend dialog failed, using browser picker");
  }

  try {
    if ("showDirectoryPicker" in window) {
      await readProjectFromDirectoryPicker();
      return;
    }
    elements.projectDirectoryInput.click();
  } catch (error) {
    console.log("[ui] select project cancelled or failed", error);
    setProjectStatus("已取消选择目录");
  }
}

async function selectProjectRootFromBackend() {
  console.log("[ui] request backend project root dialog");
  setProjectStatus("Waiting for local directory dialog...");
  const selected = await postJson("/api/select-project-root", {});
  console.log("[ui] backend selected project root", selected);
  return selected;
}

async function loadProjectFromBackendRoot(selected) {
  const root = selected.project_root || "";
  const projectName = selected.project_name || inferProjectNameFromRoot(root);
  state.project.root = root;
  console.log("[ui] load project from backend root", {
    projectName,
    root,
    indexed: Array.isArray(selected.files) ? selected.files.length : 0,
  });
  if (Array.isArray(selected.files)) {
    await loadIndexedProjectFiles(projectName, selected.files, root, selected.files.length);
    return;
  }
  await readProjectFromDirectoryPicker();
}

async function readProjectFromDirectoryPicker() {
  setProjectStatus("正在读取目录...");
  const directoryHandle = await window.showDirectoryPicker();
  const files = [];
  await collectFilesFromDirectoryHandle(directoryHandle, "", files);
  await loadProjectFiles(directoryHandle.name, files, state.project.root || "");
}

async function collectFilesFromDirectoryHandle(directoryHandle, basePath, files) {
  for await (const [name, handle] of directoryHandle.entries()) {
    const relativePath = basePath ? `${basePath}/${name}` : name;
    if (handle.kind === "directory") {
      if (!shouldSkipPath(relativePath, true)) {
        await collectFilesFromDirectoryHandle(handle, relativePath, files);
      }
      continue;
    }
    if (handle.kind === "file" && shouldIndexFile(relativePath)) {
      const file = await handle.getFile();
      files.push({ path: relativePath, file });
    }
  }
}

async function readProjectFromInput() {
  console.log("[ui] read project from webkitdirectory input");
  const inputFiles = Array.from(elements.projectDirectoryInput.files || []);
  const files = inputFiles
    .map((file) => ({
      path: file.webkitRelativePath || file.name,
      file,
    }))
    .filter((entry) => shouldIndexFile(entry.path));
  const projectName = inferProjectNameFromInputFiles(inputFiles);
  await loadProjectFiles(projectName, files, state.project.root || "");
  elements.projectDirectoryInput.value = "";
}

async function loadProjectFiles(projectName, fileEntries, projectRoot = "") {
  console.log("[ui] load project files", { projectName, projectRoot, total: fileEntries.length });
  setProjectStatus("正在建立离线索引...");
  const indexedFiles = [];
  for (const entry of fileEntries) {
    const normalizedPath = stripProjectRootPrefix(normalizeProjectPath(entry.path), projectName);
    if (!normalizedPath || shouldSkipPath(normalizedPath, false)) continue;
    if (entry.file.size > MAX_TEXT_FILE_BYTES) continue;
    const text = await entry.file.text();
    indexedFiles.push({
      path: normalizedPath,
      name: normalizedPath.split("/").pop(),
      ext: getExtension(normalizedPath),
      size: entry.file.size,
      text,
    });
  }

  indexedFiles.sort((left, right) => left.path.localeCompare(right.path));
  state.project = {
    name: projectName || "selected-project",
    root: projectRoot || state.project.root || "",
    files: indexedFiles,
    fileMap: new Map(indexedFiles.map((file) => [file.path, file])),
    selectedFile: null,
    searchResults: [],
  };
  renderProjectSummary(fileEntries.length);
  renderProjectTree();
  renderProjectSearchEmpty();
  renderProjectFile(null);
  console.log("[ui] project indexed", {
    name: state.project.name,
    indexed: indexedFiles.length,
  });
}

async function loadIndexedProjectFiles(projectName, indexedFiles, projectRoot = "", totalFiles = 0) {
  console.log("[ui] load backend indexed project files", {
    projectName,
    projectRoot,
    indexed: indexedFiles.length,
  });
  state.project = {
    name: projectName || "selected-project",
    root: projectRoot || "",
    files: indexedFiles,
    fileMap: new Map(indexedFiles.map((file) => [file.path, file])),
    selectedFile: null,
    searchResults: [],
  };
  renderProjectSummary(totalFiles || indexedFiles.length);
  renderProjectTree();
  renderProjectSearchEmpty();
  renderProjectFile(null);
}

function renderProjectSummary(totalFiles) {
  elements.projectName.textContent = state.project.name || "未选择";
  elements.projectRoot.textContent = state.project.root || "browser picker only";
  elements.projectFileCount.textContent = String(totalFiles || state.project.files.length);
  elements.projectIndexedCount.textContent = String(state.project.files.length);
  elements.projectTreeCount.textContent = `${state.project.files.length} files`;
  elements.projectSearchButton.disabled = state.project.files.length === 0;
  elements.applyProjectPromptButton.disabled = state.project.files.length === 0;
  setProjectStatus(state.project.files.length ? "索引完成" : "没有可索引的文本文件");
}

function renderProjectTree() {
  elements.projectTree.innerHTML = "";
  if (!state.project.files.length) {
    elements.projectTree.classList.add("empty-state");
    elements.projectTree.textContent = "选择项目后显示目录结构。";
    return;
  }
  elements.projectTree.classList.remove("empty-state");
  const root = buildTree(state.project.files);
  elements.projectTree.appendChild(renderTreeNode(root, true));
}

function buildTree(files) {
  const root = { name: state.project.name, path: "", children: new Map(), file: null };
  files.forEach((file) => {
    const parts = file.path.split("/");
    let current = root;
    parts.forEach((part, index) => {
      const childPath = parts.slice(0, index + 1).join("/");
      if (!current.children.has(part)) {
        current.children.set(part, { name: part, path: childPath, children: new Map(), file: null });
      }
      current = current.children.get(part);
      if (index === parts.length - 1) current.file = file;
    });
  });
  return root;
}

function renderTreeNode(node, isRoot) {
  if (isRoot) {
    const wrapper = document.createElement("div");
    wrapper.className = "tree-root";
    Array.from(node.children.values()).sort(compareTreeNodes).forEach((child) => {
      wrapper.appendChild(renderTreeNode(child, false, 1));
    });
    return wrapper;
  }

  if (node.file) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "tree-file";
    button.title = node.path;
    button.innerHTML = `<span class="tree-icon">FILE</span><span>${escapeHtml(node.name)}</span>`;
    button.addEventListener("click", () => renderProjectFile(node.file));
    return button;
  }

  const details = document.createElement("details");
  details.className = "tree-dir";
  details.open = getTreeDepth(node.path) <= 2;
  const summary = document.createElement("summary");
  summary.title = node.path;
  summary.innerHTML = `<span class="tree-icon">DIR</span><span>${escapeHtml(node.name)}</span>`;
  details.appendChild(summary);
  const children = Array.from(node.children.values()).sort(compareTreeNodes);
  if (children.length) {
    const childList = document.createElement("div");
    childList.className = "tree-children";
    children.forEach((child) => childList.appendChild(renderTreeNode(child, false)));
    details.appendChild(childList);
  }
  return details;
}

function compareTreeNodes(left, right) {
  if (Boolean(left.file) !== Boolean(right.file)) return left.file ? 1 : -1;
  return left.name.localeCompare(right.name);
}

function searchProjectCode() {
  const query = elements.projectSearchInput.value.trim();
  console.log("[ui] search project code", { query });
  if (!query || !state.project.files.length) return;
  const matcher = createMatcher(query);
  const results = [];
  state.project.files.forEach((file) => {
    const lines = file.text.split(/\r?\n/);
    lines.forEach((line, index) => {
      if (matcher(line) || matcher(file.path)) {
        results.push({
          file,
          lineNumber: index + 1,
          line,
          context: extractLineContext(lines, index),
        });
      }
    });
  });
  state.project.searchResults = results.slice(0, 80);
  renderProjectSearchResults(query);
}

function renderProjectSearchResults(query) {
  elements.projectSearchResults.innerHTML = "";
  if (!state.project.searchResults.length) {
    elements.projectSearchResults.classList.add("empty-state");
    elements.projectSearchResults.textContent = `没有命中：${query}`;
    return;
  }
  elements.projectSearchResults.classList.remove("empty-state");
  state.project.searchResults.forEach((result) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-result";
    const fileName = result.file.name || result.file.path;
    button.innerHTML = `
      <span class="search-result-head">
        <strong>${escapeHtml(fileName)}:${escapeHtml(String(result.lineNumber))}</strong>
        <span>${escapeHtml(result.file.ext || "text")}</span>
      </span>
      <span class="search-result-path">${escapeHtml(result.file.path)}</span>
      <code>${highlightCodeInline(shorten(result.line.trim(), 180), result.file.ext)}</code>
    `;
    button.addEventListener("click", () => renderProjectFile(result.file, result.lineNumber));
    elements.projectSearchResults.appendChild(button);
  });
}

function renderProjectSearchEmpty() {
  elements.projectSearchResults.classList.add("empty-state");
  elements.projectSearchResults.textContent = state.project.files.length ? "输入关键词后搜索代码。" : "选择项目后可搜索代码。";
}

function renderProjectFile(file, focusLine) {
  state.project.selectedFile = file;
  if (!file) {
    elements.projectFilePath.textContent = "no file selected";
    elements.projectFilePreview.classList.add("empty-state");
    elements.projectFilePreview.textContent = "点击目录树或搜索结果查看文件内容。";
    return;
  }
  console.log("[ui] preview project file", { path: file.path, focusLine });
  elements.projectFilePath.textContent = file.path;
  elements.projectFilePreview.classList.remove("empty-state");
  elements.projectFilePreview.innerHTML = renderCodePreview(file, focusLine);
}

function applyProjectPrompt() {
  console.log("[ui] apply project prompt", {
    project: state.project.name,
    projectRoot: state.project.root,
    selectedFile: state.project.selectedFile ? state.project.selectedFile.path : null,
    searchResults: state.project.searchResults.length,
  });
  const evidence = buildProjectEvidenceContext();
  const projectRootLine = state.project.root ? `Project Root: ${state.project.root}` : "Project Root: not available from browser picker";
  const projectRootRule = state.project.root
    ? "真实项目模式约束：不要搜索当前 SE-Explorer-Agent 仓库；不要调用 search_docs 或 shell_readonly 来分析这个项目；所有 list_repo_tree、search_code、grep_code、view_file 调用都必须传入上方 Project Root 作为 project_root，并且 view_file 只允许使用 path/start/end/project_root 参数。"
    : "真实项目模式约束：不要搜索当前 SE-Explorer-Agent 仓库；不要调用 search_docs 或 shell_readonly 来分析这个项目；当前浏览器目录选择未提供本地 Project Root 绝对路径，请优先基于下方 UI-provided evidence 回答，不要猜测后端可访问的文件路径。";
  elements.questionInput.value = [
    `请基于 UI 离线项目探索得到的代码证据，分析项目 ${state.project.name} 的核心功能调用链。`,
    projectRootLine,
    "请重点说明前端页面、前端服务调用和后端接口之间的关系，给出带 evidence 引用的解释，并指出一个适合课堂汇报展示的代码理解结论。",
    "以下 [ev_9xx] 是由 UI 离线项目探索阶段提供的代码证据，可在最终回答中直接引用；如果后续工具调用产生新的 Evidence Memory，也可以同时引用真实工具证据。",
    projectRootRule,
    "",
    "离线探索证据：",
    evidence,
  ].join("\n");
  elements.scenarioSelect.value = "code";
  elements.maxStepsInput.value = "10";
  elements.taskIdInput.value = `${slugify(state.project.name)}_ui_project_demo`;
  elements.mockInput.checked = false;
  setStatus("Ready");
}

function buildProjectEvidenceContext() {
  const selected = state.project.selectedFile ? [state.project.selectedFile] : [];
  const searched = state.project.searchResults.slice(0, 8).map((result) => result.file);
  const uniqueFiles = Array.from(new Map([...selected, ...searched].map((file) => [file.path, file])).values()).slice(0, 6);
  if (!uniqueFiles.length) {
    return state.project.files.slice(0, 6).map((file) => `- ${file.path}`).join("\n");
  }
  return uniqueFiles
    .map((file, index) => {
      const evidenceId = `ev_${String(901 + index).padStart(3, "0")}`;
      return [
        `[${evidenceId}] UI-provided code evidence: ${file.path}`,
        "```",
        shorten(file.text, 1800),
        "```",
      ].join("\n");
    })
    .join("\n\n");
}

async function loadReports() {
  console.log("[ui] load reports");
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
  renderRunningState();
  const payload = {
    question: elements.questionInput.value,
    mock: elements.mockInput.checked,
    mock_scenario: elements.scenarioSelect.value,
    max_steps: Number(elements.maxStepsInput.value || 10),
    task_id: elements.taskIdInput.value,
  };
  console.log("[ui] run ask", payload);
  try {
    const result = await postJson("/api/ask", payload);
    state.result = result;
    renderResult();
    setStatus(`Done: ${result.task_id}`);
    console.log("[ui] ask done", {
      task_id: result.task_id,
      evidence_count: (result.evidence || []).length,
      trajectory_count: (result.trajectory || []).length,
      verifier_passed: Boolean(result.verification && result.verification.passed),
    });
  } catch (error) {
    console.log("[ui] ask failed", error);
    state.result = null;
    renderError(String(error.message || error));
    setBadge("failed", false);
    setStatus("Failed");
  } finally {
    setBusy(false);
  }
}

function renderResult() {
  const result = state.result || {};
  elements.answerOutput.textContent = result.answer || "";
  elements.verificationOutput.innerHTML = renderVerification(result.verification || {});
  const passed = Boolean(result.verification && result.verification.passed);
  setBadge(passed ? "passed" : "failed", passed);
  renderEvidence();
  renderTrajectory();
}

function renderVerification(verification) {
  const issues = verification.issues || [];
  const semanticChecks = verification.semantic_checks || [];
  const suggested = verification.suggested_next_action || null;
  return `
    <div class="kv-grid">
      <span>passed</span><strong>${escapeHtml(String(Boolean(verification.passed)))}</strong>
      <span>issues</span><strong>${escapeHtml(String(issues.length))}</strong>
      <span>suggestion</span><strong>${escapeHtml(verification.suggestion || "none")}</strong>
    </div>
    ${renderListBlock("Issues", issues)}
    ${renderActionBlock(suggested)}
    ${renderSemanticChecks(semanticChecks)}
  `;
}

function renderListBlock(title, values) {
  if (!values || !values.length) {
    return `<section class="detail-block"><h4>${escapeHtml(title)}</h4><p class="muted">none</p></section>`;
  }
  return `
    <section class="detail-block">
      <h4>${escapeHtml(title)}</h4>
      <ul>${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
    </section>
  `;
}

function renderActionBlock(action) {
  if (!action) {
    return `<section class="detail-block"><h4>Suggested Next Action</h4><p class="muted">none</p></section>`;
  }
  return `
    <section class="detail-block">
      <h4>Suggested Next Action</h4>
      <pre>${escapeHtml(JSON.stringify(action, null, 2))}</pre>
    </section>
  `;
}

function renderSemanticChecks(checks) {
  if (!checks || !checks.length) {
    return `<section class="detail-block"><h4>Semantic Checks</h4><p class="muted">none</p></section>`;
  }
  return `
    <section class="detail-block">
      <h4>Semantic Checks</h4>
      ${checks
        .map(
          (item) => `
            <article class="mini-card">
              <div class="item-head">
                <strong>${escapeHtml(item.supported ? "supported" : "unsupported")}</strong>
                <span class="badge ${item.supported ? "pass" : "fail"}">${escapeHtml(String(item.coverage || "n/a"))}</span>
              </div>
              <p>${escapeHtml(item.claim || "")}</p>
            </article>
          `,
        )
        .join("")}
    </section>
  `;
}

function renderEvidence() {
  const result = state.result || {};
  const filter = elements.evidenceFilter.value;
  const evidence = (result.evidence || []).filter((item) => filter === "all" || item.source_type === filter);
  elements.evidenceList.innerHTML = "";
  if (!evidence.length) {
    elements.evidenceList.classList.add("empty-state");
    elements.evidenceList.textContent = filter === "all" ? "暂无 evidence。" : `没有 ${filter} 类型 evidence。`;
    return;
  }
  elements.evidenceList.classList.remove("empty-state");
  evidence.forEach((item) => {
    const node = document.createElement("article");
    node.className = `item source-${item.source_type}`;
    node.innerHTML = `
      <div class="item-head">
        <div class="item-title">${escapeHtml(item.evidence_id)} · ${escapeHtml(item.source_type)}</div>
        <span class="badge ${item.used_in_final ? "pass" : "neutral"}">${item.used_in_final ? "used" : "stored"}</span>
      </div>
      <div class="item-meta">${escapeHtml(formatSource(item))}</div>
      <div class="meta-pills">${renderMetadataPills(item.metadata || {})}</div>
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
  if (!trajectory.length) {
    elements.trajectoryList.classList.add("empty-state");
    elements.trajectoryList.textContent = "暂无 trajectory。";
    return;
  }
  elements.trajectoryList.classList.remove("empty-state");
  trajectory.forEach((step) => {
    const node = document.createElement("article");
    node.className = "item";
    node.innerHTML = `
      <div class="item-head">
        <div class="item-title">Step ${escapeHtml(step.step)} · ${escapeHtml(step.action)}</div>
        <span class="badge ${step.success ? "pass" : "fail"}">${step.success ? "ok" : "fail"}</span>
      </div>
      <div class="item-meta">${escapeHtml(step.phase || "unknown phase")} · ${escapeHtml(String(step.latency_ms || 0))} ms</div>
      <div class="meta-pills">${renderEvidenceRefs(step.evidence_ids || [])}</div>
      <pre>${escapeHtml(shorten(step.observation_summary || "", 900))}</pre>
    `;
    elements.trajectoryList.appendChild(node);
  });
}

function renderSelectedReport() {
  const index = Number(elements.reportSelect.value || 0);
  const report = state.reports[index];
  if (!report) {
    elements.reportOutput.innerHTML = `<p class="empty-state">暂无 report。</p>`;
    elements.reportOutput.classList.add("empty-state");
    return;
  }
  elements.reportOutput.innerHTML = renderReport(report);
  elements.reportOutput.classList.toggle("empty-state", !report.exists);
}

function renderReport(report) {
  if (!report.exists) {
    return `
      <div class="report-card">
        <div class="report-meta">
          ${renderReportMeta("type", report.type)}
          ${renderReportMeta("path", report.path)}
          ${renderReportMeta("exists", report.exists)}
        </div>
        <p class="empty-state">${escapeHtml(report.path)} missing</p>
      </div>
    `;
  }
  return `
    <article class="report-card">
      <div class="report-meta">
        ${renderReportMeta("type", report.type)}
        ${renderReportMeta("path", report.path)}
        ${renderReportMeta("exists", report.exists)}
      </div>
      <div class="report-document">${renderReportMarkdown(report.content || "")}</div>
    </article>
  `;
}

function renderReportMeta(label, value) {
  const badgeClass = label === "exists" ? (value ? "pass" : "fail") : "neutral";
  return `
    <span class="report-meta-item">
      <span>${escapeHtml(label)}</span>
      <strong class="badge ${badgeClass}">${escapeHtml(String(value))}</strong>
    </span>
  `;
}

function renderReportMarkdown(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const nodes = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }
    if (line.trim().startsWith("```")) {
      const block = [];
      index += 1;
      while (index < lines.length && !lines[index].trim().startsWith("```")) {
        block.push(lines[index]);
        index += 1;
      }
      index += 1;
      nodes.push(`<pre class="report-code">${escapeHtml(block.join("\n"))}</pre>`);
      continue;
    }
    if (isMarkdownTableStart(lines, index)) {
      const tableLines = [];
      while (index < lines.length && lines[index].trim().startsWith("|")) {
        tableLines.push(lines[index]);
        index += 1;
      }
      nodes.push(renderMarkdownTable(tableLines));
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      const level = Math.min(heading[1].length + 2, 6);
      nodes.push(`<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`);
      index += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      nodes.push(`<ul>${items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join("")}</ul>`);
      continue;
    }
    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].trim().startsWith("```") &&
      !isMarkdownTableStart(lines, index) &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !/^\s*[-*]\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    nodes.push(`<p>${renderInlineMarkdown(paragraph.join(" "))}</p>`);
  }

  return nodes.join("");
}

function isMarkdownTableStart(lines, index) {
  return (
    index + 1 < lines.length &&
    lines[index].trim().startsWith("|") &&
    /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(lines[index + 1])
  );
}

function renderMarkdownTable(lines) {
  const rows = lines
    .filter((line, index) => index !== 1)
    .map((line) => line.trim().replace(/^\||\|$/g, "").split("|").map((cell) => cell.trim()));
  if (!rows.length) return "";
  const header = rows[0];
  const body = rows.slice(1);
  return `
    <div class="report-table-wrap">
      <table class="report-table">
        <thead><tr>${header.map((cell) => `<th>${renderInlineMarkdown(cell)}</th>`).join("")}</tr></thead>
        <tbody>
          ${body.map((row) => `<tr>${row.map((cell) => `<td>${renderInlineMarkdown(cell)}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderInlineMarkdown(text) {
  let value = escapeHtml(text);
  value = value.replace(/`([^`]+)`/g, '<code>$1</code>');
  value = value.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  value = value.replace(/\b(True|passed|pass_rate=1\.00|1\.00)\b/g, '<span class="report-good">$1</span>');
  value = value.replace(/\b(False|failed|0\.00)\b/g, '<span class="report-bad">$1</span>');
  return value;
}

function formatSource(item) {
  const parts = [item.source || ""];
  if (item.line_range) parts.push(item.line_range);
  if (item.metadata && item.metadata.page) parts.push(`page ${item.metadata.page}`);
  if (item.metadata && item.metadata.block_type) parts.push(item.metadata.block_type);
  return parts.filter(Boolean).join(" · ");
}

function renderMetadataPills(metadata) {
  const values = [];
  if (metadata.retrieval_strategy) values.push(["strategy", metadata.retrieval_strategy]);
  if (metadata.candidate_sources) values.push(["sources", metadata.candidate_sources.join(", ")]);
  if (metadata.page) values.push(["page", metadata.page]);
  if (metadata.block_type) values.push(["block", metadata.block_type]);
  if (metadata.score_parts && metadata.score_parts.bm25_score !== undefined) {
    values.push(["bm25", metadata.score_parts.bm25_score]);
  }
  if (!values.length) return "";
  return values
    .map(([label, value]) => `<span class="meta-pill">${escapeHtml(label)}: ${escapeHtml(shorten(value, 80))}</span>`)
    .join("");
}

function renderEvidenceRefs(ids) {
  if (!ids.length) return `<span class="meta-pill muted-pill">no evidence refs</span>`;
  return ids.map((id) => `<span class="meta-pill">${escapeHtml(id)}</span>`).join("");
}

function setBadge(text, passed) {
  elements.verifierBadge.textContent = text;
  elements.verifierBadge.className = `badge ${passed ? "pass" : "fail"}`;
}

function setBusy(isBusy) {
  elements.runButton.disabled = isBusy;
  elements.runButton.textContent = isBusy ? "Running..." : "Run Agent";
}

function setStatus(text) {
  elements.statusText.textContent = text;
  const normalized = String(text).toLowerCase();
  elements.statusText.className = "status-pill";
  if (normalized.startsWith("running")) elements.statusText.classList.add("running");
  if (normalized.startsWith("done")) elements.statusText.classList.add("done");
  if (normalized.startsWith("failed")) elements.statusText.classList.add("failed");
}

function renderEmptyState() {
  elements.answerOutput.textContent = "等待运行 Agent。";
  elements.verificationOutput.innerHTML = `<p class="empty-state">Verifier 将检查证据引用、事实支撑和任务覆盖。</p>`;
  elements.evidenceList.classList.add("empty-state");
  elements.evidenceList.textContent = "暂无 evidence。";
  elements.trajectoryList.classList.add("empty-state");
  elements.trajectoryList.textContent = "暂无 trajectory。";
  elements.stepCount.textContent = "0 steps";
  setBadge("pending", false);
  elements.verifierBadge.className = "badge neutral";
}

function renderRunningState() {
  elements.answerOutput.textContent = "Agent 正在检索文档、定位代码、收集证据并等待 Verifier 检查。";
  elements.verificationOutput.innerHTML = `<p class="empty-state">运行完成后显示 Verifier 分析。</p>`;
  elements.evidenceList.classList.add("empty-state");
  elements.evidenceList.textContent = "运行中，等待 evidence 写入。";
  elements.trajectoryList.classList.add("empty-state");
  elements.trajectoryList.textContent = "运行中，等待 trajectory 写入。";
  elements.stepCount.textContent = "running";
  setBadge("running", false);
  elements.verifierBadge.className = "badge neutral";
}

function renderError(message) {
  elements.answerOutput.textContent = `运行失败：${message}`;
  elements.verificationOutput.innerHTML = `<p class="empty-state">请检查任务参数、LLM 配置或后端日志。</p>`;
  elements.evidenceList.classList.add("empty-state");
  elements.evidenceList.textContent = "失败状态下没有新的 evidence。";
  elements.trajectoryList.classList.add("empty-state");
  elements.trajectoryList.textContent = "失败状态下没有新的 trajectory。";
  elements.stepCount.textContent = "0 steps";
}

function shouldIndexFile(path) {
  const normalized = normalizeProjectPath(path);
  if (!normalized || shouldSkipPath(normalized, false)) return false;
  return TEXT_EXTENSIONS.has(getExtension(normalized));
}

function shouldSkipPath(path, isDirectory) {
  const parts = normalizeProjectPath(path).split("/").filter(Boolean);
  if (parts.some((part) => SKIP_DIRS.has(part))) return true;
  if (isDirectory) return false;
  return parts.some((part) => part.startsWith(".") && part !== ".env.example");
}

function normalizeProjectPath(path) {
  return String(path || "").replace(/\\/g, "/").replace(/^\/+/, "");
}

function stripProjectRootPrefix(path, projectName) {
  const normalizedName = normalizeProjectPath(projectName);
  if (!normalizedName || !path.startsWith(`${normalizedName}/`)) return path;
  return path.slice(normalizedName.length + 1);
}

function getExtension(path) {
  const name = normalizeProjectPath(path).split("/").pop() || "";
  const index = name.lastIndexOf(".");
  return index >= 0 ? name.slice(index).toLowerCase() : "";
}

function inferProjectNameFromInputFiles(files) {
  const firstPath = files[0] ? files[0].webkitRelativePath || files[0].name : "";
  return firstPath.split(/[\\/]/).filter(Boolean)[0] || "selected-project";
}

function inferProjectNameFromRoot(root) {
  return String(root || "").split(/[\\/]/).filter(Boolean).pop() || "selected-project";
}

function createMatcher(query) {
  try {
    const regex = new RegExp(query, "i");
    return (text) => regex.test(text);
  } catch (_) {
    const lowered = query.toLowerCase();
    return (text) => String(text).toLowerCase().includes(lowered);
  }
}

function extractLineContext(lines, index) {
  const start = Math.max(0, index - 2);
  const end = Math.min(lines.length, index + 3);
  return lines.slice(start, end).map((line, offset) => `${start + offset + 1}: ${line}`).join("\n");
}

function renderCodePreview(file, focusLine) {
  const lines = file.text.split(/\r?\n/);
  const start = focusLine ? Math.max(0, focusLine - 35) : 0;
  const end = focusLine ? Math.min(lines.length, focusLine + 45) : Math.min(lines.length, 260);
  const codeRows = lines
    .slice(start, end)
    .map((line, index) => {
      const lineNumber = start + index + 1;
      const focused = lineNumber === focusLine;
      return `
        <div class="code-line ${focused ? "focused" : ""}" data-line="${lineNumber}">
          <span class="line-number">${lineNumber}</span>
          <code>${highlightCodeInline(line, file.ext)}</code>
        </div>
      `;
    })
    .join("\n");
  return `
    <div class="code-toolbar">
      <span>${escapeHtml(file.name || file.path)}</span>
      <span>${escapeHtml(file.ext || "text")} · ${escapeHtml(String(lines.length))} lines</span>
    </div>
    <div class="code-scroll">${codeRows}</div>
  `;
}

function highlightCodeInline(line, ext) {
  let value = escapeHtml(line);
  value = value.replace(/("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g, '<span class="tok-string">$1</span>');
  value = value.replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="tok-number">$1</span>');
  value = value.replace(
    /\b(const|let|var|function|return|if|else|for|while|class|public|private|protected|static|final|new|import|export|from|try|catch|throw|async|await|void|int|long|double|boolean|String|Map|List)\b/g,
    '<span class="tok-keyword">$1</span>',
  );
  value = value.replace(/(\/\/.*)$/g, '<span class="tok-comment">$1</span>');
  if ([".py", ".yml", ".yaml"].includes(ext)) {
    value = value.replace(/(#.*)$/g, '<span class="tok-comment">$1</span>');
  }
  return value;
}

function getTreeDepth(path) {
  return normalizeProjectPath(path).split("/").filter(Boolean).length;
}

function setProjectStatus(text) {
  elements.projectStatus.textContent = text;
}

function slugify(value) {
  const slug = String(value || "project")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  return slug || "project";
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
