"""포트 자동 인계 테스트 (§12.5) — fake seam, 실 소켓·실 kill 없음."""

from __future__ import annotations

import json
import os
import signal
import urllib.request

import pytest

from pm.system import takeover
from pm.system.takeover import (can_signal, probe_cafe_server,
                                takeover_port)


# ── probe: /api/health 마커 판별 ──────────────────────────────
class FakeResponse:

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def opener_returning(payload: bytes):
    def opener(url, timeout):  # noqa: ARG001 — urlopen 시그니처 맞춤
        del url, timeout
        return FakeResponse(payload)
    return opener


def test_probe_detects_cafe_marker():
    payload = json.dumps({"app": "plugin-cafe", "pid": 4242}).encode()
    assert probe_cafe_server(8765, opener=opener_returning(payload)) == 4242


@pytest.mark.parametrize("payload", [
    json.dumps({"app": "other-app", "pid": 1}).encode(),  # 다른 앱
    json.dumps({"pid": 7}).encode(),                      # 마커 없음
    json.dumps({"app": "plugin-cafe", "pid": "7"}).encode(),  # pid 비정수
    json.dumps({"app": "plugin-cafe", "pid": 0}).encode(),    # pid 무효
    json.dumps(["plugin-cafe"]).encode(),                 # dict 아님
    b"<html>not json</html>",                             # 비JSON
])
def test_probe_rejects_foreign_or_broken(payload):
    assert probe_cafe_server(8765,
                             opener=opener_returning(payload)) is None


def test_probe_connection_failure_is_none():
    def opener(url, timeout):
        raise OSError("connection refused")
    assert probe_cafe_server(8765, opener=opener) is None


def test_default_opener_bypasses_proxy():
    # http_proxy 환경변수를 타면 루프백 probe가 외부로 새고(§11) 프록시
    # 위조 응답이 kill을 유도할 수 있다 — ProxyHandler({})를 넘기면
    # env를 읽는 기본 ProxyHandler가 대체·탈락해 프록시 경로가 사라진다
    handlers = takeover._DIRECT_OPENER.handlers  # pylint: disable=protected-access
    assert not any(isinstance(h, urllib.request.ProxyHandler)
                   for h in handlers)


# ── can_signal: 종료 권한 실측 (POSIX) ────────────────────────
@pytest.mark.skipif(os.name != "posix", reason="POSIX 전용 검사")
def test_can_signal_paths():
    def eperm(pid, sig):
        raise PermissionError("EPERM")
    assert not can_signal(4242, kill=eperm)  # 다른 사용자 소유

    def esrch(pid, sig):
        raise ProcessLookupError()
    assert can_signal(4242, kill=esrch)  # 이미 죽음 — 낙관

    assert can_signal(4242, kill=lambda pid, sig: None)  # 권한 있음


# ── takeover: 자기 서버만 종료·회수 ───────────────────────────
class FakeWorld:
    """점유 프로세스 모형 — kill 신호에 따라 죽고, busy는 생존 실측."""

    def __init__(self, occupied=True, dies_on=signal.SIGTERM,
                 kill_error=None, frees_at=None):
        self.occupied = occupied
        self.dies_on = dies_on        # None = 어떤 신호로도 안 죽음
        self.kill_error = kill_error  # kill 호출 시 던질 예외
        self.frees_at = frees_at      # 신호와 무관하게 이 시각에 해제
        self.killed = []
        self.now = 0.0

    def busy(self, port):
        del port
        if self.frees_at is not None and self.now >= self.frees_at:
            return False
        return self.occupied

    def kill(self, pid, sig):
        self.killed.append((pid, sig))
        if self.kill_error is not None:
            raise self.kill_error
        if self.dies_on is not None and sig == self.dies_on:
            self.occupied = False

    def sleep(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now


def run_takeover(world, prober, deadline=5.0):
    return takeover_port(8765, prober=prober, kill=world.kill,
                         busy=world.busy, sleep=world.sleep,
                         clock=world.clock, deadline=deadline)


def test_free_port_needs_nothing():
    world = FakeWorld(occupied=False)
    assert run_takeover(world, prober=lambda p: 4242)
    assert world.killed == []


def test_foreign_process_untouched():
    world = FakeWorld()
    assert not run_takeover(world, prober=lambda p: None)
    assert world.killed == []


def test_own_server_sigterm_then_freed():
    world = FakeWorld(dies_on=signal.SIGTERM)
    assert run_takeover(world, prober=lambda p: 4242)
    assert world.killed == [(4242, signal.SIGTERM)]


@pytest.mark.skipif(not hasattr(signal, "SIGKILL"),
                    reason="SIGKILL은 POSIX 전용")
def test_stubborn_server_gets_sigkill():
    world = FakeWorld(dies_on=signal.SIGKILL)  # SIGTERM 무시
    assert run_takeover(world, prober=lambda p: 4242)
    assert world.killed == [(4242, signal.SIGTERM), (4242, signal.SIGKILL)]


def test_immortal_server_fails_within_deadline():
    world = FakeWorld(dies_on=None)
    assert not run_takeover(world, prober=lambda p: 4242, deadline=2.0)
    assert world.now <= 2.5  # deadline을 크게 넘겨 기다리지 않는다


def test_permission_error_gives_up():
    world = FakeWorld(kill_error=PermissionError("EPERM"))
    assert not run_takeover(world, prober=lambda p: 4242)
    assert len(world.killed) == 1  # SIGKILL 재시도도 하지 않는다


def test_already_dead_pid_waits_for_release():
    # SIGTERM 시점엔 이미 죽었고(OS가 소켓 회수 중) 곧 포트가 풀리는 경우
    world = FakeWorld(kill_error=ProcessLookupError(), frees_at=0.2)
    assert run_takeover(world, prober=lambda p: 4242)


def test_windows_dead_pid_oserror_is_tolerated():
    # Windows의 죽은 pid는 ProcessLookupError가 아니라 WinError 87
    # (errno EINVAL)의 일반 OSError로 온다 — 크래시 없이 해제 대기
    world = FakeWorld(kill_error=OSError(22, "EINVAL"), frees_at=0.2)
    assert run_takeover(world, prober=lambda p: 4242)


def test_never_kills_self():
    world = FakeWorld()
    assert not run_takeover(world, prober=lambda p: os.getpid())
    assert world.killed == []


def test_freed_between_probe_and_recheck():
    world = FakeWorld()

    def prober(port):  # probe 순간 점유자가 스스로 내려간 경합
        world.occupied = False
        return None

    assert run_takeover(world, prober)
    assert world.killed == []
