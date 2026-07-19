"""git 명령 실행 (Architecture.md §5·§11).

인증 토큰은 argv(`-c http.extraHeader` — ps에 노출)가 아니라
GIT_CONFIG_COUNT/KEY/VALUE 환경변수로만 전달하고,
GIT_TERMINAL_PROMPT=0으로 크리덴셜 프롬프트를 차단한다.
"""

from __future__ import annotations

import base64
import logging
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Protocol, Tuple

from pm.errors import GitOpsError

logger = logging.getLogger(__name__)


class GitRunner(Protocol):
    """git 연산 추상 — subprocess 구현과 테스트 기록형이 호환 (§2.2)."""

    def clone(self, clone_url: str, dest: Path) -> None:
        """Raises GitOpsError: clone 실패."""

    def pull(self, repo_dir: Path) -> None:
        """Raises GitOpsError: pull 실패."""

    def head_commit(self, repo_dir: Path) -> str:
        """HEAD 커밋 해시를 돌려준다. Raises GitOpsError."""


def build_git_env(
    token: Optional[str],
    ca_bundle: Optional[str] = None,
    base_env: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """git 프로세스용 환경변수를 만든다 (§11 방식).

    Args:
        token: PAT — None이면 무인증 (공개 repo).
        ca_bundle: §10.5 사내 인증서 번들 경로.
        base_env: 바탕 환경 — None이면 os.environ.
    """
    env = dict(base_env if base_env is not None else os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    configs: List[Tuple[str, str]] = []
    if token:
        basic = base64.b64encode(
            f"x-access-token:{token}".encode("utf-8")).decode("ascii")
        configs.append(("http.extraheader", f"Authorization: basic {basic}"))
    if ca_bundle:
        configs.append(("http.sslCAInfo", ca_bundle))
    env["GIT_CONFIG_COUNT"] = str(len(configs))
    for index, (key, value) in enumerate(configs):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


def _clear_readonly(func: Callable[[str], None], path: str, _exc) -> None:
    """Windows read-only .git 오브젝트 삭제 대응 (§6.2)."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove_repo_dir(path: Path) -> None:
    """clone 디렉토리를 지운다 — read-only 파일(.git 오브젝트) 포함."""
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        # onerror는 3.12에서 deprecated — 신 시그니처로 호출
        shutil.rmtree(path, onexc=_clear_readonly)  # pylint: disable=unexpected-keyword-arg
    else:
        shutil.rmtree(path, onerror=_clear_readonly)


class SubprocessGitRunner:
    """GitRunner의 subprocess 구현체.

    Args:
        token_provider: 호출 시점의 PAT를 돌려주는 콜러블 (§2.2 DIP).
        ca_bundle_provider: §10.5 인증서 경로 콜러블 — None이면 미사용.
        git_executable: git 실행 파일 이름/경로.
    """

    def __init__(
        self,
        token_provider: Callable[[], Optional[str]],
        ca_bundle_provider: Optional[Callable[[], Optional[str]]] = None,
        git_executable: str = "git",
    ) -> None:
        self._token_provider = token_provider
        self._ca_bundle_provider = ca_bundle_provider
        self._git = git_executable

    def clone(self, clone_url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        self._run(["clone", clone_url, str(dest)])

    def pull(self, repo_dir: Path) -> None:
        self._run(["-C", str(repo_dir), "pull", "--ff-only"])

    def head_commit(self, repo_dir: Path) -> str:
        return self._run(["-C", str(repo_dir), "rev-parse", "HEAD"])

    def _run(self, args: List[str]) -> str:
        """git을 실행하고 stdout을 돌려준다 — 실패는 GitOpsError."""
        ca_bundle = (self._ca_bundle_provider()
                     if self._ca_bundle_provider is not None else None)
        env = build_git_env(self._token_provider(), ca_bundle)
        try:
            completed = subprocess.run(
                [self._git] + args,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as e:
            raise GitOpsError(f"git 실행 실패: {e}") from e
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            tail = detail[-1] if detail else f"exit {completed.returncode}"
            raise GitOpsError(f"git {args[0]} 실패: {tail}")
        return completed.stdout.strip()
