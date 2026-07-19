// 진입점 — 세션 부트스트랩·뷰 전환·heartbeat·공통 fetch 래퍼 (§12.5·§12.6).
// 로직은 전부 API(services)에 있고 여기는 fetch·렌더·이벤트만 (§13.2).

import { initSidebar } from "./sidebar.js";
import { initChat } from "./chat.js";
import { initTerm } from "./term.js";
import { initWorkflow } from "./workflow.js";

const $ = (id) => document.getElementById(id);

const TAB_ID = crypto.randomUUID(); // 탭별 세션 ID (§12.5)
const state = { locked: false, id: null, host: null, view: "chat", inMain: false };

class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

// ── 공통 fetch 래퍼 — 401이면 로그인 뷰로 복귀 (§10.2) ──
async function api(path, opts = {}) {
  const init = { method: opts.method || "GET" };
  if (opts.body !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  let data = {};
  try { data = await res.json(); } catch { /* 본문 없는 응답 */ }
  if (res.status === 401) {
    onAuthFail(data.error);
    throw new ApiError(data.error || "로그인이 필요합니다", 401);
  }
  if (!res.ok) throw new ApiError(data.error || `HTTP ${res.status}`, res.status);
  return data;
}

// ── 토스트 ──
function toast(text, kind = "", ms = 4500) {
  const el = document.createElement("div");
  el.className = "toast" + (kind ? " " + kind : "");
  el.textContent = text;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}

// ── heartbeat (§12.5) — 2초 간격, 탭 닫힘은 sendBeacon ──
setInterval(() => {
  fetch("/api/heartbeat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session: TAB_ID }),
  }).catch(() => {});
}, 2000);
window.addEventListener("pagehide", () => {
  navigator.sendBeacon("/api/tab-close", TAB_ID);
});

// ── 미검증 세션 잠금 (§10.2) — org 추가 외 기능 disabled ──
function setLocked(locked) {
  state.locked = locked;
  document.body.classList.toggle("pm-locked", locked);
  $("lockBanner").hidden = !locked;
  $("connDot").classList.toggle("warn", locked);
  chat.setEnabled(!locked);
}

function setConn(host, id) {
  state.host = host;
  if (id) state.id = id;
  $("connHost").textContent = (host || "host 미확정") + " · ";
  $("connId").textContent = state.id || "";
}

// ── 뷰 전환: 로그인 ↔ 메인 ──
function showLogin(prefillId, message) {
  state.inMain = false;
  $("view-main").hidden = true;
  $("view-login").hidden = false;
  if (prefillId) $("loginId").value = prefillId; // 입력 프리필 (§12.6)
  $("loginPwd").value = "";
  const err = $("loginErr");
  err.textContent = message || "";
  err.hidden = !message;
  ($("loginId").value ? $("loginPwd") : $("loginId")).focus();
}

function enterMain(sess) {
  state.inMain = true;
  setConn(sess.host, sess.id);
  setLocked(!!sess.unverified);
  $("view-login").hidden = true;
  $("view-main").hidden = false;
  sidebar.refreshAll();
}

// 401 폴백 — 토큰 무효 등이면 로그인 뷰로 (§12.6)
function onAuthFail(message) {
  if (!state.inMain) return; // 이미 로그인 뷰
  term.reset();
  showLogin(state.id, message || "세션이 만료되었습니다 — 다시 로그인하세요");
}

// org 추가 후 재조회 — 미검증 세션이 검증됐으면 잠금 해제 (§10.2)
async function recheckSession() {
  try {
    const s = await api("/api/session");
    setConn(s.host, s.id);
    if (state.locked && s.logged_in && !s.unverified) {
      setLocked(false);
      toast("검증 완료 — 모든 기능이 활성화되었습니다");
    }
  } catch { /* 401은 래퍼가 처리 */ }
}

// ── 메인 상단: 세그먼트 탭 [Claude|터미널|Workflow] + 액션 버튼 (§12.1) ──
const TABS = {
  chat: {
    btn: "tabChat", view: "view-chat", action: "새 대화",
    hint: "cwd=repo 루트 · pm 명령도 입력 가능 (list·enable·disable·inspect)",
  },
  term: {
    btn: "tabTerm", view: "view-term", action: "새 터미널",
    hint: "진짜 셸 — claude·pm 직접 실행 · exit로 이 세션만 종료",
  },
  flow: {
    btn: "tabFlow", view: "view-flow", action: "기록 지우기",
    hint: "claude 실행 타임라인 — 챗·내장 터미널 세션 모두 자동 수집 (§12.7)",
  },
};

function switchTab(view) {
  state.view = view;
  for (const [key, tab] of Object.entries(TABS)) {
    $(tab.btn).classList.toggle("on", key === view);
    $(tab.view).classList.toggle("on", key === view);
  }
  $("actionTxt").textContent = TABS[view].action;
  $("hintTxt").textContent = TABS[view].hint;
  if (view === "term") term.ensure(); // 첫 진입 시 세션 생성 (§12.4)
  if (view === "flow") flow.ensure(); // 첫 진입 시 스트림 구독 (§12.7)
}

// ── 모듈 조립 (의존성 주입 — 순환 임포트 방지) ──
const ctx = { api, toast, isLocked: () => state.locked, authFail: onAuthFail, recheckSession };
const chat = initChat(ctx);
const term = initTerm(ctx);
const flow = initWorkflow(ctx);
const sidebar = initSidebar(ctx);

for (const [key, tab] of Object.entries(TABS)) {
  $(tab.btn).addEventListener("click", () => switchTab(key));
}
$("actionBtn").addEventListener("click", () => {
  if (state.view === "chat") chat.newChat();
  else if (state.view === "term") term.newTerm();
  else flow.clearAll();
});

// ── 로그인 (§12.6): ID/PWD(PAT) → POST /api/login ──
$("loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const id = $("loginId").value.trim();
  const token = $("loginPwd").value.trim();
  const err = $("loginErr");
  if (!id || !token) {
    err.textContent = "ID와 PAT를 모두 입력하세요";
    err.hidden = false;
    return;
  }
  err.hidden = true;
  $("loginBtn").disabled = true;
  try {
    const r = await api("/api/login", { method: "POST", body: { id, token } });
    if (r.first_save) { // 평문 저장 경고 1회 (§8.4)
      toast("토큰이 data/credentials.json에 평문으로 저장되었습니다 (권한 600) — 최초 1회 안내", "", 8000);
    }
    const s = await api("/api/session");
    enterMain({ id: s.id || id, host: s.host, unverified: s.unverified });
    if (s.unverified) {
      toast("미검증 세션 — 챗 입력줄의 ☕ 아이콘으로 organization을 추가하면 검증됩니다", "", 8000);
    }
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  } finally {
    $("loginBtn").disabled = false;
  }
});

// ── 로그아웃 = 로그인 화면 복귀 — 저장 자격 유지, 새 로그인이 덮어씀 (§12.6) ──
$("logoutBtn").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } catch { /* 무시 */ }
  chat.reset();
  term.reset();
  flow.reset();
  setLocked(false);
  showLogin(state.id, "");
});

// ── 부트스트랩: GET /api/session → 메인 / 로그인 (§12.6) ──
(async function boot() {
  switchTab("chat");
  try {
    const s = await fetch("/api/session").then((r) => r.json());
    if (s.logged_in) enterMain(s);
    else showLogin(s.id || "");
  } catch {
    showLogin("");
  }
})();
