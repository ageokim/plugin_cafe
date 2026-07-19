"""내장 터미널의 pty 세션 관리 (§12.4).

POSIX는 표준 pty, Windows는 pywinpty(ConPTY). 셸은 cwd=ROOT로 뜬다 —
여기서 `pm`·`claude`(완전한 대화형)를 그대로 실행한다.
"""

from __future__ import annotations

import os
import platform
import select
import signal
import threading
import time
import uuid
from typing import Dict, Optional

from pm.errors import PmError
from pm.paths import ProjectPaths


class PosixTerminalSession:
    """pty.fork 기반 셸 세션 — read/write/resize/close."""

    def __init__(self, root: str, shell: Optional[str] = None) -> None:
        import pty  # POSIX 전용 — Windows에서는 임포트되지 않는다

        self.session_id = uuid.uuid4().hex
        shell = shell or os.environ.get("SHELL") or "/bin/sh"
        pid, fd = pty.fork()
        if pid == 0:  # 자식: ROOT에서 셸 실행
            os.chdir(root)
            os.execvp(shell, [shell])  # noqa: S606 — 사용자 자신의 셸
        self._pid = pid
        self._fd = fd

    def read(self, timeout: float = 0.1) -> bytes:
        """출력 읽기 — timeout 내 데이터 없으면 b''. EOF는 OSError."""
        ready, _, _ = select.select([self._fd], [], [], timeout)
        if not ready:
            return b""
        return os.read(self._fd, 65536)

    def write(self, data: str) -> None:
        os.write(self._fd, data.encode("utf-8", errors="ignore"))

    def resize(self, rows: int, cols: int) -> None:
        import fcntl
        import struct
        import termios
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)

    def alive(self) -> bool:
        try:
            pid, _ = os.waitpid(self._pid, os.WNOHANG)
        except ChildProcessError:  # 이미 회수됨
            return False
        return pid == 0

    def close(self) -> None:
        """SIGHUP → 최대 1초 회수 대기 → SIGKILL — 좀비를 남기지 않는다."""
        try:
            os.kill(self._pid, signal.SIGHUP)
        except ProcessLookupError:
            pass
        try:
            os.close(self._fd)
        except OSError:
            pass
        for _ in range(20):
            try:
                pid, _ = os.waitpid(self._pid, os.WNOHANG)
            except ChildProcessError:
                return
            if pid != 0:
                return
            time.sleep(0.05)
        try:
            os.kill(self._pid, signal.SIGKILL)
            os.waitpid(self._pid, 0)
        except (ProcessLookupError, ChildProcessError):
            pass


class WindowsTerminalSession:
    """pywinpty(ConPTY) 세션 — POSIX 세션과 동일 인터페이스."""

    def __init__(self, root: str, shell: Optional[str] = None) -> None:
        try:
            from winpty import PtyProcess  # pylint: disable=import-error
        except ImportError as exc:
            raise PmError(
                "pywinpty가 없어 내장 터미널을 열 수 없습니다 (§9.2 "
                "설치 후 재시도)") from exc
        self.session_id = uuid.uuid4().hex
        shell = shell or os.environ.get("COMSPEC") or "cmd.exe"
        self._proc = PtyProcess.spawn(shell, cwd=root)

    def read(self, timeout: float = 0.1) -> bytes:
        del timeout  # winpty read는 논블로킹 폴링으로 대체
        try:
            return self._proc.read(65536).encode("utf-8", errors="ignore")
        except EOFError:
            raise OSError("세션 종료")  # pylint: disable=raise-missing-from

    def write(self, data: str) -> None:
        self._proc.write(data)

    def resize(self, rows: int, cols: int) -> None:
        self._proc.setwinsize(rows, cols)

    def alive(self) -> bool:
        return self._proc.isalive()

    def close(self) -> None:
        if self._proc.isalive():
            self._proc.terminate()


class TerminalManager:
    """세션 생성·조회·전체 정리 (§12.5 종료 시 close_all)."""

    def __init__(self, paths: ProjectPaths,
                 system: Optional[str] = None) -> None:
        self._root = str(paths.root)
        self._system = system if system is not None else platform.system()
        self._sessions: Dict[str, object] = {}
        self._lock = threading.Lock()

    def create(self):
        if self._system == "Windows":
            session = WindowsTerminalSession(self._root)
        else:
            session = PosixTerminalSession(self._root)
        with self._lock:
            self._sessions[session.session_id] = session
        return session

    def discard(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.pop(session_id, None)
        if session is not None:
            session.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
