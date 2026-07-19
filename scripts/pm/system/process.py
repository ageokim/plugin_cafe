"""cwd=ROOT 프로세스 실행 + 외부 터미널 열기(보조) (§5·§12.1).

내장 터미널(M5 system/terminal.py)과 별개로, 로컬 환경에서 실제 OS
터미널 창을 여는 보조 기능과 일반 subprocess 실행을 담당한다.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
from typing import Callable, List, Optional, Sequence

from pm.errors import PmError
from pm.paths import ProjectPaths


class CommandRunner:
    """ROOT를 cwd로 하는 subprocess 실행기.

    Args:
        paths: ProjectPaths — 모든 실행의 작업 디렉토리.
        run: 테스트 주입용 subprocess.run 대체물.
        which: 테스트 주입용 shutil.which 대체물.
        system: 테스트 주입용 platform.system 대체물.
    """

    def __init__(
        self,
        paths: ProjectPaths,
        run: Callable[..., "subprocess.CompletedProcess[str]"] = None,
        which: Callable[[str], Optional[str]] = None,
        system: Callable[[], str] = None,
    ) -> None:
        self._paths = paths
        self._run = run if run is not None else subprocess.run
        self._which = which if which is not None else shutil.which
        self._system = system if system is not None else platform.system

    def run(
        self,
        args: Sequence[str],
        timeout: Optional[float] = None,
    ) -> "subprocess.CompletedProcess[str]":
        """명령을 ROOT에서 실행하고 결과를 반환한다 (출력 캡처).

        Args:
            args: 실행할 인자 목록.
            timeout: 초 단위 제한 — None이면 무제한.
        """
        return self._run(
            list(args),
            cwd=str(self._paths.root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def open_external_terminal(self) -> str:
        """OS 터미널 새 창을 ROOT에서 연다. 사용한 명령 이름을 반환.

        Raises:
            PmError: 사용할 수 있는 터미널을 찾지 못함.
        """
        root = str(self._paths.root)
        for name, args in self._terminal_candidates(root):
            if self._which(name) is None:
                continue
            self._spawn(args)
            return name
        raise PmError(
            "열 수 있는 터미널을 찾지 못했습니다 — 내장 터미널(웹)을 "
            "사용하세요 (§12.4)")

    def _terminal_candidates(self, root: str) -> List[tuple]:
        """OS별 (탐색용 실행파일명, 실행 인자) 후보 — 우선순위순."""
        system = self._system()
        if system == "Windows":
            return [
                ("wt.exe", ["wt.exe", "-d", root]),
                ("powershell", [
                    "cmd", "/c", "start", "powershell", "-NoExit",
                    "-Command", f"cd '{root}'"
                ]),
            ]
        if system == "Darwin":
            return [("open", ["open", "-a", "Terminal", root])]
        return [
            ("gnome-terminal",
             ["gnome-terminal", f"--working-directory={root}"]),
            ("konsole", ["konsole", "--workdir", root]),
            ("x-terminal-emulator", ["x-terminal-emulator"]),
            ("xterm", ["xterm"]),
        ]

    def _spawn(self, args: Sequence[str]) -> None:
        """터미널을 붙잡지 않도록 분리 실행한다 (테스트에서 오버라이드)."""
        subprocess.Popen(  # noqa: S603 — 후보 목록은 코드 내 고정값
            list(args),
            cwd=str(self._paths.root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
