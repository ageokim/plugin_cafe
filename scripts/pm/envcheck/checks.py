"""§9.4 체크 13항목의 기본 probe 구성.

각 probe는 순수 콜러블 — 테스트는 ProbeCheck에 fake probe를 꽂거나,
build_checks에 fake 협력자(which·run 등)를 주입해 검증한다(§13.3).
"""

from __future__ import annotations

import importlib
import json
import platform
import shutil
import socket
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Callable, List, Optional

from pm.config import ConfigProvider
from pm.envcheck.checker import BOOTSTRAP, WEB, ProbeCheck, ProbeResult
from pm.paths import ProjectPaths

_INSTALL_CMD = ('"$PYTHON" -m pip install --user -r env/requirements.txt'
                " (§9.2 — PEP 668이면 --break-system-packages 추가)")

# (모듈명, 3.10+ 전용 여부, Windows 전용 여부) — §9.2 requirements와 일치
_REQUIRED_MODULES = [
    ("flask", False, False),
    ("flask_sock", False, False),
    ("requests", False, False),
    ("claude_agent_sdk", True, False),
    ("winpty", False, True),
]


def _is_windows(system: Callable[[], str]) -> bool:
    return system() == "Windows"


def _os_fix(system: Callable[[], str], win: str, posix: str) -> str:
    return win if _is_windows(system) else posix


