"""서버 수명 관리 (§12.5) — "창을 닫으면 서버도 꺼진다".

- 페이지 JS가 2초 간격 heartbeat(탭별 세션 ID).
- "활성 탭" = 마지막 heartbeat가 timeout(10초) 이내인 세션 ID —
  tab-close beacon이 유실돼도 timeout 경과로 자연히 빠진다.
- **종료 판정의 주체는 오직 watchdog**: 활성 집합이 빈 상태로
  유예(grace)가 지속될 때만 종료. beacon은 판정을 앞당기는 힌트다.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable, Dict, List, Optional

from flask import Blueprint, jsonify, request

# §12.5: heartbeat 2초 간격 → timeout 10초 = 5회 연속 누락.
# 백그라운드 탭의 타이머 스로틀링을 감안한 여유값.
HEARTBEAT_TIMEOUT = 10.0
GRACE = 10.0
# 기동 직후 브라우저가 아직 안 붙은 구간의 보호 — 첫 heartbeat가
# 이 시간 안에 안 오면 브라우저 오픈 실패로 보고 종료한다.
STARTUP_GRACE = 60.0


class LifecycleManager:
    """활성 탭 집합 추적과 종료 판정 — 순수 로직 (스레드는 Watchdog).

    Args:
        heartbeat_timeout: 활성 탭 판정 기준 (초).
        grace: 빈 집합이 지속돼야 하는 유예 (초).
        startup_grace: 첫 heartbeat 대기 한도 (초).
        clock: 테스트 주입용 단조 시계.
    """

    def __init__(
        self,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT,
        grace: float = GRACE,
        startup_grace: float = STARTUP_GRACE,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._timeout = heartbeat_timeout
        self._grace = grace
        self._startup_grace = startup_grace
        self._clock = clock
        self._lock = threading.Lock()
        self._beats: Dict[str, float] = {}
        self._started_at = clock()
        self._seen_any = False
        self._empty_since: Optional[float] = None

    def heartbeat(self, session_id: str) -> None:
        with self._lock:
            self._beats[session_id] = self._clock()
            self._seen_any = True
            self._empty_since = None

    def tab_close(self, session_id: str) -> None:
        """beacon 수신 — 그 탭을 활성 집합에서 즉시 제거하는 표시일 뿐,
        서버를 직접 종료하지 않는다 (§12.5)."""
        with self._lock:
            self._beats.pop(session_id, None)

    def active_sessions(self, now: Optional[float] = None) -> List[str]:
        now = self._clock() if now is None else now
        with self._lock:
            # 만료 항목은 정리 — 집합이 무한히 자라지 않게
            stale = [sid for sid, beat in self._beats.items()
                     if now - beat > self._timeout]
            for sid in stale:
                del self._beats[sid]
            return list(self._beats)

    def should_exit(self) -> bool:
        """watchdog 전용 — 주기 호출을 전제로 빈 집합 지속 시간을 잰다."""
        now = self._clock()
        if self.active_sessions(now):
            self._empty_since = None
            return False
        if not self._seen_any:
            return (now - self._started_at) >= self._startup_grace
        if self._empty_since is None:
            self._empty_since = now
            return False
        return (now - self._empty_since) >= self._grace


class Watchdog(threading.Thread):
    """주기적으로 판정을 묻고, 종료 조건이 서면 on_exit를 1회 호출."""

    def __init__(self, manager: LifecycleManager,
                 on_exit: Callable[[], None],
                 interval: float = 1.0) -> None:
        super().__init__(daemon=True, name="pm-lifecycle-watchdog")
        self._manager = manager
        self._on_exit = on_exit
        self._interval = interval
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.wait(self._interval):
            if self._manager.should_exit():
                self._on_exit()
                return


def make_lifecycle_bp(manager: LifecycleManager) -> Blueprint:
    """POST /heartbeat · POST /tab-close · GET /health (§5 api/lifecycle)."""
    bp = Blueprint("lifecycle", __name__)

    @bp.get("/health")
    def health():
        # 포트 인계(system/takeover §12.5)가 "포트 점유자 = Plugin Cafe
        # 서버"를 판별하는 마커 — 무인증(로그인 전에도 응답해야 함).
        return jsonify({"app": "plugin-cafe", "pid": os.getpid()})

    @bp.post("/heartbeat")
    def heartbeat():
        session_id = (request.get_json(silent=True) or {}).get("session")
        if not session_id:
            return jsonify({"error": "session 필요"}), 400
        manager.heartbeat(str(session_id))
        return jsonify({"ok": True})

    @bp.post("/tab-close")
    def tab_close():
        # sendBeacon은 text/plain으로 올 수 있다 — 본문 = 세션 ID
        payload = request.get_json(silent=True)
        session_id = (payload or {}).get("session") if payload \
            else request.get_data(as_text=True).strip()
        if session_id:
            manager.tab_close(str(session_id))
        return jsonify({"ok": True})

    return bp
