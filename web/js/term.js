// 내장 터미널 (§12.4) — xterm.js(vendor 전역 Terminal/FitAddon) ↔ WS /api/term.
// 연결마다 단기 1회용 토큰을 먼저 발급받는다 (§11).
/* global Terminal, FitAddon */

export function initTerm(ctx) {
  const $ = (id) => document.getElementById(id);
  const host = $("termHost");
  const overlay = $("termOverlay");
  const overlayMsg = $("termOverlayMsg");
  let term = null;
  let fitAddon = null;
  let ws = null;
  let ended = false;
  let lockShown = false; // 잠금 안내 오버레이 여부 — 해제되면 자동 재시도

  function showOverlay(msg) {
    overlayMsg.textContent = msg;
    overlay.hidden = false;
  }

  function sendJson(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function endSession() { // 셸 exit·소켓 닫힘 → "세션 종료 — [새 터미널]" (§12.4)
    if (ended) return;
    ended = true;
    showOverlay("세션 종료");
  }

  function dispose() {
    if (ws) {
      ws.onclose = null;
      ws.onmessage = null;
      try { ws.close(); } catch { /* 무시 */ }
      ws = null;
    }
    if (term) {
      term.dispose();
      term = null;
      fitAddon = null;
    }
    host.textContent = "";
    ended = false;
  }

  async function create() {
    if (ctx.isLocked()) { // 미검증 세션 잠금 (§10.2)
      showOverlay("미검증 세션 — organization 추가로 검증 후 사용할 수 있습니다");
      lockShown = true;
      return;
    }
    lockShown = false;
    let issued;
    try {
      issued = await ctx.api("/api/term/token", { method: "POST" });
    } catch (e) {
      if (e.status !== 401) showOverlay(e.message);
      return;
    }
    dispose();
    overlay.hidden = true;
    term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      scrollback: 5000,
      fontFamily: '"SF Mono", Menlo, Consolas, monospace',
      theme: { // 로스티드 브라운 (§12.1 카페 테마)
        background: "#3a2e26",
        foreground: "#efe3d1",
        cursor: "#e0a866",
        selectionBackground: "rgba(224,168,102,.35)",
      },
    });
    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(host);
    fitAddon.fit();

    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/term?token=${encodeURIComponent(issued.token)}`);
    ws.onopen = () => {
      sendJson({ type: "resize", rows: term.rows, cols: term.cols });
      term.focus();
    };
    ws.onmessage = (e) => {
      const data = e.data;
      if (typeof data === "string" && data.startsWith("{")) {
        try { // 서버 제어 메시지 {"type":"exit"} 판별 — 그 외는 일반 출력
          const msg = JSON.parse(data);
          if (msg && msg.type === "exit") { endSession(); return; }
        } catch { /* 일반 출력 */ }
      }
      if (term) term.write(data);
    };
    ws.onclose = () => endSession();
    term.onData((d) => sendJson({ type: "input", data: d }));
    term.onResize(({ rows, cols }) => sendJson({ type: "resize", rows, cols }));
  }

  // 터미널 탭 진입 — 첫 진입이면 세션 생성, 이후엔 크기 맞춤 (§12.4)
  function ensure() {
    if (!term && (overlay.hidden || (lockShown && !ctx.isLocked()))) {
      create();
      return;
    }
    requestAnimationFrame(() => { if (fitAddon && term) fitAddon.fit(); });
  }

  function newTerm() {
    dispose();
    create();
  }

  function reset() { // 로그아웃·인증 만료 시 정리
    dispose();
    overlay.hidden = true;
    lockShown = false;
  }

  window.addEventListener("resize", () => {
    if (fitAddon && term && $("view-term").classList.contains("on")) fitAddon.fit();
  });
  $("termOverlayBtn").addEventListener("click", newTerm);

  return { ensure, newTerm, reset };
}
