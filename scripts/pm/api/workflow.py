"""Workflow 타임라인 (§12.7) — hooks 이벤트 수집·상태 도출·SSE 팬아웃.

claude 세션(챗 SDK·터미널 대화형)의 hooks가 `POST /api/workflow/events`로
쏘는 JSON을 받아, 세션별 step 타임라인(진행중/완료/실패·서브에이전트
depth)을 **메모리 링버퍼에만** 유지하고 SSE로 구독자에게 중계한다.
저장 상태를 두지 않는 §6.4 원칙과 동일 — 서버 종료 시 소멸.
"""

from __future__ import annotations

import dataclasses
import json
import queue
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Mapping, Optional

from flask import Blueprint, Response, jsonify, request

MAX_SESSIONS = 20
MAX_STEPS_PER_SESSION = 500
SUBSCRIBER_QUEUE_LIMIT = 1000
KEEPALIVE_SECONDS = 15.0

# 도구별 요약 규칙 (§12.7 — 요약은 서버가 생성, 프론트는 렌더만)
_SUMMARY_KEYS = {
    "Bash": "command",
    "Read": "file_path",
    "Write": "file_path",
    "Edit": "file_path",
    "Grep": "pattern",
    "Glob": "pattern",
    "WebFetch": "url",
}
_SUMMARY_MAX = 60


def _summarize(tool_name: str, tool_input: Mapping[str, Any]) -> str:
    """tool_input에서 사람이 알아볼 한 줄을 뽑는다."""
    if tool_name == "Task":
        parts = [str(tool_input.get("subagent_type", "")),
                 str(tool_input.get("description", ""))[:40]]
        return " · ".join(p for p in parts if p) or "subagent"
    key = _SUMMARY_KEYS.get(tool_name)
    if key and tool_input.get(key):
        return str(tool_input[key])[:_SUMMARY_MAX]
    for value in tool_input.values():  # 첫 문자열 값 (MCP 등 미지 도구)
        if isinstance(value, str) and value.strip():
            return value[:_SUMMARY_MAX]
    return ", ".join(list(tool_input)[:4])


def _plugin_of(tool_name: str) -> Optional[str]:
    """`mcp__plugin_{name}_…` 네임스페이스에서 플러그인명 추출 (§12.7)."""
    if not tool_name.startswith("mcp__plugin_"):
        return None
    rest = tool_name[len("mcp__plugin_"):]
    return rest.split("_", 1)[0] or None


@dataclasses.dataclass
class _Step:
    step_id: int
    kind: str  # prompt | tool | subagent
    status: str  # running | done | failed
    summary: str
    depth: int
    started_at: float
    ended_at: Optional[float] = None
    tool_name: Optional[str] = None
    agent_type: Optional[str] = None
    agent_id: Optional[str] = None
    is_plugin: bool = False
    plugin: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        data.pop("agent_id")  # 내부 매칭용
        return data


class _Session:
    """세션 하나의 step 목록 + 짝맞추기/depth 상태 (§12.7)."""

    def __init__(self, session_id: str, now: float) -> None:
        self.session_id = session_id
        self.source = "unknown"
        self.model: Optional[str] = None
        self.state = "active"  # active | idle | ended
        self.started_at = now
        self.last_event_at = now
        self.steps: List[_Step] = []
        self._next_id = 1
        # tool_name → running step_id 스택 (LIFO 짝맞추기)
        self._running: Dict[str, List[int]] = {}
        self._agents: List[str] = []  # 활성 서브에이전트 agent_id 스택

    def meta(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "short_id": self.session_id[:8],
            "state": self.state,
            "source": self.source,
            "model": self.model,
            "started_at": self.started_at,
            "last_event_at": self.last_event_at,
            "step_count": len(self.steps),
        }

    def add_step(self, **kwargs: Any) -> _Step:
        step = _Step(step_id=self._next_id, depth=len(self._agents),
                     **kwargs)
        self._next_id += 1
        self.steps.append(step)
        self._trim()
        return step

    def _trim(self) -> None:
        """step 상한 초과 시 앞쪽 완료분부터 절삭 (§12.7 링버퍼)."""
        excess = len(self.steps) - MAX_STEPS_PER_SESSION
        if excess <= 0:
            return
        kept = [s for s in self.steps if s.status == "running"]
        done = [s for s in self.steps if s.status != "running"]
        self.steps = done[excess:] + kept
        self.steps.sort(key=lambda s: s.step_id)

    def find_step(self, step_id: int) -> Optional[_Step]:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None


