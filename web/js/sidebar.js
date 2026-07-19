// 사이드바 (§12.2) — org 등록·플러그인 카탈로그·preset. fetch·렌더·이벤트만.
// 외부 데이터 렌더는 전부 textContent (XSS §11).

const STATE_LABEL = { enabled: ["사용중", "on"], installed: ["꺼짐", "off"], available: ["미설치", "no"] };
const ACTION_LABEL = { install: "설치", uninstall: "삭제", enable: "켜기", disable: "끄기", update: "업데이트" };
const BATCH_LABEL = { install: "일괄 설치", enable: "일괄 켜기", disable: "일괄 끄기", uninstall: "일괄 삭제", apply: "전환" };
const BADGE = { "all-on": ["on", "전부 켜짐"], partial: ["partial", "일부 켜짐"], off: ["off", "꺼짐"] };
const enc = encodeURIComponent;

export function initSidebar(ctx) {
  const $ = (id) => document.getElementById(id);
  let orgs = [];
  let plugins = [];
  let presets = [];
  const filter = { q: "", state: "all" };
  let openPop = null;

  // ── DOM 헬퍼 ──
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function icon(name, size) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "ic");
    if (size) { svg.style.width = size + "px"; svg.style.height = size + "px"; }
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#" + name);
    svg.appendChild(use);
    return svg;
  }
  function iconBtn(sym, title, cls) {
    const b = el("button", cls);
    b.type = "button";
    b.title = title;
    b.appendChild(icon(sym, 12));
    return b;
  }
  function textBtn(label, cls) {
    const b = el("button", cls, label);
    b.type = "button";
    return b;
  }

  let onPopClose = null; // 팝업이 닫힐 때 1회 실행 (멤버 편집 후 재렌더용)
  function closePop() {
    if (openPop) { openPop.remove(); openPop = null; }
    if (onPopClose) { const fn = onPopClose; onPopClose = null; fn(); }
  }
  document.addEventListener("click", (e) => {
    if (openPop && !openPop.contains(e.target)) closePop();
  });

  function fail(e) { // 401은 공통 래퍼가 로그인 뷰로 복귀시킨다
    if (e.status !== 401) ctx.toast(e.message, "err");
  }

  // ── 데이터 로드 ──
  async function loadOrgs() { orgs = await ctx.api("/api/orgs"); }
  async function loadPlugins() { plugins = await ctx.api("/api/plugins?cached=1"); }
  async function loadPresets() { presets = await ctx.api("/api/presets"); }

  async function refreshAll() { // 시작·org 변경 시 — org 재검증 포함 (§10.2)
    try { await Promise.all([loadOrgs(), loadPlugins(), loadPresets()]); }
    catch (e) { fail(e); }
    render();
  }
  async function refreshData() { // 액션 후 — 목록·preset만 갱신
    try { await Promise.all([loadPlugins(), loadPresets()]); }
    catch (e) { fail(e); }
    render();
  }

  // ── 필터 (§12.2: 페이지네이션 대신 검색 + 칩) ──
  function qMatch(p) {
    if (!filter.q) return true;
    const q = filter.q.toLowerCase();
    return p.name.toLowerCase().includes(q)
      || (p.description || "").toLowerCase().includes(q)
      || p.org.toLowerCase().includes(q);
  }
  function matches(p) {
    return qMatch(p) && (filter.state === "all" || p.state === filter.state);
  }

  function render() {
    closePop();
    renderChips();
    renderPresets();
    renderPlugins();
  }

  function renderChips() {
    const base = plugins.filter(qMatch);
    const counts = { all: base.length, enabled: 0, installed: 0, available: 0 };
    base.forEach((p) => { if (counts[p.state] !== undefined) counts[p.state] += 1; });
    const box = $("chips");
    box.textContent = "";
    [["all", "전체"], ["enabled", "사용중"], ["installed", "꺼짐"], ["available", "미설치"]]
      .forEach(([key, label]) => {
        const chip = el("span", "chip" + (filter.state === key ? " on" : ""));
        if (key !== "all") chip.appendChild(el("span", "d " + key));
        chip.appendChild(document.createTextNode(`${label} ${counts[key]}`));
        chip.addEventListener("click", () => { filter.state = key; render(); });
        box.appendChild(chip);
      });
  }

  // ── org 그룹 + 플러그인 행 ──
  function renderPlugins() {
    const box = $("pluginList");
    box.textContent = "";
    const registered = new Map(orgs.map((o) => [o.name, o]));
    const groups = {};
    plugins.filter(matches).forEach((p) => {
      (groups[p.org] = groups[p.org] || []).push(p);
    });
    // 등록 org 먼저, 그다음 카탈로그에만 남은 미등록 org (§12.2 고아 방지)
    const names = orgs.map((o) => o.name).concat(
      Object.keys(groups).filter((n) => !registered.has(n)).sort());
    let any = false;
    let cardIdx = 0; // 레시피 카드 헤더 틴트 2톤 순환 (amber/green)
    names.forEach((name) => {
      const org = registered.get(name);
      let rows = groups[name] || [];
      if (!org) rows = rows.filter((p) => p.state !== "available"); // 설치본만
      if (!org && !rows.length) return;
      any = true;
      const card = el("div", "org-card" + (cardIdx % 2 ? " tint-1" : ""));
      cardIdx += 1;
      card.appendChild(orgHeader(name, org, rows));
      rows.forEach((p) => card.appendChild(pluginRow(p, org)));
      box.appendChild(card);
    });
    if (!any) {
      box.appendChild(el("div", "empty",
        orgs.length ? "조건에 맞는 플러그인이 없습니다" : "organization을 추가하면 플러그인이 표시됩니다"));
    }
  }

  function orgHeader(name, org, rows) {
    const h = el("div", "org-h");
    h.appendChild(icon("i-dripper", 14));
    h.appendChild(el("span", "", name));
    h.appendChild(el("span", "n", `${rows.length}개`));
    if (org && !org.authorized) h.appendChild(el("span", "tag warn", "권한 없음")); // 잠금 표시 (§10.2)
    if (!org) h.appendChild(el("span", "tag", "미등록"));
    const sp = el("span", "sp");
    if (org) {
      const rf = iconBtn("i-refresh", "재스캔", "btn ghost sm needs-auth");
      rf.addEventListener("click", () => rescanOrg(name, rf));
      const rm = iconBtn("i-x", "org 제거 (설치본 포함 삭제)", "btn ghost sm needs-auth");
      rm.addEventListener("click", () => confirmRemoveOrg(name, sp, rf, rm));
      sp.append(rf, rm);
    }
    h.appendChild(sp);
    return h;
  }

  function pluginRow(p) {
    const row = el("div", "plugin");
    const bean = icon("i-bean", 13); // 원두 아이콘 — 사용중이면 진한 브라운
    bean.classList.add(p.state === "enabled" ? "bean-on" : "bean-off");
    row.appendChild(bean);
    row.appendChild(el("span", "nm", p.name));
    row.appendChild(el("span", "lead")); // 메뉴판식 dotted leader
    row.appendChild(el("span", "desc", p.description || ""));
    // 행 hover 시 '+ preset' — 멤버 추가/제거 토글 (§6.5)
    const addp = iconBtn("i-plus", "preset에 추가", "btn ghost sm addp needs-auth");
    addp.addEventListener("click", (e) => { e.stopPropagation(); openPresetPick(row, p); });
    row.appendChild(addp);
    const [label, cls] = STATE_LABEL[p.state] || [p.state, "no"];
    const st = el("span", "st " + cls);
    st.appendChild(el("span", "d"));
    st.appendChild(document.createTextNode(label));
    row.appendChild(st);
    const acts = el("span", "acts");
    row.appendChild(acts);
    fillActions(acts, p);
    return row;
  }

  function fillActions(acts, p) {
    acts.textContent = "";
    if (p.state === "available") {
      const b = textBtn("", "btn sm primary needs-auth");
      b.appendChild(icon("i-dl", 11));
      b.appendChild(document.createTextNode("설치"));
      b.addEventListener("click", () => doAction(p, "install", acts));
      acts.appendChild(b);
      return;
    }
    const toggle = textBtn(p.state === "enabled" ? "끄기" : "켜기", "btn ghost sm needs-auth");
    toggle.addEventListener("click", () =>
      doAction(p, p.state === "enabled" ? "disable" : "enable", acts));
    acts.appendChild(toggle);
    const up = iconBtn("i-refresh", "업데이트", "btn ghost sm needs-auth");
    up.addEventListener("click", () => doAction(p, "update", acts));
    acts.appendChild(up);
    const del = iconBtn("i-trash", "삭제 (uninstall)", "btn ghost sm danger needs-auth");
    del.addEventListener("click", () => { // 파괴적 동작 — 인라인 확인 (§12.2)
      acts.textContent = "";
      acts.appendChild(el("span", "confirm", "삭제할까요?"));
      const yes = textBtn("삭제", "btn sm dangerp");
      yes.addEventListener("click", () => doAction(p, "uninstall", acts));
      const no = textBtn("취소", "btn ghost sm");
      no.addEventListener("click", () => fillActions(acts, p));
      acts.append(yes, no);
    });
    acts.appendChild(del);
  }

  async function doAction(p, action, acts) {
    acts.querySelectorAll("button").forEach((b) => { b.disabled = true; });
    try {
      const r = await ctx.api(
        `/api/plugins/${enc(p.org)}/${enc(p.name)}/${action}`, { method: "POST" });
      let text = `${p.org}/${p.name} ${ACTION_LABEL[action]} 완료 — ${r.note || ""}`;
      if (r.warnings && r.warnings.length) text += "\n" + r.warnings.join("\n");
      ctx.toast(text);
    } catch (e) { fail(e); }
    await refreshData();
  }

  // ── org 추가/제거/재스캔 (§10.2) ──
  async function addOrg() {
    const input = $("orgUrl");
    const url = input.value.trim();
    if (!url) return;
    const err = $("orgErr");
    err.hidden = true;
    const btn = $("orgAddBtn");
    btn.disabled = true;
    btn.classList.add("busy"); // 검증 중 스피너
    try {
      const r = await ctx.api("/api/orgs", { method: "POST", body: { url } });
      input.value = "";
      ctx.toast(`${r.name} 등록 완료 — 플러그인 ${r.plugin_count}개 발견`);
      await ctx.recheckSession(); // 미검증 세션이 검증됐을 수 있음 (§10.2)
      await refreshAll();
      closeOrgPop(); // 등록 성공 — 팝오버는 아이콘으로 복귀 (§12.2)
    } catch (e) {
      if (e.status !== 401) { err.textContent = e.message; err.hidden = false; } // 인라인 사유
    } finally {
      btn.disabled = false;
      btn.classList.remove("busy");
    }
  }

  function confirmRemoveOrg(name, sp, rf, rm) {
    const installed = plugins.filter(
      (p) => p.org === name && p.state !== "available").length;
    sp.textContent = "";
    sp.appendChild(el("span", "confirm",
      installed ? `설치본 ${installed}개 포함 삭제할까요?` : "org를 삭제할까요?"));
    const yes = textBtn("삭제", "btn sm dangerp");
    yes.addEventListener("click", () => removeOrg(name));
    const no = textBtn("취소", "btn ghost sm");
    no.addEventListener("click", () => { sp.textContent = ""; sp.append(rf, rm); });
    sp.append(yes, no);
  }

  async function removeOrg(name) {
    try {
      const r = await ctx.api(`/api/orgs/${enc(name)}`, { method: "DELETE" });
      ctx.toast(`${name} 제거됨 — ${r.note || ""}`);
      await refreshAll();
    } catch (e) { fail(e); }
  }

  async function rescanOrg(name, btn) {
    btn.classList.add("busy");
    try {
      await ctx.api(`/api/plugins?org=${enc(name)}`); // 재스캔
      ctx.toast(`${name} 재스캔 완료`);
      await refreshData();
    } catch (e) {
      fail(e);
      btn.classList.remove("busy");
    }
  }

  // ── preset 섹션 (§6.5·§12.2) ──
  function renderPresets() {
    const box = $("presetList");
    box.textContent = "";
    const board = el("div", "menu-board"); // 메뉴판 (dashed 보드, §12.2)
    box.appendChild(board);
    if (!presets.length) {
      board.appendChild(el("div", "empty", "아직 preset이 없습니다"));
      return;
    }
    presets.forEach((ps) => {
      const row = el("div", "preset");
      const [cls, label] = BADGE[ps.badge] || ["off", ps.badge];
      row.appendChild(el("span", "pd " + cls));
      row.appendChild(el("span", "nm", ps.name));
      row.appendChild(el("span", "lead")); // 메뉴판 dotted leader
      row.appendChild(el("span", "n", `${ps.members.length}개 · ${label}`));
      const apply = textBtn("전환", "btn sm needs-auth" + (ps.badge === "all-on" ? " primary" : ""));
      apply.addEventListener("click", () => presetBatch(ps.name, "apply"));
      const menu = textBtn("⋯", "btn ghost sm needs-auth");
      menu.addEventListener("click", (e) => { e.stopPropagation(); openPresetMenu(row, ps); });
      row.append(apply, menu);
      board.appendChild(row);
    });
  }

  function openPresetMenu(row, ps) {
    closePop();
    const pop = el("div", "pop");
    const item = (label, fn, danger) => {
      const b = textBtn(label, danger ? "danger" : "");
      b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
      pop.appendChild(b);
    };
    item("멤버 편집…", () => renderMemberEdit(pop, ps.name));
    pop.appendChild(el("div", "sep"));
    item("일괄 설치", () => { closePop(); presetBatch(ps.name, "install"); });
    item("일괄 켜기", () => { closePop(); presetBatch(ps.name, "enable"); });
    item("일괄 끄기", () => { closePop(); presetBatch(ps.name, "disable"); });
    item("일괄 삭제…", () => { // 파괴적 — 확인 단계 (§6.5)
      pop.textContent = "";
      pop.appendChild(el("div", "pop-q", `멤버 ${ps.members.length}개를 모두 삭제할까요?`));
      const yes = textBtn("삭제", "danger");
      yes.addEventListener("click", (e) => {
        e.stopPropagation(); closePop(); presetBatch(ps.name, "uninstall");
      });
      const no = textBtn("취소", "");
      no.addEventListener("click", (e) => { e.stopPropagation(); closePop(); });
      pop.append(yes, no);
    }, true);
    pop.appendChild(el("div", "sep"));
    item("정의 삭제 (플러그인 무영향)", async () => {
      closePop();
      try {
        await ctx.api(`/api/presets/${enc(ps.name)}`, { method: "DELETE" });
        ctx.toast(`preset '${ps.name}' 정의가 삭제되었습니다`);
        await loadPresets();
        render();
      } catch (e) { fail(e); }
    });
    row.appendChild(pop);
    openPop = pop;
  }

  // ⋯ 메뉴의 멤버 편집 — 카탈로그 전체에서 ✓ 토글, 연속 추가 가능 (§12.2)
  function renderMemberEdit(pop, presetName) {
    onPopClose = render; // 닫힐 때 행 배지·멤버 수 갱신
    pop.textContent = "";
    const ps = presets.find((x) => x.name === presetName);
    if (!ps) { closePop(); return; }
    pop.appendChild(el("div", "pop-h", `'${ps.name}' 멤버 편집 — 클릭해서 넣고 빼기`));
    if (!plugins.length) {
      pop.appendChild(el("div", "pop-empty",
        "카탈로그가 비어 있습니다 — 챗 입력줄의 ☕ 아이콘으로 organization을 등록하면 플러그인이 나타납니다"));
      return;
    }
    const list = el("div", "pop-scroll");
    plugins.forEach((p) => {
      const has = ps.members.includes(p.ref);
      const b = textBtn((has ? "✓ " : "+ ") + p.ref, has ? "sel" : "");
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        try {
          await ctx.api(`/api/presets/${enc(ps.name)}/members`,
            { method: "POST", body: { ref: p.ref, op: has ? "remove" : "add" } });
          await loadPresets();
          renderMemberEdit(pop, presetName); // 팝업 유지한 채 갱신 — 연속 편집
        } catch (ex) { fail(ex); }
      });
      list.appendChild(b);
    });
    pop.appendChild(list);
  }

  // + preset 팝업 — 멤버 추가/제거 토글
  function openPresetPick(row, p) {
    closePop();
    const pop = el("div", "pop");
    if (!presets.length) {
      pop.appendChild(el("div", "pop-empty", "preset이 없습니다 — [+ 새 preset]으로 먼저 만드세요"));
    }
    presets.forEach((ps) => {
      const has = ps.members.includes(p.ref);
      const b = textBtn((has ? "✓ " : "+ ") + ps.name, "");
      b.addEventListener("click", async (e) => {
        e.stopPropagation();
        closePop();
        try {
          await ctx.api(`/api/presets/${enc(ps.name)}/members`,
            { method: "POST", body: { ref: p.ref, op: has ? "remove" : "add" } });
          ctx.toast(`${ps.name}에서 ${p.ref} ${has ? "제거" : "추가"}됨`);
          await loadPresets();
          render();
        } catch (ex) { fail(ex); }
      });
      pop.appendChild(b);
    });
    row.appendChild(pop);
    openPop = pop;
  }

  // 일괄 액션 — 멤버별 성공/실패 요약 토스트 (§6.5)
  async function presetBatch(name, action) {
    try {
      const r = await ctx.api(`/api/presets/${enc(name)}/${action}`, { method: "POST" });
      const failures = r.results.filter((x) => !x.ok);
      const okCount = r.results.length - failures.length;
      let text = `${name} ${BATCH_LABEL[action]} — 성공 ${okCount} · 실패 ${failures.length}`;
      failures.forEach((f) => { text += `\n✕ ${f.ref}: ${f.detail || f.action}`; });
      if (r.note) text += `\n${r.note}`;
      ctx.toast(text, failures.length ? "err" : "", 8000);
    } catch (e) { fail(e); }
    await refreshData();
  }

  async function createPreset() {
    const input = $("presetNewName");
    const name = input.value.trim();
    if (!name) return;
    try {
      await ctx.api("/api/presets", { method: "POST", body: { name } });
      input.value = "";
      $("presetNewRow").hidden = true;
      ctx.toast(`preset '${name}' 생성됨 — 플러그인 행의 + 아이콘으로 멤버를 추가하세요`);
      await loadPresets();
      render();
    } catch (e) { fail(e); }
  }

  // ── Inspect 요약 (§12.2) ──
  async function loadInspect() {
    const body = $("inspectBody");
    body.textContent = "불러오는 중…";
    try {
      const rows = await ctx.api("/api/inspect");
      body.textContent = "";
      if (!rows.length) {
        body.appendChild(el("div", "ins-row", "설치된 플러그인이 없습니다"));
        return;
      }
      rows.forEach((r) => {
        const issues = r.issues.length ? " — " + r.issues.join(", ") : " — 정상";
        body.appendChild(el("div", "ins-row", `${r.ref} [${r.state}]${issues}`));
      });
    } catch (e) {
      body.textContent = e.status === 401 ? "" : e.message;
    }
  }

  // ── 고정/미고정 (§12.2 요구 4) — localStorage 저장, hover 레일 ──
  function initPin() {
    const app = $("app");
    const sb = $("sb");
    const rail = $("rail");
    const pinBtn = $("pinBtn");
    let pinned = localStorage.getItem("pm.pinned") !== "0";
    let hideTimer = null;
    const apply = () => {
      pinBtn.classList.toggle("on", pinned);
      $("pinTxt").textContent = pinned ? "고정" : "미고정";
      app.classList.toggle("unpinned", !pinned);
      sb.classList.remove("open");
    };
    pinBtn.addEventListener("click", () => {
      pinned = !pinned;
      localStorage.setItem("pm.pinned", pinned ? "1" : "0");
      apply();
    });
    rail.addEventListener("mouseenter", () => { clearTimeout(hideTimer); sb.classList.add("open"); });
    sb.addEventListener("mouseenter", () => clearTimeout(hideTimer));
    sb.addEventListener("mouseleave", () => { // 접힘 지연 ~300ms — 깜빡임 방지
      if (pinned) return;
      hideTimer = setTimeout(() => sb.classList.remove("open"), 300);
    });
    apply();
  }

  // ── 폭 조절 (§12.2) — 오른쪽 가장자리 드래그, localStorage 저장 ──
  function initResize() {
    const sb = $("sb");
    const handle = $("sbResize");
    const DEFAULT_W = 360;
    const MIN_W = 280;
    const maxW = () => Math.min(640, Math.round(window.innerWidth * 0.6));
    const clamp = (w) => Math.min(Math.max(w, MIN_W), maxW());
    let width = parseInt(localStorage.getItem("pm.sbw"), 10) || DEFAULT_W;
    const apply = () => document.documentElement.style
      .setProperty("--sbw", clamp(width) + "px");
    apply();
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault(); // 드래그 중 텍스트 선택 방지
      document.body.classList.add("sb-resizing");
      const left = sb.getBoundingClientRect().left;
      const move = (ev) => { width = clamp(ev.clientX - left); apply(); };
      const up = () => {
        document.removeEventListener("mousemove", move);
        document.removeEventListener("mouseup", up);
        document.body.classList.remove("sb-resizing");
        localStorage.setItem("pm.sbw", String(clamp(width)));
      };
      document.addEventListener("mousemove", move);
      document.addEventListener("mouseup", up);
    });
    handle.addEventListener("dblclick", () => { // 기본 폭 복원
      width = DEFAULT_W;
      apply();
      localStorage.removeItem("pm.sbw");
    });
  }

  // ── 이벤트 결선 ──
  // ── org 추가 팝오버 (§12.2): 아이콘 클릭 ↔ 열기, 바깥 클릭/Esc ↔ 닫기 ──
  function closeOrgPop() {
    $("orgPop").hidden = true;
    $("orgFab").classList.remove("open");
    $("orgUrl").value = "";   // 만들다 만 상태를 남기지 않음 (§12.2)
    $("orgErr").hidden = true;
  }
  $("orgFab").addEventListener("click", () => {
    const pop = $("orgPop");
    pop.hidden = !pop.hidden;
    $("orgFab").classList.toggle("open", !pop.hidden);
    if (!pop.hidden) $("orgUrl").focus();
  });
  document.addEventListener("click", (e) => {
    if (!$("orgPop").hidden && !$("orgFabWrap").contains(e.target)) closeOrgPop();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeOrgPop();
  });

  $("orgAddBtn").addEventListener("click", addOrg);
  $("orgUrl").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing) addOrg();
  });
  $("searchIn").addEventListener("input", (e) => {
    filter.q = e.target.value.trim();
    render();
  });
  function closePresetNew() {
    $("presetNewRow").hidden = true;
    $("presetNewName").value = "";
  }
  $("presetNewBtn").addEventListener("click", () => {
    const row = $("presetNewRow");
    row.hidden = !row.hidden;
    if (!row.hidden) $("presetNewName").focus();
  });
  // 안 만들고 다른 곳을 누르면 입력 행 접힘 — org 팝오버와 동일 규칙 (§12.2)
  document.addEventListener("click", (e) => {
    if ($("presetNewRow").hidden) return;
    if ($("presetNewRow").contains(e.target)) return;
    if ($("presetNewBtn").contains(e.target)) return;
    closePresetNew();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closePresetNew();
  });
  $("presetNewOk").addEventListener("click", createPreset);
  $("presetNewName").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.isComposing) createPreset();
  });
  $("inspectBox").addEventListener("toggle", () => {
    if ($("inspectBox").open) loadInspect();
  });
  initPin();
  initResize();

  return { refreshAll };
}
