"""WorkflowStore·workflow API 계약 테스트 (§12.7, M9)."""

from __future__ import annotations

from pm.api.workflow import (MAX_STEPS_PER_SESSION, WorkflowStore, sse_line)


class Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def ev(name: str, sid: str = "s1", **extra) -> dict:
    return dict({"hook_event_name": name, "session_id": sid}, **extra)


def make_store(**kwargs) -> WorkflowStore:
    return WorkflowStore(clock=Clock(), **kwargs)


# ── 짝맞추기·상태 도출 ───────────────────────────────────────
def test_pre_post_pairing_lifo():
    store = make_store()
    store.ingest(ev("PreToolUse", tool_name="Bash",
                    tool_input={"command": "sleep 1"}))
    store.ingest(ev("PreToolUse", tool_name="Bash",
                    tool_input={"command": "echo 둘째"}))
    store.ingest(ev("PostToolUse", tool_name="Bash", tool_input={}))
    steps = store.snapshot()[0]["steps"]
    assert steps[0]["status"] == "running"  # 먼저 시작한 것은 아직
    assert steps[1]["status"] == "done"  # LIFO — 최근 것 먼저 마감
    assert steps[1]["summary"] == "echo 둘째"


def test_post_without_pre_creates_completed_step():
    """서버 재시작 내성 — Post만 와도 완료 step 즉석 생성 (§12.7)."""
    store = make_store()
    store.ingest(ev("PostToolUse", tool_name="Read",
                    tool_input={"file_path": "a.py"}))
    steps = store.snapshot()[0]["steps"]
    assert steps == [dict(steps[0], status="done", summary="a.py")]


def test_failure_marks_failed():
    store = make_store()
    store.ingest(ev("PreToolUse", tool_name="Bash",
                    tool_input={"command": "false"}))
    store.ingest(ev("PostToolUseFailure", tool_name="Bash", tool_input={}))
    assert store.snapshot()[0]["steps"][0]["status"] == "failed"


def test_subagent_depth_and_stop():
    store = make_store()
    store.ingest(ev("SubagentStart", agent_type="reviewer", agent_id="a1"))
    store.ingest(ev("PreToolUse", tool_name="Grep",
                    tool_input={"pattern": "TODO"}))
    store.ingest(ev("PostToolUse", tool_name="Grep", tool_input={}))
    store.ingest(ev("SubagentStop", agent_id="a1"))
    steps = store.snapshot()[0]["steps"]
    assert steps[0]["kind"] == "subagent" and steps[0]["depth"] == 0
    assert steps[0]["status"] == "done"
    assert steps[1]["depth"] == 1  # 서브에이전트 구간의 도구는 들여쓰기


def test_stop_finishes_running_and_idles_session():
    store = make_store()
    store.ingest(ev("PreToolUse", tool_name="Bash",
                    tool_input={"command": "x"}))
    store.ingest(ev("Stop"))
    session = store.snapshot()[0]
    assert session["state"] == "idle"
    assert session["steps"][0]["status"] == "done"  # 일괄 마감 (버전 내성)


def test_session_start_and_prompt_and_plugin_badge():
    store = make_store()
    store.ingest(ev("SessionStart", source="startup", model="m1"))
    store.ingest(ev("UserPromptSubmit", prompt="코드리뷰 해줘"))
    store.ingest(ev("PreToolUse", tool_name="mcp__plugin_foo_db__query",
                    tool_input={"query": "select 1"}))
    session = store.snapshot()[0]
    assert session["source"] == "startup" and session["model"] == "m1"
    assert session["steps"][0]["kind"] == "prompt"
    tool = session["steps"][1]
    assert tool["is_plugin"] is True and tool["plugin"] == "foo"


def test_unknown_event_and_missing_fields_ignored():
    store = make_store()
    store.ingest({"hook_event_name": "미래이벤트", "session_id": "s1"})
    store.ingest({"hook_event_name": "PreToolUse"})  # session_id 없음
    store.ingest({})  # 전부 없음
    snap = store.snapshot()
    assert len(snap) == 1  # 자동 생성 세션 하나 (unknown-session)
    assert snap[0]["steps"][0]["status"] == "running"


