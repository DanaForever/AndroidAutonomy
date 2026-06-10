const state = {
  task: null,
  trace: null,
  image: null,
  live: null,
  primary: null,
  secondary: null,
};

const $ = (id) => document.getElementById(id);

function showMessage(text, kind = "") {
  const el = document.createElement("div");
  el.className = `message ${kind}`;
  el.textContent = text;
  $("messages").prepend(el);
  setTimeout(() => el.remove(), 9000);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || (data.errors || []).join("; ") || `${path} failed`);
  }
  return data;
}

function coordText(c) {
  return c ? `px [${c.pixel[0]}, ${c.pixel[1]}] qwen [${c.qwen[0]}, ${c.qwen[1]}]` : "-";
}

function refreshCoordStatus() {
  $("coordStatus").textContent =
    `live: ${coordText(state.live)}, frozen: ${coordText(state.primary)}, end: ${coordText(state.secondary)}`;
  renderCommands();
}

function qwenFromPixel(x, y) {
  const w = state.image?.width || 1;
  const h = state.image?.height || 1;
  return [Math.round(x * 999 / w), Math.round(y * 999 / h)];
}

function currentAction() {
  const type = $("actionType").value;
  if (type === "click" || type === "long_press") {
    if (!state.primary) return null;
    return { type, pixel: state.primary.pixel, qwen: state.primary.qwen };
  }
  if (type === "swipe") {
    if (!state.primary || !state.secondary) return null;
    return {
      type,
      pixel: [state.primary.pixel, state.secondary.pixel],
      qwen: [state.primary.qwen, state.secondary.qwen],
      duration_ms: Number($("durationInput").value || 400),
    };
  }
  if (type === "type") {
    return { type, text: $("textInput").value };
  }
  if (type === "system_button") {
    return { type, button: $("buttonInput").value };
  }
  if (type === "wait") {
    return { type, duration_ms: Number($("durationInput").value || 1000) };
  }
  if (type === "terminate") {
    return { type, status: "success" };
  }
  return null;
}

function shellQuote(text) {
  return `'${String(text).replaceAll("'", "'\\''")}'`;
}

function adbCommand(action) {
  if (!action) return "";
  if (action.type === "click") return `adb shell input tap ${action.pixel[0]} ${action.pixel[1]}`;
  if (action.type === "long_press") {
    return `adb shell input swipe ${action.pixel[0]} ${action.pixel[1]} ${action.pixel[0]} ${action.pixel[1]} ${action.duration_ms || 700}`;
  }
  if (action.type === "swipe") {
    const [a, b] = action.pixel;
    return `adb shell input swipe ${a[0]} ${a[1]} ${b[0]} ${b[1]} ${action.duration_ms || 400}`;
  }
  if (action.type === "type") return `adb shell input text ${shellQuote(action.text || "")}`;
  if (action.type === "system_button") {
    const map = { Back: "KEYCODE_BACK", Home: "KEYCODE_HOME", Enter: "KEYCODE_ENTER" };
    return `adb shell input keyevent ${map[action.button] || action.button}`;
  }
  if (action.type === "wait") return "";
  return "";
}

function toolCall(action) {
  if (!action) return "";
  const args = {};
  if (action.type === "click" || action.type === "long_press") {
    args.action = action.type;
    args.coordinate = action.qwen;
  } else if (action.type === "swipe") {
    args.action = "swipe";
    args.coordinate = action.qwen[0];
    args.coordinate2 = action.qwen[1];
  } else if (action.type === "type") {
    args.action = "type";
    args.text = action.text || "";
  } else if (action.type === "system_button") {
    args.action = "system_button";
    args.button = action.button;
  } else if (action.type === "wait") {
    args.action = "wait";
    args.time = Math.max(1, Math.round((action.duration_ms || 1000) / 1000));
  } else if (action.type === "terminate") {
    args.action = "terminate";
    args.status = action.status || "success";
  }
  return JSON.stringify({ name: "mobile_use", arguments: args });
}

function renderCommands() {
  const action = currentAction();
  $("adbCommand").textContent = adbCommand(action);
  $("toolCall").textContent = toolCall(action);
}

function renderActionControls() {
  const type = $("actionType").value;
  $("textRow").style.display = type === "type" ? "grid" : "none";
  $("buttonRow").style.display = type === "system_button" ? "grid" : "none";
  $("durationRow").style.display = ["swipe", "long_press", "wait"].includes(type) ? "grid" : "none";
  renderCommands();
}

async function loadTask() {
  state.task = await api("/task");
  $("taskName").textContent = state.task.task_name;
  $("taskGoal").textContent = state.task.goal || "";
  renderTaskParams();
  $("budget").textContent = state.task.budget ?? "-";
  $("optimalSteps").textContent = state.task.optimal_steps ?? "-";
  $("savedCount").textContent = state.task.saved_trajectories ?? 0;
  $("successCriteria").textContent = state.task.success_criteria || "";
  renderSuccessChecks();
}