def build_checks(
    paths: ProjectPaths,
    config: ConfigProvider,
    which: Callable[[str], Optional[str]] = None,
    run: Callable[..., "subprocess.CompletedProcess[str]"] = None,
    system: Callable[[], str] = None,
    version: Optional[tuple] = None,
    prober: Callable[[int], Optional[int]] = None,
) -> List[ProbeCheck]:
    """§9.4 표 13항목을 조립한다 — 항목 순서는 표 번호와 동일.

    Args:
        paths: ProjectPaths.
        config: ConfigProvider (host·port 등).
        which/run/system/version: 테스트 주입 seam — None이면 실물.
        prober: 포트 점유자 판별 seam — None이면 takeover.probe_cafe_server.
    """
    which = which if which is not None else shutil.which
    run = run if run is not None else subprocess.run
    system = system if system is not None else platform.system
    ver = version if version is not None else sys.version_info

    def python_version() -> ProbeResult:
        ok = tuple(ver[:2]) >= (3, 8)
        detail = f"python {ver[0]}.{ver[1]} 발견"
        if ok and tuple(ver[:2]) < (3, 10):
            detail += (" — 챗 SDK는 Python 3.10+, 이 버전에서는 "
                       "subprocess 폴백으로 동작(§12.3)")
        fix = None if ok else _os_fix(
            system, "winget install Python.Python.3.12",
            "sudo apt install python3")
        return ok, detail, fix

    def pinned_interpreter() -> ProbeResult:
        env_file = paths.env_file
        if not env_file.exists():
            return (False, "data/env.json 없음 — 인터프리터 미고정",
                    "셋업 재실행 (./run.sh 또는 run.cmd)")
        try:
            pinned = json.loads(env_file.read_text(encoding="utf-8"))
            pinned_path = Path(str(pinned.get("python", "")))
        except (json.JSONDecodeError, OSError) as exc:
            return (False, f"env.json 손상: {exc}",
                    "셋업 재실행 (재탐색·재기록)")
        if not pinned_path.exists():
            return (False, f"고정 인터프리터 소실: {pinned_path}",
                    "셋업 재실행 (재탐색·재기록)")
        return True, f"고정 인터프리터: {pinned_path}", None

    def pip_works() -> ProbeResult:
        result = run([sys.executable, "-m", "pip", "--version"],
                     capture_output=True, text=True, check=False)
        if result.returncode == 0:
            return True, str(result.stdout).strip(), None
        return (False, "pip 동작 안 함",
                f'"{sys.executable}" -m ensurepip --user')

    def pep668_marker() -> ProbeResult:
        marker = Path(sysconfig.get_path("stdlib")) / "EXTERNALLY-MANAGED"
        if marker.exists():
            return (True, "PEP 668 마커 있음 — 설치 시 "
                    "--break-system-packages가 자동 적용됨(§9.2)",
                    None)
        return True, "PEP 668 마커 없음", None

    def packages() -> ProbeResult:
        missing: List[str] = []
        for module, py310_only, win_only in _REQUIRED_MODULES:
            if py310_only and tuple(ver[:2]) < (3, 10):
                continue
            if win_only and not _is_windows(system):
                continue
            try:
                importlib.import_module(module)
            except ImportError:
                missing.append(module)
        if missing:
            return (False, f"미설치 패키지: {', '.join(missing)}",
                    _INSTALL_CMD)
        return True, "필수 패키지 전부 사용 가능", None

    def git_installed() -> ProbeResult:
        if which("git") is None:
            return (False, "git 없음", _os_fix(
                system, "winget install Git.Git", "sudo apt install git"))
        return True, "git 사용 가능", None

    def claude_cli() -> ProbeResult:
        from pm.system.claudebin import resolve_claude_bin
        found = resolve_claude_bin(config, which=which, system=system)
        if found is None:
            return (False, "claude 실행 파일 없음 (PATH·SDK 번들·"
                    "~/.claude/local·VSCode 확장 전부 탐색)",
                    "npm install -g @anthropic-ai/claude-code 또는 "
                    "config.json에 claude_bin 지정 (§12.3)")
        return True, f"claude: {found}", None

    def pm_on_path() -> ProbeResult:
        found = which("pm")
        if found is None:
            return (False, "pm이 PATH에 없음",
                    _os_fix(system, r"env\setup_win.ps1 재실행",
                            "./env/setup_linux.sh 재실행"))
        try:
            resolved = Path(found).resolve()
        except OSError:
            resolved = Path(found)
        expected = (paths.root / "scripts" / "bin").resolve()
        if expected not in resolved.parents and resolved.parent != expected:
            return (False,
                    f"PATH의 pm이 다른 checkout을 가리킴: {resolved}",
                    _os_fix(system, r"env\setup_win.ps1 재실행",
                            "./env/setup_linux.sh 재실행"))
        return True, f"pm shim: {resolved}", None

    def host_reachable() -> ProbeResult:
        host = config.github_host
        if host is None:
            return True, "GitHub host 미정 — 첫 org 추가 후 검사(skip)", None
        import requests  # 지연 임포트 — 5번 체크와 독립적으로 동작
        from pm.github.urls import ApiUrlBuilder
        api_base = ApiUrlBuilder(config.github_api_base).api_base(host)
        try:
            requests.head(api_base, timeout=config.http_timeout,
                          verify=config.ca_bundle or True)
        except requests.RequestException as exc:
            return (False, f"{api_base} 도달 실패: {exc}",
                    "프록시/ca_bundle 설정 확인 (§10.5)")
        return True, f"{api_base} 도달 가능", None

    def claude_structure() -> ProbeResult:
        problems: List[str] = []
        for path in (paths.marketplace_file,
                     paths.claude_settings_local_file):
            if not path.exists():
                continue  # 생성 전 상태는 정상 (§8)
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                problems.append(path.name)
        if problems:
            return (False, f"손상된 파일: {', '.join(problems)}",
                    "pm inspect --repair")
        return True, ".claude 구조 정합", None

    def credentials_perms() -> ProbeResult:
        cred = paths.credentials_file
        if not cred.exists():
            return True, "credentials.json 없음 — 로그인 전 상태", None
        if _is_windows(system):
            return True, "Windows — POSIX 권한 검사 생략", None
        mode = cred.stat().st_mode & 0o777
        if mode & 0o077:
            return (False, f"권한 {oct(mode)} — 600이어야 함",
                    f"chmod 600 {cred}")
        return True, "권한 600 확인", None

    def pty_available() -> ProbeResult:
        module = "winpty" if _is_windows(system) else "pty"
        try:
            importlib.import_module(module)
        except ImportError:
            return (False, f"{module} 사용 불가 — 내장 터미널 동작 안 함",
                    _INSTALL_CMD)
        return True, f"pty 사용 가능 ({module})", None

    def port_free() -> ProbeResult:
        # bind 의미론을 serve와 일치시키기 위해 takeover.port_busy로 실측
        # (TIME_WAIT를 점유로 오판하지 않음 — §12.5)
        from pm.system.takeover import can_signal, port_busy, \
            probe_cafe_server
        port = config.flask_port
        if not port_busy(port):
            return True, f"포트 {port} 사용 가능", None
        # 점유자가 이전 Plugin Cafe 서버면 serve가 자동 인계하므로
        # 막지 않는다 (§12.5 system/takeover) — 무관 프로세스만 FAIL
        probe = prober if prober is not None else probe_cafe_server
        pid = probe(port)
        if pid is not None and can_signal(pid):
            return (True, f"포트 {port}를 이전 Plugin Cafe 서버"
                    f"(pid {pid})가 점유 — 시작 시 자동 인계(§12.5)",
                    None)
        if pid is not None:  # 다른 사용자 소유 — serve도 EPERM 실패
            return (False, f"포트 {port}를 다른 사용자의 Plugin Cafe "
                    f"서버(pid {pid})가 점유 — 권한이 없어 자동 인계 불가",
                    f"해당 사용자로 pid {pid} 종료 또는 config.json의 "
                    "flask_port 변경")
        return (False, f"포트 {port} 사용 중",
                "점유 프로세스 종료 또는 config.json의 flask_port 변경")

    return [
        ProbeCheck("python_version", "python ≥ 3.8", BOOTSTRAP,
                   python_version),
        ProbeCheck("pinned_interpreter", "고정 인터프리터 일치", BOOTSTRAP,
                   pinned_interpreter),
        ProbeCheck("pip", "pip 동작", BOOTSTRAP, pip_works),
        ProbeCheck("pep668", "PEP 668 마커 (정보성)", BOOTSTRAP,
                   pep668_marker, informational=True),
        ProbeCheck("packages", "필수 패키지", BOOTSTRAP, packages),
        ProbeCheck("git", "git", WEB, git_installed),
        ProbeCheck("claude_cli", "claude CLI", WEB, claude_cli),
        ProbeCheck("pm_path", "pm PATH 등록", WEB, pm_on_path),
        ProbeCheck("host_reachable", "GitHub 호스트 도달성", WEB,
                   host_reachable),
        ProbeCheck("claude_structure", ".claude 구조", WEB,
                   claude_structure),
        ProbeCheck("credentials_perms", "credentials 권한 (정보성)", WEB,
                   credentials_perms, informational=True),
        ProbeCheck("pty", "pty 가용성", WEB, pty_available),
        ProbeCheck("port_free", "flask_port 사용 가능", BOOTSTRAP,
                   port_free),
    ]