class WorkflowStore:
    """스레드 세이프 수집기 — ingest는 hooks, 조회·SSE는 웹 (§12.7).

    Args:
        clock: epoch 초 시계 (테스트 주입).
        max_sessions: 세션 링버퍼 상한.
    """

    def __init__(self, clock: Callable[[], float] = time.time,
                 max_sessions: int = MAX_SESSIONS) -> None:
        self._clock = clock
        self._max_sessions = max_sessions
        self._sessions: "OrderedDict[str, _Session]" = OrderedDict()
        self._subs: List["queue.Queue[Optional[Dict[str, Any]]]"] = []
        self._lock = threading.Lock()

    # ── 구독 (SSE 팬아웃) ────────────────────────────────────
    def subscribe(self) -> "queue.Queue[Optional[Dict[str, Any]]]":
        q: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue(
            maxsize=SUBSCRIBER_QUEUE_LIMIT)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q: "queue.Queue[Optional[Dict[str, Any]]]") -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def _publish(self, event: Dict[str, Any]) -> None:
        """느린 구독자는 끊는다 — 큐가 차면 종료 센티널 후 구독 해제."""
        for q in list(self._subs):
            try:
                q.put_nowait(event)
            except queue.Full:
                self._subs.remove(q)
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass

    # ── 수집 ─────────────────────────────────────────────────
    def ingest(self, payload: Mapping[str, Any]) -> None:
        """hook JSON 하나 처리 — 미지 이벤트·필드 누락은 조용히 무시."""
        event_name = str(payload.get("hook_event_name", ""))
        session_id = str(payload.get("session_id") or "unknown-session")
        handler = self._HANDLERS.get(event_name)
        if handler is None:
            return
        with self._lock:
            now = self._clock()
            session, created = self._get_session(session_id, now)
            session.last_event_at = now
            if session.state != "active" and event_name not in (
                    "Stop", "SessionEnd"):
                session.state = "active"
            if created:
                self._publish({"type": "session", "session": session.meta()})
            handler(self, session, payload, now)

    def _get_session(self, session_id: str, now: float):
        if session_id in self._sessions:
            return self._sessions[session_id], False
        session = _Session(session_id, now)
        self._sessions[session_id] = session
        # 링버퍼: 오래된 비활성 우선 제거, 없으면 최고령 제거
        while len(self._sessions) > self._max_sessions:
            victim = next(
                (sid for sid, s in self._sessions.items()
                 if s.state != "active"),
                next(iter(self._sessions)))
            del self._sessions[victim]
        return session, True

    def _emit_step(self, session: _Session, step: _Step) -> None:
        self._publish({"type": "step", "session_id": session.session_id,
                       "session": session.meta(), "step": step.to_dict()})

    # ── 이벤트 핸들러 (§12.7 상태 도출 규칙) ─────────────────
    def _on_session_start(self, session: _Session,
                          payload: Mapping[str, Any], now: float) -> None:
        del now
        session.source = str(payload.get("source") or session.source)
        session.model = payload.get("model") or session.model
        session.state = "active"
        self._publish({"type": "session", "session": session.meta()})

    def _on_prompt(self, session: _Session, payload: Mapping[str, Any],
                   now: float) -> None:
        text = str(payload.get("prompt") or "(프롬프트)")
        step = session.add_step(kind="prompt", status="done",
                                summary=text[:80], started_at=now,
                                ended_at=now)
        self._emit_step(session, step)

    def _on_pre_tool(self, session: _Session, payload: Mapping[str, Any],
                     now: float) -> None:
        tool_name = str(payload.get("tool_name") or "tool")
        tool_input = payload.get("tool_input")
        tool_input = tool_input if isinstance(tool_input, Mapping) else {}
        step = session.add_step(
            kind="tool", status="running", tool_name=tool_name,
            summary=_summarize(tool_name, tool_input), started_at=now,
            is_plugin=tool_name.startswith("mcp__"),
            plugin=_plugin_of(tool_name))
        session._running.setdefault(tool_name, []).append(step.step_id)  # pylint: disable=protected-access
        self._emit_step(session, step)

    def _close_tool(self, session: _Session, payload: Mapping[str, Any],
                    now: float, status: str) -> None:
        """Post(Failure) — 같은 tool_name의 최근 running step을 마감(LIFO).
        짝이 없으면(서버 재시작 등) 완료 step을 즉석 생성 (§12.7)."""
        tool_name = str(payload.get("tool_name") or "tool")
        stack = session._running.get(tool_name)  # pylint: disable=protected-access
        step = session.find_step(stack.pop()) if stack else None
        if step is None:
            tool_input = payload.get("tool_input")
            tool_input = tool_input if isinstance(tool_input, Mapping) else {}
            step = session.add_step(
                kind="tool", status=status, tool_name=tool_name,
                summary=_summarize(tool_name, tool_input), started_at=now,
                ended_at=now, is_plugin=tool_name.startswith("mcp__"),
                plugin=_plugin_of(tool_name))
        else:
            step.status = status
            step.ended_at = now
        self._emit_step(session, step)

    def _on_post_tool(self, session: _Session, payload: Mapping[str, Any],
                      now: float) -> None:
        self._close_tool(session, payload, now, "done")

    def _on_post_tool_failure(self, session: _Session,
                              payload: Mapping[str, Any],
                              now: float) -> None:
        self._close_tool(session, payload, now, "failed")

    def _on_subagent_start(self, session: _Session,
                           payload: Mapping[str, Any], now: float) -> None:
        agent_type = str(payload.get("agent_type") or "subagent")
        agent_id = str(payload.get("agent_id") or f"agent-{now}")
        step = session.add_step(kind="subagent", status="running",
                                summary=agent_type, agent_type=agent_type,
                                agent_id=agent_id, started_at=now)
        session._agents.append(agent_id)  # pylint: disable=protected-access
        self._emit_step(session, step)

    def _on_subagent_stop(self, session: _Session,
                          payload: Mapping[str, Any], now: float) -> None:
        agent_id = str(payload.get("agent_id") or "")
        agents = session._agents  # pylint: disable=protected-access
        if agent_id in agents:
            agents.remove(agent_id)
        elif agents:
            agents.pop()
        for step in reversed(session.steps):
            if step.kind == "subagent" and step.status == "running" and (
                    not agent_id or step.agent_id == agent_id):
                step.status = "done"
                step.ended_at = now
                self._emit_step(session, step)
                return

    def _finish_all(self, session: _Session, now: float,
                    state: str) -> None:
        """Stop/SessionEnd — 잔여 running 일괄 마감 (§12.7 버전 내성)."""
        for step in session.steps:
            if step.status == "running":
                step.status = "done"
                step.ended_at = now
                self._emit_step(session, step)
        session._running.clear()  # pylint: disable=protected-access
        session._agents.clear()  # pylint: disable=protected-access
        session.state = state
        self._publish({"type": "session", "session": session.meta()})

    def _on_stop(self, session: _Session, payload: Mapping[str, Any],
                 now: float) -> None:
        del payload
        self._finish_all(session, now, "idle")

    def _on_session_end(self, session: _Session,
                        payload: Mapping[str, Any], now: float) -> None:
        del payload
        self._finish_all(session, now, "ended")

    _HANDLERS: Dict[str, Callable[..., None]] = {
        "SessionStart": _on_session_start,
        "UserPromptSubmit": _on_prompt,
        "PreToolUse": _on_pre_tool,
        "PostToolUse": _on_post_tool,
        "PostToolUseFailure": _on_post_tool_failure,
        "SubagentStart": _on_subagent_start,
        "SubagentStop": _on_subagent_stop,
        "Stop": _on_stop,
        "SessionEnd": _on_session_end,
    }

    # ── 조회·정리 ────────────────────────────────────────────
    def snapshot(self) -> List[Dict[str, Any]]:
        """전 세션(최신 활동순) + step 목록 — 탭 진입 스냅샷용."""
        with self._lock:
            sessions = sorted(self._sessions.values(),
                              key=lambda s: s.last_event_at, reverse=True)
            return [dict(s.meta(), steps=[st.to_dict() for st in s.steps])
                    for s in sessions]

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._publish({"type": "clear"})