function renderTaskParams() {
  const root = $("taskParams");
  root.innerHTML = "";
  const params = state.task.params || {};
  for (const [key, value] of Object.entries(params)) {
    const chip = document.createElement("div");
    chip.className = "param-chip";
    chip.title = `${key}: ${value}`;
    chip.innerHTML = `<strong>${escapeHtml(key)}</strong>: ${escapeHtml(value)}`;
    root.append(chip);
  }
}

async function loadDevice() {
  const status = await api("/device_status");
  $("adbStatus").textContent = status.ok ? (status.device || "ok") : "offline";
  if (!status.ok && status.error) showMessage(status.error, "error");
}

async function loadTrace() {
  state.trace = await api("/trace");
  renderTrace();
}

function renderSuccessChecks() {
  const root = $("successChecks");
  root.innerHTML = "";
  for (const check of state.task.success_checks || []) {
    const card = document.createElement("div");
    card.className = "check-card";
    const title = document.createElement("strong");
    title.textContent = check.label || "Check";
    const expected = document.createElement("div");
    expected.textContent = check.expected ? `Expected: ${check.expected}` : "";
    const command = document.createElement("code");
    command.textContent = check.command || "";
    const row = document.createElement("div");
    row.className = "button-row";
    const copy = document.createElement("button");
    copy.textContent = "Copy";
    copy.onclick = () => copyText(check.command || "");
    row.append(copy);
    if (check.safe_to_run) {
      const run = document.createElement("button");
      run.textContent = "Run";
      run.onclick = async () => {
        try {
          const out = await api("/run_adb", { method: "POST", body: JSON.stringify({ command: check.command }) });
          showMessage((out.stdout || out.stderr || "").trim() || `exit ${out.returncode}`, out.ok ? "ok" : "error");
        } catch (e) {
          showMessage(e.message, "error");
        }
      };
      row.append(run);
    }
    card.append(title, expected, command, row);
    root.append(card);
  }
}

