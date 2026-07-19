// Workflow 탭 (§12.7) — 실행 타임라인 렌더 전용.
// 데이터·상태 도출은 전부 서버(WorkflowStore) 몫 — 여기는 스냅샷 로딩
// + EventSource 수신 + DOM 렌더만 한다 (§13.2).

const $ = (id) => document.getElementById(id);

const STATE_LABEL = { active: "진행 중", idle: "대기", ended: "종료" };
const SOURCE_LABEL = {
  startup: "새 세션", resume: "재개", clear: "초기화", unknown: "세션",
};

export function initWorkflow(ctx) {
  // session_id → { meta, steps: Map(step_id → step) }
  const sessions = new Map();
  let es = null;
  let pluginOnly = false;
  let ticker = null;

  // ── 수신 ──
  function connect() {
    es = new EventSource("/api/workflow/stream");
    es.onopen = loadSnapshot; // 최초 + 자동 재연결 시 재동기화 (§12.7)
    es.addEventListener("message", (e) => {
      try { handle(JSON.parse(e.data)); } catch { /* 형식 밖 무시 */ }
    });
    // onerror: EventSource가 스스로 재연결 → onopen에서 복구
  }

  async function loadSnapshot() {
    try {
      const body = await ctx.api("/api/workflow/sessions");
      sessions.clear();
      for (const s of body.sessions) {
        sessions.set(s.session_id, {
          meta: s,
          steps: new Map(s.steps.map((st) => [st.step_id, st])),
        });
      }
      render();
    } catch { /* 401은 래퍼가 처리 */ }
  }

  function upsert(meta) {
    let entry = sessions.get(meta.session_id);
    if (!entry) {
      entry = { meta, steps: new Map() };
      sessions.set(meta.session_id, entry);
    } else {
      entry.meta = meta;
    }
    return entry;
  }

  function handle(ev) {
    if (ev.type === "clear") {
      sessions.clear();
    } else if (ev.type === "session") {
      upsert(ev.session);
    } else if (ev.type === "step") {
      upsert(ev.session).steps.set(ev.step.step_id, ev.step);
    } else {
      return;
    }
    render();
  }

  // ── 렌더 ──
  function fmtClock(epoch) {
    return new Date(epoch * 1000).toLocaleTimeString("ko-KR", { hour12: false });
  }

  function fmtElapsed(step) {
    const end = step.ended_at ?? Date.now() / 1000;
    const sec = Math.max(0, end - step.started_at);
    if (sec < 10) return sec.toFixed(1) + "s";
    if (sec < 60) return Math.round(sec) + "s";
    return Math.floor(sec / 60) + "m " + Math.round(sec % 60) + "s";
  }

  function stepRow(step) {
    const row = document.createElement("div");
    row.className = `wf-step ${step.status}` + (step.is_plugin ? " plugin" : "");
    row.style.marginLeft = step.depth * 22 + "px";

    const dot = document.createElement("span");
    dot.className = "wf-dot " + step.status;
    dot.textContent = step.status === "done" ? "✓"
      : step.status === "failed" ? "✗" : "";
    row.appendChild(dot);

    const body = document.createElement("span");
    body.className = "wf-body";
    const name = document.createElement("span");
    name.className = "wf-name";
    name.textContent = step.kind === "prompt" ? "프롬프트"
      : step.kind === "subagent" ? `서브에이전트 ${step.agent_type || ""}`
      : step.tool_name || "도구";
    body.appendChild(name);
    if (step.plugin) {
      const badge = document.createElement("span");
      badge.className = "wf-plugin-badge";
      badge.textContent = step.plugin;
      body.appendChild(badge);
    }
    const sum = document.createElement("span");
    sum.className = "wf-sum";
    sum.textContent = step.summary || "";
    body.appendChild(sum);
    row.appendChild(body);

    const time = document.createElement("span");
    time.className = "wf-time";
    time.textContent = step.status === "running"
      ? fmtElapsed(step) + " …"
      : `${fmtClock(step.started_at)} · ${fmtElapsed(step)}`;
    row.appendChild(time);
    return row;
  }

  function sessionCard(entry) {
    const { meta } = entry;
    const card = document.createElement("div");
    card.className = "wf-card";

    const head = document.createElement("div");
    head.className = "wf-head";
    const dot = document.createElement("span");
    dot.className = "wf-state " + meta.state;
    head.appendChild(dot);
    const title = document.createElement("span");
    title.className = "wf-title";
    title.textContent =
      `${SOURCE_LABEL[meta.source] || meta.source} ${meta.short_id}`
      + (meta.model ? ` · ${meta.model}` : "");
    head.appendChild(title);
    const stateTxt = document.createElement("span");
    stateTxt.className = "wf-statetxt";
    stateTxt.textContent = STATE_LABEL[meta.state] || meta.state;
    head.appendChild(stateTxt);
    card.appendChild(head);

    const line = document.createElement("div");
    line.className = "wf-line";
    let shown = 0;
    for (const step of entry.steps.values()) {
      if (pluginOnly && !step.is_plugin) continue;
      line.appendChild(stepRow(step));
      shown += 1;
    }
    if (!shown) {
      const empty = document.createElement("div");
      empty.className = "wf-empty";
      empty.textContent = pluginOnly ? "플러그인 도구 실행 없음" : "아직 단계 없음";
      line.appendChild(empty);
    }
    card.appendChild(line);
    return card;
  }

  function render() {
    const list = $("wfList");
    if (!list) return;
    list.replaceChildren();
    if (!sessions.size) {
      const empty = document.createElement("div");
      empty.className = "wf-empty big";
      empty.textContent =
        "아직 기록이 없습니다 — 챗이나 내장 터미널에서 claude가 도구를 "
        + "쓰면 여기에 실시간으로 나타납니다";
      list.appendChild(empty);
      return;
    }
    const ordered = [...sessions.values()]
      .sort((a, b) => b.meta.last_event_at - a.meta.last_event_at);
    for (const entry of ordered) list.appendChild(sessionCard(entry));
    if ($("wfAutoScroll").checked) list.scrollTop = 0; // 최신 세션이 위
  }

  // 진행 중 경과시간 1초 갱신 — 탭이 보일 때만
  function startTicker() {
    if (ticker) return;
    ticker = setInterval(() => {
      if (!$("view-flow").classList.contains("on")) return;
      const hasRunning = [...sessions.values()].some((e) =>
        [...e.steps.values()].some((s) => s.status === "running"));
      if (hasRunning) render();
    }, 1000);
  }

  // ── 컨트롤 ──
  function setFilter(plugin) {
    pluginOnly = plugin;
    $("wfFilterAll").classList.toggle("on", !plugin);
    $("wfFilterPlugin").classList.toggle("on", plugin);
    render();
  }
  $("wfFilterAll").addEventListener("click", () => setFilter(false));
  $("wfFilterPlugin").addEventListener("click", () => setFilter(true));

  function ensure() {
    if (!es) connect();
    startTicker();
  }

  async function clearAll() {
    try {
      await ctx.api("/api/workflow", { method: "DELETE" });
      ctx.toast("workflow 기록을 지웠습니다");
    } catch (ex) {
      ctx.toast(ex.message, "err");
    }
  }

  function reset() { // 로그아웃 시 — 구독 종료 + 화면 비움
    if (es) { es.close(); es = null; }
    if (ticker) { clearInterval(ticker); ticker = null; }
    sessions.clear();
    render();
  }

  return { ensure, clearAll, reset };
}