def sse_line(event: Mapping[str, Any]) -> str:
    """SSE 직렬화 — chat.py와 동일한 `data: {json}\\n\\n` 포맷 (§12.7)."""
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def make_workflow_bp(store: WorkflowStore) -> Blueprint:
    """무인증 로컬 계측 채널 (§11 표 근거 — 127.0.0.1 전용)."""
    bp = Blueprint("workflow", __name__)

    @bp.post("/workflow/events")
    def events():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "JSON 객체가 필요합니다"}), 400
        store.ingest(payload)
        return "", 202

    @bp.get("/workflow/sessions")
    def sessions():
        return jsonify({"sessions": store.snapshot()})

    @bp.get("/workflow/stream")
    def stream():
        def generate():
            q = store.subscribe()
            try:
                while True:
                    try:
                        event = q.get(timeout=KEEPALIVE_SECONDS)
                    except queue.Empty:
                        yield ": ping\n\n"  # keepalive — 죽은 연결 감지
                        continue
                    if event is None:  # overflow 종료 센티널 (§12.7 배압)
                        return
                    yield sse_line(event)
            finally:
                store.unsubscribe(q)

        return Response(generate(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

    @bp.delete("/workflow")
    def clear():
        store.clear()
        return jsonify({"ok": True})

    return bp
