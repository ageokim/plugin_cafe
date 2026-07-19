"""TokenStore(§11 1회용 토큰) + 실 pty 세션 스모크 (§12.4, POSIX)."""

from __future__ import annotations

import sys
import time

import pytest

from pm.api.terminal import TokenStore


class Clock:

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_token_single_use():
    store = TokenStore(ttl=30.0, clock=Clock())
    token = store.issue()
    assert store.consume(token) is True
    assert store.consume(token) is False  # 1회용 — 재사용 불가


def test_token_expiry():
    clock = Clock()
    store = TokenStore(ttl=30.0, clock=clock)
    token = store.issue()
    clock.now = 31.0
    assert store.consume(token) is False


def test_unknown_token_rejected():
    store = TokenStore(clock=Clock())
    assert store.consume("위조토큰") is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX pty 전용")
def test_posix_pty_roundtrip(tmp_paths):
    """진짜 셸에 명령을 넣고 출력을 돌려받는다 — cwd=ROOT 확인 포함."""
    from pm.system.terminal import TerminalManager
    tmp_paths.root.mkdir(parents=True, exist_ok=True)
    manager = TerminalManager(tmp_paths)
    session = manager.create()
    try:
        session.write("pwd; echo MARKER-$((6*7))\n")
        collected = b""
        deadline = time.time() + 5.0
        while time.time() < deadline and b"MARKER-42" not in collected:
            collected += session.read(timeout=0.2)
        text = collected.decode(errors="replace")
        assert "MARKER-42" in text
        assert str(tmp_paths.root.resolve()) in text  # cwd=ROOT (§12.4)
    finally:
        manager.close_all()
        assert not session.alive()
