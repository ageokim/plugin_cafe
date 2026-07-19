"""claude 실행 파일 해석 (§12.3·§12.4) — PATH 밖 설치 대응.

실사용 환경에서 claude CLI는 PATH에 없을 수 있다 — VSCode 확장 내장
바이너리, claude-agent-sdk 번들, ~/.claude/local 설치 등. 해석 우선순위:

1. config ``claude_bin`` (명시 지정 — §2.3)
2. PATH의 ``claude`` (shutil.which)
3. claude-agent-sdk 번들 (``claude_agent_sdk/_bundled/``)
4. ``~/.claude/local/claude``
5. VSCode 확장 native-binary (최신 버전 우선)

``ensure_claude_on_path``는 찾은 디렉토리를 PATH 앞에 넣는다 —
serve 시작 시 1회 호출로 챗 subprocess 폴백·SDK·내장 터미널(pty)·
훅 스크립트까지 전부 `claude` 를 찾을 수 있게 된다.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
from pathlib import Path
from typing import Callable, List, MutableMapping, Optional

logger = logging.getLogger(__name__)


def _exe_name(system: Callable[[], str]) -> str:
    return "claude.exe" if system() == "Windows" else "claude"


def _sdk_bundle_dir() -> Optional[Path]:
    """claude-agent-sdk 번들 디렉토리 — SDK 미설치면 None."""
    try:
        import claude_agent_sdk  # pylint: disable=import-outside-toplevel
        return Path(claude_agent_sdk.__file__).parent / "_bundled"
    except ImportError:
        return None


def _known_locations(
    home: Path,
    system: Callable[[], str],
    sdk_locator: Callable[[], Optional[Path]] = _sdk_bundle_dir,
) -> List[Path]:
    """PATH 밖의 잘 알려진 설치 위치 후보 — 우선순위순."""
    exe = _exe_name(system)
    candidates: List[Path] = []
    bundle = sdk_locator()
    if bundle is not None:
        candidates.append(bundle / exe)
    candidates.append(home / ".claude" / "local" / exe)
    extensions_dir = home / ".vscode" / "extensions"
    if extensions_dir.is_dir():
        for ext in sorted(extensions_dir.glob("anthropic.claude-code-*"),
                          reverse=True):
            candidates.append(ext / "resources" / "native-binary" / exe)
    return candidates


def resolve_claude_bin(
    config: Optional[object] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    home: Optional[Path] = None,
    system: Callable[[], str] = platform.system,
    sdk_locator: Callable[[], Optional[Path]] = _sdk_bundle_dir,
) -> Optional[str]:
    """claude 실행 파일의 절대경로 — 못 찾으면 None.

    Args:
        config: ``claude_bin`` 속성을 가진 ConfigProvider (선택).
        which/home/system: 테스트 주입 seam.
    """
    configured = getattr(config, "claude_bin", None) if config else None
    if configured:
        path = Path(configured)
        if path.exists() and os.access(str(path), os.X_OK):
            return str(path)
        logger.warning("config claude_bin이 유효하지 않음: %s — 자동 탐색으로"
                       " 폴백", configured)
    found = which("claude")
    if found:
        return found
    home_dir = home if home is not None else Path.home()
    for candidate in _known_locations(home_dir, system, sdk_locator):
        if candidate.exists() and os.access(str(candidate), os.X_OK):
            return str(candidate)
    return None


def ensure_claude_on_path(
    config: Optional[object] = None,
    environ: Optional[MutableMapping[str, str]] = None,
    which: Callable[[str], Optional[str]] = shutil.which,
    home: Optional[Path] = None,
    system: Callable[[], str] = platform.system,
    sdk_locator: Callable[[], Optional[Path]] = _sdk_bundle_dir,
) -> Optional[str]:
    """claude를 해석하고 그 디렉토리를 PATH 앞에 넣는다(멱등).

    Returns:
        해석된 claude 절대경로 — 못 찾으면 None (PATH 무변경).
    """
    env = environ if environ is not None else os.environ
    resolved = resolve_claude_bin(config, which=which, home=home,
                                  system=system, sdk_locator=sdk_locator)
    if resolved is None:
        logger.warning(
            "claude 실행 파일을 찾지 못함 — 챗·내장 터미널에서 claude를 "
            "쓸 수 없습니다. config.json에 claude_bin을 지정하세요 (§2.3)")
        return None
    directory = str(Path(resolved).parent)
    parts = env.get("PATH", "").split(os.pathsep)
    if directory not in parts:
        env["PATH"] = directory + os.pathsep + env.get("PATH", "")
    return resolved
