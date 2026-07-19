"""챗 무응답 방지 가드 테스트 (§12.3) — 백엔드 실패가 반드시
error 이벤트로 표면화되는지 (스트림의 조용한 사망 = 무응답 재현 케이스)."""

from __future__ import annotations

import json

from flask import Flask

from pm.api.chat import SubprocessChatBackend, make_chat_bp


def _events(data: str):
    out = []
    for chunk in data.split("\n\n"):
        if chunk.startswith("data: "):
            out.append(json.loads(chunk[6:]))
    return out


def test_subprocess_backend_popen_failure_yields_error():
    """claude 미발견(FileNotFoundError) → 예외 대신 error+done 이벤트."""

    def failing_popen(*args, **kwargs):
        raise FileNotFoundError("claude")

    backend = SubprocessChatBackend("/tmp", popen=failing_popen)
    events = list(backend.stream("hi"))
    assert [e["type"] for e in events] == ["error", "done"]
    assert "claude_bin" in events[0]["text"]  # 수정 안내 포함 (§12.3)


def test_subprocess_backend_uses_resolved_claude_bin():
    captured = {}

    def fake_popen(args, **kwargs):
        captured["argv0"] = args[0]
        raise FileNotFoundError("stop")  # 실행까지는 안 감

    backend = SubprocessChatBackend("/tmp", popen=fake_popen,
                                    claude_bin="/resolved/claude")
    list(backend.stream("hi"))
    assert captured["argv0"] == "/resolved/claude"


def test_sse_guard_surfaces_backend_exception():
    """스트림 도중 예외 → SSE에 error+done이 실려 프론트에 보인다."""

    class BoomBackend:

        def stream(self, message, session_id=None):
            yield {"type": "delta", "text": "부분"}
            raise RuntimeError("백엔드 폭발")

    app = Flask(__name__)
    app.register_blueprint(make_chat_bp(container=None,
                                        backend=BoomBackend()),
                           url_prefix="/api")
    client = app.test_client()
    res = client.post("/api/chat", json={"message": "hi"})
    events = _events(res.get_data(as_text=True))
    types = [e["type"] for e in events]
    assert types == ["delta", "error", "done"]
    assert "백엔드 폭발" in events[1]["text"]
