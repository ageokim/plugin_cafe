"""터미널 WS API (§12.4·§11) — 토큰 발급 + xterm.js ↔ pty 중계.

내장 터미널은 임의 명령 실행 통로다 — localhost 바인딩에 더해
**WS 연결마다 단기(≈30초)·1회용 토큰**을 검증한다(§11). 토큰은
인증된 세션에만 발급되고 첫 사용 시 무효화된다.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Any, Callable, Dict

from flask import Blueprint, jsonify, request

TOKEN_TTL = 30.0


class TokenStore:
    """발급-소비 1회용 토큰 (테스트 주입용 clock)."""

    def __init__(self, ttl: float = TOKEN_TTL,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl
        self._clock = clock
        self._tokens: Dict[str, float] = {}
        self._lock = threading.Lock()

    def issue(self) -> str:
        token = secrets.token_urlsafe(32)
        now = self._clock()
        with self._lock:
            # 만료분 청소 — 무한 증가 방지
            self._tokens = {t: exp for t, exp in self._tokens.items()
                            if exp > now}
            self._tokens[token] = now + self._ttl
        return token

    def consume(self, token: str) -> bool:
        """유효하면 True — 어느 쪽이든 토큰은 제거된다(1회용)."""
        with self._lock:
            expiry = self._tokens.pop(token, None)
        return expiry is not None and expiry > self._clock()


def make_terminal_bp(auth_service: Any, token_store: TokenStore) -> Blueprint:
    bp = Blueprint("terminal", __name__)

    @bp.post("/term/token")
    def issue_token():
        # 미검증 세션은 org 추가 외 기능이 잠긴다(§10.2) — 터미널 포함
        if auth_service.current_id() is None:
            return jsonify({"error": "로그인이 필요합니다"}), 401
        return jsonify({"token": token_store.issue(),
                        "expires_in": TOKEN_TTL})

    return bp


def register_terminal_ws(sock: Any, manager: Any,
                         token_store: TokenStore) -> None:
    """flask-sock 라우트 등록 — `WS /api/term?token=…` (§12.4)."""

    @sock.route("/api/term")
    def term(ws):  # pylint: disable=unused-variable
        token = request.args.get("token", "")
        if not token_store.consume(token):
            ws.close(reason="유효하지 않은 토큰")
            return
        session = manager.create()
        stop = threading.Event()

        def pump_output() -> None:
            try:
                while not stop.is_set():
                    data = session.read(timeout=0.1)
                    if data:
                        ws.send(data.decode("utf-8", errors="replace"))
                    elif not session.alive():
                        break
            except OSError:
                pass  # 셸 exit → 세션 종료 (§12.4 수명 규칙)
            finally:
                try:
                    ws.send(json.dumps({"type": "exit"}))
                    ws.close()
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

        reader = threading.Thread(target=pump_output, daemon=True,
                                  name="pm-term-reader")
        reader.start()
        try:
            while True:
                raw = ws.receive()
                if raw is None:
                    break
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    session.write(str(raw))
                    continue
                if msg.get("type") == "input":
                    session.write(str(msg.get("data", "")))
                elif msg.get("type") == "resize":
                    session.resize(int(msg.get("rows", 24)),
                                   int(msg.get("cols", 80)))
        finally:
            stop.set()
            manager.discard(session.session_id)
