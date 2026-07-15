"""enable/disable use case (Architecture.md §5·§6.4) — 링크 1급.

enable = 링크 2개 생성 / disable = 링크 제거. native형(plugin.json 보유,
marketplace 등록 존재)이면 enabledPlugins도 병행 토글한다(§6.3) —
단 **상태 판정의 기준은 링크**다(§6.4).
"""

from __future__ import annotations

from typing import List, Tuple

from pm.claudeplug.links import PluginLinks
from pm.claudeplug.registry import ClaudePluginRegistry
from pm.errors import RegistryError
from pm.models import PluginState, derive_state
from pm.paths import ProjectPaths


class ActivationService:
    """활성 토글과 상태 실측 도출 (§2.2 ISP — links·registry·paths만).

    Args:
        registry: ClaudePluginRegistry (native 병행).
        paths: ProjectPaths — clone 존재 실측용.
        links: PluginLinks — 상태의 진실 (§6.4).
    """

    def __init__(self, registry: ClaudePluginRegistry, paths: ProjectPaths,
                 links: PluginLinks) -> None:
        self._registry = registry
        self._paths = paths
        self._links = links

    def enable(self, org: str, name: str) -> None:
        """링크 생성 (+native면 enabledPlugins true).

        Raises:
            RegistryError: clone 없음 — 설치 먼저.
        """
        self._links.enable(org, name)
        self._sync_native(org, name, True)

    def disable(self, org: str, name: str) -> None:
        """링크 제거 (+native면 enabledPlugins false).

        Raises:
            RegistryError: 설치되지 않음.
        """
        if not self._paths.plugin_clone_dir(org, name).is_dir():
            raise RegistryError(
                f"설치되지 않음: {org}/{name} — pm install 먼저 (§6.4)")
        self._links.disable(org, name)
        self._sync_native(org, name, False)

    def state(self, org: str, name: str) -> PluginState:
        """§6.4 실측 도출 — clone 존재 ∧ plugin_roots 링크."""
        return derive_state(
            cloned=self._paths.plugin_clone_dir(org, name).is_dir(),
            linked=self._links.is_enabled(org, name))

    def installed_refs(self) -> List[Tuple[str, str]]:
        """디스크 실측 설치 목록 — (org, name) (§6.4, preset 전환 열거용)."""
        plugins_dir = self._paths.plugins_dir
        if not plugins_dir.is_dir():
            return []
        return sorted(
            (org_dir.name, plugin_dir.name)
            for org_dir in plugins_dir.iterdir() if org_dir.is_dir()
            for plugin_dir in org_dir.iterdir() if plugin_dir.is_dir())

    def _sync_native(self, org: str, name: str, value: bool) -> None:
        entry_name = self._registry.entry_for(org, name)
        if entry_name is not None:
            self._registry.set_enabled(entry_name, value)
