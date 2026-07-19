"""claude 챗 API (§12.3) — POST /chat, SSE 스트리밍.

- 백엔드: Python ≥3.10 + claude-agent-sdk → SDK / 그 외 → `claude -p
  --output-format stream-json` subprocess 폴백. 어느 쪽이든 local
  `.claude` 설정·활성 플러그인이 적용된다(cwd=ROOT, setting_sources).
- `pm` 가로채기: `^pm\\s` + allowlist(list·enable·disable·inspect)만
  services 직접 호출(cli 재사용) — 맨 앞 공백은 이스케이프(§12.3).
"""

from __future__ import annotations

import contextlib
import io
import json
import queue
import re
import subprocess
import sys
import threading
from typing import Any, Callable, Dict, Iterator, List, Optional

from flask import Blueprint, Response, jsonify, request

PM_PATTERN = re.compile(r"^pm\s")
PM_ALLOWLIST = ("list", "enable", "disable", "inspect")


def try_intercept(container: Any, message: str) -> Optional[str]:
    """§12.3 가로채기 — 처리했으면 출력 텍스트, 아니면 None(claude로)."""
    if not PM_PATTERN.match(message):  # 앞 공백 = 이스케이프 (매치 안 됨)
        return None
    args = message.split()[1:]
    if not args or args[0] not in PM_ALLOWLIST:
        return None
    from pm import cli  # 지연 임포트 — 순환 방지
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main(args, container=container)
    text = out.getvalue().rstrip()
    if code != 0:
        text += f"\n(종료코드 {code})"
    return text


class SubprocessChatBackend:
    """`claude -p` stream-json 폴백 (3.8·3.9 또는 SDK 부재 §12.3)."""

    def __init__(self, root: str,
                 popen: Callable[..., Any] = subprocess.Popen,
                 claude_bin: Optional[str] = None) -> None:
        self._root = root
        self._popen = popen
        self._claude_bin = claude_bin or "claude"

    def stream(self, message: str,
               session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        args = [self._claude_bin, "-p", message,
                "--output-format", "stream-json", "--verbose"]
        if session_id:
            args += ["--resume", session_id]
        try:
            proc = self._popen(args, cwd=self._root, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
        except OSError as exc:
            # claude 미발견/실행 불가 — 스트림이 조용히 죽지 않게 명시 오류
            yield {"type": "error",
                   "text": f"claude 실행 실패: {exc} — config.json에 "
                           "claude_bin을 지정하세요 (§12.3)"}
            yield {"type": "done", "session_id": None}
            return
        result_session: Optional[str] = None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "assistant":
                content = (event.get("message") or {}).get("content", [])
                for block in content:
                    if block.get("type") == "text" and block.get("text"):
                        yield {"type": "delta", "text": block["text"]}
            elif event.get("type") == "result":
                result_session = event.get("session_id")
        proc.wait()
        if proc.returncode != 0:
            stderr = proc.stderr.read() if proc.stderr else ""
            yield {"type": "error",
                   "text": f"claude 종료코드 {proc.returncode}: "
                           f"{stderr.strip()[:500]}"}
        yield {"type": "done", "session_id": result_session}


class SdkChatBackend:
    """Claude Agent SDK 백엔드 (Python ≥3.10, §12.3) —
    setting_sources로 local `.claude` 설정·skills·플러그인 로딩."""

    def __init__(self, root: str) -> None:
        self._root = root

    def stream(self, message: str,
               session_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        import asyncio
        from claude_agent_sdk import (  # pylint: disable=import-error
            ClaudeAgentOptions, query)

        events: "queue.Queue[Optional[Dict[str, Any]]]" = queue.Queue()
        options = ClaudeAgentOptions(
            cwd=self._root,
            setting_sources=["project", "local"],
            resume=session_id,
        )

        def _extract_text(msg: Any) -> List[str]:
            texts = []
            for block in getattr(msg, "content", None) or []:
                text = getattr(block, "text", None)
                if text:
                    texts.append(text)
            return texts

        async def _pump() -> None:
            found_session = None
            async for msg in query(prompt=message, options=options):
                kind = type(msg).__name__
                if kind == "AssistantMessage":
                    for text in _extract_text(msg):
                        events.put({"type": "delta", "text": text})
                elif kind == "ResultMessage":
                    found_session = getattr(msg, "session_id", None)
            events.put({"type": "done", "session_id": found_session})

        def _run() -> None:
            try:
                asyncio.run(_pump())
            except Exception as exc:  # pylint: disable=broad-exception-caught
                events.put({"type": "error", "text": str(exc)})
                events.put({"type": "done", "session_id": None})
            finally:
                events.put(None)  # sentinel

        threading.Thread(target=_run, daemon=True,
                         name="pm-chat-sdk").start()
        while True:
            event = events.get()
            if event is None:
                return
            yield event


def build_chat_backend(root: str, claude_bin: Optional[str] = None) -> Any:
    """버전 게이트(§12.3): 3.10+에서 SDK 시도, 아니면 subprocess 폴백."""
    if sys.version_info >= (3, 10):
        try:
            import claude_agent_sdk  # noqa: F401  pylint: disable=unused-import
            return SdkChatBackend(root)
        except ImportError:
            pass
    return SubprocessChatBackend(root, claude_bin=claude_bin)


def make_chat_bp(container: Any, backend: Any) -> Blueprint:
    bp = Blueprint("chat", __name__)

    def _sse(events: Iterator[Dict[str, Any]]) -> Iterator[str]:
        try:
            for event in events:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # 백엔드 예외로 스트림이 무응답으로 죽는 것 방지 (§12.3)
            for event in ({"type": "error", "text": f"챗 백엔드 오류: {exc}"},
                          {"type": "done", "session_id": None}):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    @bp.post("/chat")
    def chat():
        body = request.get_json(silent=True) or {}
        message = str(body.get("message", ""))
        if not message.strip():
            return jsonify({"error": "message가 필요합니다"}), 400
        intercepted = try_intercept(container, message)
        if intercepted is not None:
            events: Iterator[Dict[str, Any]] = iter([
                {"type": "pm-result", "text": intercepted},
                {"type": "done", "session_id": body.get("session_id")},
            ])
        else:
            events = backend.stream(message, body.get("session_id") or None)
        return Response(_sse(events), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache",
                                 "X-Accel-Buffering": "no"})

    return bp