# ── 링버퍼 ───────────────────────────────────────────────────
def test_session_ring_buffer_evicts_inactive_first():
    store = make_store(max_sessions=2)
    store.ingest(ev("SessionStart", sid="old"))
    store.ingest(ev("SessionEnd", sid="old"))  # ended
    store.ingest(ev("SessionStart", sid="live"))
    store.ingest(ev("SessionStart", sid="new"))  # 3번째 → old 제거
    ids = {s["session_id"] for s in store.snapshot()}
    assert ids == {"live", "new"}


def test_step_trim_drops_oldest_completed():
    store = make_store()
    for i in range(MAX_STEPS_PER_SESSION + 10):
        store.ingest(ev("PreToolUse", tool_name="Read",
                        tool_input={"file_path": f"f{i}"}))
        store.ingest(ev("PostToolUse", tool_name="Read", tool_input={}))
    steps = store.snapshot()[0]["steps"]
    assert len(steps) <= MAX_STEPS_PER_SESSION
    # 앞쪽(오래된 완료분)이 절삭되고 최신 step은 남는다
    assert steps[-1]["summary"] == f"f{MAX_STEPS_PER_SESSION + 9}"
    assert steps[0]["summary"] != "f0"


# ── 팬아웃·배압 ──────────────────────────────────────────────
def test_fanout_to_multiple_subscribers():
    store = make_store()
    q1, q2 = store.subscribe(), store.subscribe()
    store.ingest(ev("PreToolUse", tool_name="Bash",
                    tool_input={"command": "x"}))
    # 신규 세션 알림(session) → step 순으로 두 구독자 모두 수신
    assert q1.get_nowait()["type"] == "session" == q2.get_nowait()["type"]
    e1, e2 = q1.get_nowait(), q2.get_nowait()
    assert e1["type"] == "step" == e2["type"]
    assert e1["step"]["status"] == "running"


def test_slow_subscriber_is_dropped_alone():
    store = make_store()
    slow, fast = store.subscribe(), store.subscribe()
    # slow 큐를 인위로 가득 채움
    while not slow.full():
        slow.put_nowait({"type": "filler"})
    store.ingest(ev("PreToolUse", tool_name="Bash",
                    tool_input={"command": "x"}))
    assert fast.get_nowait()["type"] == "session"  # 세션 알림
    assert fast.get_nowait()["type"] == "step"  # 빠른 쪽은 정상 수신
    # slow는 구독 해제됨 — 다음 이벤트를 받지 않는다
    store.ingest(ev("PostToolUse", tool_name="Bash", tool_input={}))
    assert fast.get_nowait()["type"] == "step"
    assert slow.qsize() == slow.maxsize  # filler 그대로 (신규 유입 없음)


def test_clear_broadcasts():
    store = make_store()
    store.ingest(ev("PreToolUse", tool_name="Bash",
                    tool_input={"command": "x"}))
    q = store.subscribe()
    store.clear()
    assert store.snapshot() == []
    assert q.get_nowait() == {"type": "clear"}


def test_sse_line_format():
    line = sse_line({"type": "clear"})
    assert line == 'data: {"type": "clear"}\n\n'  # chat.js 파서와 동일 포맷


# ── API 계약 (app.test_client + fake container) ──────────────
def test_events_endpoint_contract(client):
    res = client.post("/api/workflow/events",
                      json=ev("PreToolUse", tool_name="Bash",
                              tool_input={"command": "git status"}))
    assert res.status_code == 202
    assert client.post("/api/workflow/events",
                       data="문자열", content_type="text/plain"
                       ).status_code == 400
    assert client.post("/api/workflow/events",
                       json={"hook_event_name": "PreToolUse"}
                       ).status_code == 202  # 필드 누락 내성

    body = client.get("/api/workflow/sessions").get_json()
    by_id = {s["session_id"]: s for s in body["sessions"]}
    assert by_id["s1"]["steps"][0]["summary"] == "git status"
    assert "unknown-session" in by_id  # session_id 누락분의 자동 세션

    assert client.delete("/api/workflow").status_code == 200
    assert client.get("/api/workflow/sessions").get_json() == {
        "sessions": []}


def test_sessions_sorted_latest_first(client, app):
    store = app.extensions["pm"]["workflow_store"]
    store.ingest(ev("SessionStart", sid="first"))
    store.ingest(ev("SessionStart", sid="second"))
    sessions = client.get("/api/workflow/sessions").get_json()["sessions"]
    assert [s["session_id"] for s in sessions][0] == "second"
