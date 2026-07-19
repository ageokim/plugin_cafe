// Claude 챗 (§12.3) — POST /api/chat는 SSE 형식 스트림이지만 POST라
// EventSource 불가 → fetch + ReadableStream reader로 "data: {json}\n\n" 파싱.

export function initChat(ctx) {
  const $ = (id) => document.getElementById(id);
  const msgs = $("msgs");
  const input = $("chatIn");
  const sendBtn = $("sendBtn");
  let sessionId = null; // done 이벤트로 갱신 → 다음 요청에 전달 (§12.3)
  let streaming = false;

  function addMsg(cls, text) {
    const div = document.createElement("div");
    div.className = "msg " + cls;
    if (text !== undefined) div.textContent = text;
    msgs.appendChild(div);
    msgs.scrollTop = msgs.scrollHeight;
    return div;
  }

  async function send() {
    const text = input.value.trim();
    if (!text || streaming || ctx.isLocked()) return;
    input.value = "";
    addMsg("user", text);
    streaming = true;
    sendBtn.disabled = true;
    let claudeEl = null;

    const onEvent = (ev) => {
      if (ev.type === "delta") { // 텍스트 누적 렌더
        if (!claudeEl) claudeEl = addMsg("claude", "");
        claudeEl.textContent += ev.text || "";
      } else if (ev.type === "pm-result") { // pm 가로채기 — 코드 블록 말풍선
        const box = addMsg("claude");
        const pre = document.createElement("pre");
        pre.textContent = ev.text || "";
        box.appendChild(pre);
      } else if (ev.type === "error") {
        addMsg("claude err", ev.text || "오류");
      } else if (ev.type === "done") {
        if (ev.session_id) sessionId = ev.session_id;
      }
      msgs.scrollTop = msgs.scrollHeight;
    };

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, session_id: sessionId }),
      });
      if (res.status === 401) { ctx.authFail(); return; }
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        addMsg("claude err", data.error || `HTTP ${res.status}`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf("\n\n")) >= 0) { // 이벤트 경계
          const chunk = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          for (const line of chunk.split("\n")) {
            if (!line.startsWith("data: ")) continue;
            try { onEvent(JSON.parse(line.slice(6))); } catch { /* 조각 무시 */ }
          }
        }
      }
    } catch (e) {
      addMsg("claude err", "연결 오류: " + e.message);
    } finally {
      streaming = false;
      sendBtn.disabled = ctx.isLocked();
      input.focus();
    }
  }

  // [새 대화] — session_id 폐기, 플러그인은 새 세션부터 적용 (§12.3)
  function newChat() {
    sessionId = null;
    msgs.textContent = "";
    addMsg("sys", "새 대화 — 활성화된 플러그인이 이 세션부터 적용됩니다");
  }

  function setEnabled(on) { // 미검증 세션 잠금 (§10.2)
    input.disabled = !on;
    sendBtn.disabled = !on;
    input.placeholder = on
      ? "claude에게 메시지… (pm 명령도 입력 가능)"
      : "미검증 세션 — organization 추가 후 사용할 수 있습니다";
  }

  function reset() { // 로그아웃 시
    sessionId = null;
    msgs.textContent = "";
  }

  sendBtn.addEventListener("click", send);
  input.addEventListener("keydown", (e) => { // 한글 IME 조합 중 Enter 무시
    if (e.key === "Enter" && !e.isComposing) send();
  });

  return { newChat, setEnabled, reset };
}