function renderTrace() {
  const tbody = $("traceRows");
  tbody.innerHTML = "";
  const steps = state.trace?.steps || [];
  for (const step of steps) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${step.step_index}</td>
      <td>${step.screenshot || ""}</td>
      <td><code>${escapeHtml(JSON.stringify(step.action))}</code></td>
      <td><code>${escapeHtml(step.adb_command || "")}</code></td>
      <td>${escapeHtml(step.human_note || "")}</td>
      <td><button data-delete-step="${step.step_index}">Delete</button></td>
    `;
    tbody.append(tr);
  }
  tbody.querySelectorAll("[data-delete-step]").forEach((btn) => {
    btn.onclick = () => deleteStep(Number(btn.dataset.deleteStep));
  });
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function capture() {
  const data = await api("/capture", { method: "POST", body: "{}" });
  state.image = { width: data.width, height: data.height, screenshot: data.screenshot };
  const img = $("screenshot");
  img.src = data.image_url;
  img.style.display = "block";
  $("hoverBadge").textContent = `${data.width}x${data.height} step ${data.step_index}`;
  await loadTrace();
}

function imageCoords(evt) {
  const img = $("screenshot");
  if (!img.src) return null;
  const rect = img.getBoundingClientRect();
  if (evt.clientX < rect.left || evt.clientX > rect.right || evt.clientY < rect.top || evt.clientY > rect.bottom) {
    return null;
  }
  const x = Math.max(0, Math.min(state.image.width - 1, Math.round((evt.clientX - rect.left) * state.image.width / rect.width)));
  const y = Math.max(0, Math.min(state.image.height - 1, Math.round((evt.clientY - rect.top) * state.image.height / rect.height)));
  return { pixel: [x, y], qwen: qwenFromPixel(x, y), clientX: evt.clientX, clientY: evt.clientY };
}

function onImageMove(evt) {
  const coords = imageCoords(evt);
  if (!coords) return;
  state.live = { pixel: coords.pixel, qwen: coords.qwen };
  const wrapRect = $("imageWrap").getBoundingClientRect();
  $("crosshairX").style.display = "block";
  $("crosshairY").style.display = "block";
  $("crosshairX").style.top = `${coords.clientY - wrapRect.top + $("imageWrap").scrollTop}px`;
  $("crosshairY").style.left = `${coords.clientX - wrapRect.left + $("imageWrap").scrollLeft}px`;
  $("hoverBadge").textContent = coordText(state.live);
  refreshCoordStatus();
}

function freezePrimary() {
  if (state.live) {
    state.primary = { pixel: [...state.live.pixel], qwen: [...state.live.qwen] };
    refreshCoordStatus();
  }
}

function freezeSecondary() {
  if (state.live) {
    state.secondary = { pixel: [...state.live.pixel], qwen: [...state.live.qwen] };
    refreshCoordStatus();
  }
}

function clearCoords() {
  state.primary = null;
  state.secondary = null;
  refreshCoordStatus();
}

async function copyText(text) {
  await navigator.clipboard.writeText(text || "");
  showMessage("Copied", "ok");
}

async function recordAction(actionOverride = null, noteOverride = null, verifiedOverride = null) {
  const action = actionOverride || currentAction();
  if (!action) {
    showMessage("Action is missing required coordinates or fields", "error");
    return;
  }
  const payload = {
    screenshot: state.image?.screenshot,
    action,
    adb_command: adbCommand(action),
    human_note: noteOverride ?? $("humanNote").value,
    verified: verifiedOverride ?? $("stepVerified").checked,
  };
  const data = await api("/record_action", { method: "POST", body: JSON.stringify(payload) });
  state.trace = data.trace;
  state.image = null;
  clearCoords();
  renderTrace();
  showMessage(`Recorded step ${data.step.step_index}`, "ok");
}

async function runAdb() {
  const command = $("adbCommand").textContent.trim();
  if (!command) {
    showMessage("No ADB command for this action", "error");
    return;
  }
  const out = await api("/run_adb", { method: "POST", body: JSON.stringify({ command }) });
  showMessage((out.stdout || out.stderr || "").trim() || `exit ${out.returncode}`, out.ok ? "ok" : "error");
}

async function addTerminate() {
  $("actionType").value = "terminate";
  renderActionControls();
  await recordAction(
    { type: "terminate", status: "success" },
    $("humanNote").value || "task success criteria verified",
    true,
  );
}

async function saveTrajectory() {
  const payload = {
    verification: {
      success_verified: $("successVerified").checked,
      method: $("verificationMethod").value,
    },
  };
  const data = await api("/save_trajectory", { method: "POST", body: JSON.stringify(payload) });
  if (!data.ok) {
    showMessage((data.errors || []).join("; "), "error");
    return;
  }
  showMessage(`Saved ${data.trajectory_id}`, "ok");
  await loadTask();
  await loadTrace();
}

async function discardDraft() {
  await api("/new_trajectory", { method: "POST", body: JSON.stringify({ discard: true }) });
  state.image = null;
  $("screenshot").style.display = "none";
  clearCoords();
  await loadTrace();
  showMessage("Draft discarded", "ok");
}

async function deleteStep(stepIndex) {
  const data = await api("/delete_step", {
    method: "POST",
    body: JSON.stringify({ step_index: stepIndex }),
  });
  state.trace = data.trace;
  renderTrace();
  showMessage(`Deleted step ${stepIndex}`, "ok");
}

function bindEvents() {
  $("captureBtn").onclick = () => capture().catch((e) => showMessage(e.message, "error"));
  $("clearCoordsBtn").onclick = clearCoords;
  $("copyAdbBtn").onclick = () => copyText($("adbCommand").textContent);
  $("copyToolBtn").onclick = () => copyText($("toolCall").textContent);
  $("runAdbBtn").onclick = () => runAdb().catch((e) => showMessage(e.message, "error"));
  $("recordBtn").onclick = () => recordAction().catch((e) => showMessage(e.message, "error"));
  $("addTerminateBtn").onclick = () => addTerminate().catch((e) => showMessage(e.message, "error"));
  $("saveTrajectoryBtn").onclick = () => saveTrajectory().catch((e) => showMessage(e.message, "error"));
  $("discardBtn").onclick = () => discardDraft().catch((e) => showMessage(e.message, "error"));
  $("imageWrap").addEventListener("mousemove", onImageMove);
  $("imageWrap").addEventListener("click", freezePrimary);
  $("actionType").onchange = renderActionControls;
  $("textInput").oninput = renderCommands;
  $("buttonInput").onchange = renderCommands;
  $("durationInput").oninput = renderCommands;
  document.addEventListener("keydown", (evt) => {
    if (evt.target.matches("input, textarea, select")) return;
    if (evt.key === "c") capture().catch((e) => showMessage(e.message, "error"));
    if (evt.key === "s" && !evt.ctrlKey) freezePrimary();
    if (evt.key === "e") freezeSecondary();
    if (evt.key === "r") clearCoords();
    if (evt.key === "a") recordAction().catch((e) => showMessage(e.message, "error"));
    if (evt.key === "s" && evt.ctrlKey) {
      evt.preventDefault();
      saveTrajectory().catch((e) => showMessage(e.message, "error"));
    }
  });
}

async function init() {
  bindEvents();
  renderActionControls();
  await loadTask();
  await loadDevice();
  await loadTrace();
}

init().catch((e) => showMessage(e.message, "error"));
