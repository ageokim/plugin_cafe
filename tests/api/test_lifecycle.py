"""LifecycleManager 판정 로직 (§12.5) — fake clock, 스레드 없음."""

from __future__ import annotations

from pm.api.lifecycle import LifecycleManager


class Clock:

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make(clock: Clock) -> LifecycleManager:
    return LifecycleManager(heartbeat_timeout=10.0, grace=10.0,
                            startup_grace=60.0, clock=clock)


def test_startup_grace_without_browser():
    clock = Clock()
    manager = make(clock)
    assert not manager.should_exit()  # 기동 직후 — 브라우저 대기
    clock.advance(59.0)
    assert not manager.should_exit()
    clock.advance(2.0)
    assert manager.should_exit()  # 브라우저가 끝내 안 붙음 → 종료


def test_heartbeat_keeps_alive_and_timeout_expires():
    clock = Clock()
    manager = make(clock)
    manager.heartbeat("tab-1")
    clock.advance(9.0)
    assert not manager.should_exit()  # timeout 이내 = 활성

    clock.advance(2.0)  # 마지막 beat로부터 11초 — beacon 유실 시나리오
    assert not manager.should_exit()  # 빈 집합 감지 시작 (유예 시작)
    clock.advance(9.0)
    assert not manager.should_exit()
    clock.advance(2.0)
    assert manager.should_exit()  # 유예 10초 경과 → 종료 (최대 ~20초)


def test_tab_close_starts_grace_immediately():
    clock = Clock()
    manager = make(clock)
    manager.heartbeat("tab-1")
    manager.tab_close("tab-1")  # beacon = 즉시 제거 표시 (§12.5)
    assert not manager.should_exit()  # 유예 시작
    clock.advance(10.5)
    assert manager.should_exit()


def test_refresh_within_grace_survives():
    clock = Clock()
    manager = make(clock)
    manager.heartbeat("tab-1")
    manager.tab_close("tab-1")  # 새로고침: 닫힘 후 곧 재접속
    assert not manager.should_exit()
    clock.advance(5.0)
    manager.heartbeat("tab-2")  # 유예 내 복귀 → 유예 리셋
    clock.advance(9.0)
    assert not manager.should_exit()


def test_multi_tab_needs_all_closed():
    clock = Clock()
    manager = make(clock)
    manager.heartbeat("tab-1")
    manager.heartbeat("tab-2")
    manager.tab_close("tab-1")  # 한 탭만 닫힘 — 종료 아님
    clock.advance(5.0)
    manager.heartbeat("tab-2")
    clock.advance(9.0)
    assert not manager.should_exit()
    assert manager.active_sessions() == ["tab-2"]
