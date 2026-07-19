"""상태 실측 대조 리포트·교정 (Architecture.md §6.4·§7 — 링크 1급).

진실은 파일시스템: clone + ``.claude/plugin_roots`` 링크. native형은
marketplace.json·enabledPlugins가 병행되므로 불일치를 함께 감지한다.
catalog는 스캔 캐시일 뿐이라 리포트의 근거로 쓰지 않는다.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Dict, List, Optional, Set, Tuple

from pm.claudeplug.links import PluginLinks
from pm.claudeplug.registry import (ClaudePluginRegistry, detect_profile,
                                    parse_source, validate_convention,
                                    validate_inhouse)
from pm.models import PluginState, derive_state
from pm.paths import ProjectPaths
from pm.store.json_store import JsonStore

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class PluginStatus:
    """플러그인 하나의 실측 상태와 발견된 문제."""

    org: str
    name: str
    entry_name: Optional[str]  # 링크명 (native면 marketplace 등록명과 동일)
    state: PluginState
    issues: Tuple[str, ...] = ()


class InspectService:
    """실측 대조(§6.4)·규약 검사(부록 A.4)·드리프트 교정.

    Args:
        paths: ProjectPaths.
        registry: ClaudePluginRegistry — native 병행분 대조.
        orgs_store: orgs.json — '미등록 org' 플래그 판정 (§12.2).
        links: PluginLinks — 상태의 진실 (§6.4).
    """

    def __init__(
        self,
        paths: ProjectPaths,
        registry: ClaudePluginRegistry,
        orgs_store: JsonStore,
        links: PluginLinks,
    ) -> None:
        self._paths = paths
        self._registry = registry
        self._orgs_store = orgs_store
        self._links = links

    def report(self) -> List[PluginStatus]:
        """디스크 clone ∪ native 등록의 전 항목을 실측 대조한다."""
        native_entries: Dict[Tuple[str, str], str] = {}
        targets: Set[Tuple[str, str]] = set()
        for entry_name, source in self._registry.registered().items():
            parsed = parse_source(source)
            if parsed is None:
                logger.warning("해석 불가한 source 무시: %s", source)
                continue
            native_entries[parsed] = entry_name
            targets.add(parsed)
        targets.update(self._disk_clones())
        registered_orgs = self._registered_org_names()
        return [
            self._status_for(org, name, native_entries.get((org, name)),
                             registered_orgs)
            for org, name in sorted(targets)
        ]

    def _status_for(
        self,
        org: str,
        name: str,
        native_entry: Optional[str],
        registered_orgs: Set[str],
    ) -> PluginStatus:
        """항목 하나의 실측 상태·문제 목록을 만든다 (§6.4)."""
        clone_dir = self._paths.plugin_clone_dir(org, name)
        cloned = clone_dir.is_dir()
        link_name = self._links.link_name_for(org, name)
        linked = link_name is not None
        state = derive_state(cloned=cloned, linked=linked)
        issues: List[str] = []
        if native_entry is not None and not cloned:
            issues.append("드리프트 — native 등록만 존재, clone 없음")
        if org not in registered_orgs:
            issues.append("미등록 org — org 재등록 또는 삭제 권장 (§12.2)")
        if cloned and detect_profile(clone_dir) == "standalone":
            if native_entry is not None:
                issues.append(
                    "드리프트 — native 등록 잔존, plugin.json 없음 (--repair)")
            issues.extend(f"규약 권장: {warning}"
                          for warning in validate_inhouse(clone_dir))
        if cloned and detect_profile(clone_dir) == "native":
            if native_entry is None:
                issues.append(
                    "드리프트 — native형인데 marketplace 미등록 (--repair)")
            elif self._registry.is_enabled(native_entry) != linked:
                issues.append(
                    "드리프트 — enabledPlugins ≠ 링크 (--repair, 링크 기준)")
            errors, warnings = validate_convention(clone_dir)
            issues.extend(f"규약 위반: {error}" for error in errors)
            issues.extend(f"규약 권장: {warning}" for warning in warnings)
        return PluginStatus(org, name, link_name or native_entry, state,
                            tuple(issues))

    def repair(self) -> List[str]:
        """드리프트 교정 (§6.4) — 파괴적이지 않은 정리만 수행한다.

        깨진 링크 제거, clone 없는 native 등록 제거, native형의
        enabledPlugins를 **링크 기준으로** 재동기화, 잔존 키 정리.
        clone 삭제는 하지 않는다(uninstall의 몫).

        Returns:
            수행한 조치 설명 목록.
        """
        actions: List[str] = []
        actions.extend(f"깨진 링크 제거: {link_name}"
                       for link_name in self._links.remove_dangling())
        for entry_name, source in list(self._registry.registered().items()):
            parsed = parse_source(source)
            if parsed is None or not self._paths.plugin_clone_dir(
                    *parsed).is_dir():
                self._registry.unregister(entry_name)
                actions.append(f"native 등록 제거: {entry_name} (clone 없음)")
                continue
            linked = self._links.is_enabled(*parsed)
            if self._registry.is_enabled(entry_name) != linked:
                self._registry.set_enabled(entry_name, linked)
                actions.append(
                    f"enabledPlugins 재동기화: {entry_name} → {linked}"
                    " (링크 기준 §6.4)")
        actions.extend(f"enabledPlugins 정리: {key}"
                       for key in self._registry.prune_enabled_keys())
        return actions

    # --- 내부 ---

    def _disk_clones(self) -> Set[Tuple[str, str]]:
        found: Set[Tuple[str, str]] = set()
        plugins_dir = self._paths.plugins_dir
        if not plugins_dir.is_dir():
            return found
        for org_dir in plugins_dir.iterdir():
            if not org_dir.is_dir():
                continue
            for plugin_dir in org_dir.iterdir():
                if plugin_dir.is_dir():
                    found.add((org_dir.name, plugin_dir.name))
        return found

    def _registered_org_names(self) -> Set[str]:
        data = self._orgs_store.read()
        entries = data.get("orgs", []) if isinstance(data, dict) else []
        return {entry.get("name") for entry in entries}
