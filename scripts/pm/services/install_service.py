"""설치/삭제/업데이트 use case (Architecture.md §6.2 — 링크 1급).

install: clone → 프로파일 감지 → (enable) 링크 2개 생성
(+ native면 marketplace 등록·enabledPlugins 병행 §6.3).
어느 단계든 실패하면 부분 산출물(clone·링크·등록)을 되감는다.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Tuple

from pm.claudeplug.links import PluginLinks
from pm.claudeplug.registry import (ClaudePluginRegistry, detect_profile,
                                    validate_convention)
from pm.errors import PmError, RegistryError
from pm.gitops import GitRunner, remove_repo_dir
from pm.models import Plugin
from pm.paths import ProjectPaths

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class InstallResult:
    """설치 결과 — 링크명(=등록명)·프로파일·규약 경고."""

    plugin: Plugin
    entry_name: str  # 링크명 — native면 marketplace 등록명과 동일 규칙
    enabled: bool
    warnings: Tuple[str, ...] = ()
    profile: str = "standalone"  # §6.1 표


class InstallService:
    """§6.2 설치 흐름 담당 (§2.2 ISP — git·links·registry·paths만 의존).

    Args:
        paths: ProjectPaths.
        git: GitRunner (§11 인증은 구현체 몫).
        links: PluginLinks — 링크 1급 (§6.2).
        registry: ClaudePluginRegistry — native 병행 (§6.3).
    """

    def __init__(
        self,
        paths: ProjectPaths,
        git: GitRunner,
        registry: ClaudePluginRegistry,
        links: PluginLinks,
    ) -> None:
        self._paths = paths
        self._git = git
        self._registry = registry
        self._links = links

    def install(self, plugin: Plugin, enable: bool = True) -> InstallResult:
        """clone → 프로파일 감지 → 링크(+native 등록) (§6.2).

        Raises:
            PmError: 이미 설치됨.
            GitOpsError: clone 실패.
            RegistryError: native 규약 위반 — clone은 정리된다.
        """
        dest = self._paths.plugin_clone_dir(plugin.org, plugin.name)
        if dest.exists():
            raise PmError(f"이미 설치됨: {plugin.ref}")
        self._git.clone(plugin.clone_url, dest)
        entry_name = None
        link_name = None
        warnings: Tuple[str, ...] = ()
        try:
            profile = detect_profile(dest)
            if profile == "native":
                errors, warn_list = validate_convention(dest)
                warnings = tuple(warn_list)
                if errors:
                    raise RegistryError(
                        f"native 규약 위반 — {plugin.ref}: "
                        + " / ".join(errors))
                entry_name = self._registry.register(plugin.org, plugin.name)
            if enable:
                link_name = self._links.enable(plugin.org, plugin.name)
                if entry_name is not None:
                    self._registry.set_enabled(entry_name, True)
        except BaseException:
            self._rollback(plugin, entry_name)
            raise
        return InstallResult(plugin,
                             entry_name=link_name or entry_name
                             or plugin.name,
                             enabled=enable, warnings=warnings,
                             profile=profile)

    def uninstall(self, org: str, name: str) -> None:
        """링크 제거 → (native면 등록 해제) → clone 삭제 (§6.2 순서).

        Raises:
            PmError: 설치돼 있지 않음.
        """
        entry_name = self._registry.entry_for(org, name)
        dest = self._paths.plugin_clone_dir(org, name)
        if entry_name is None and not dest.exists() \
                and not self._links.is_enabled(org, name):
            raise PmError(f"설치되지 않음: {org}/{name}")
        self._links.disable(org, name)
        if entry_name is not None:
            self._registry.unregister(entry_name)
        remove_repo_dir(dest)

    def update(self, org: str, name: str) -> str:
        """git pull — 링크는 같은 경로라 그대로 (§6.2).
        native면 멱등 재등록으로 캐시 재복사 강제 (§6.3), 활성 상태 보존.

        Returns:
            갱신 후 HEAD 커밋 해시.

        Raises:
            PmError: 설치돼 있지 않음. GitOpsError: pull 실패.
        """
        dest = self._paths.plugin_clone_dir(org, name)
        if not dest.is_dir():
            raise PmError(f"설치되지 않음: {org}/{name}")
        self._git.pull(dest)
        if detect_profile(dest) == "native":
            self._registry.register(org, name)  # 멱등 — 활성 상태 불변
        return self._git.head_commit(dest)

    def _rollback(self, plugin: Plugin, entry_name) -> None:
        """설치 되감기 — 링크·등록·clone 순으로 정리 (§6.2)."""
        try:
            self._links.disable(plugin.org, plugin.name)
        except RegistryError:
            logger.warning("되감기 중 링크 제거 실패: %s", plugin.ref)
        if entry_name is not None:
            try:
                self._registry.unregister(entry_name)
            except RegistryError:
                logger.warning("되감기 중 등록 해제 실패: %s", entry_name)
        remove_repo_dir(self._paths.plugin_clone_dir(plugin.org, plugin.name))
