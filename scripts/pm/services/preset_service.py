"""Preset — 플러그인 묶음 CRUD·일괄 오케스트레이션 (Architecture.md §6.5).

정의만 저장(§8.5)하고 상태는 실측 도출. 일괄 실행은 부분 실패 무중단 —
멤버별 결과를 수집해 돌려주고, 한 멤버의 실패가 나머지를 막지 않는다.
등록 메커니즘 자체(§6.2)는 기존 install/activation services를 호출한다.
"""

from __future__ import annotations

import dataclasses
import enum
import logging
from typing import Callable, List, Optional

from pm.claudeplug.registry import ClaudePluginRegistry
from pm.errors import PmError
from pm.models import Plugin, PluginState, Preset, utc_now_iso
from pm.services.activation_service import ActivationService
from pm.services.catalog_service import CatalogService
from pm.services.install_service import InstallService
from pm.store.json_store import JsonStore

logger = logging.getLogger(__name__)


class PresetBadge(enum.Enum):
    """도출 상태 뱃지 (§12.2) — 전부 켜짐● / 일부◐ / 꺼짐○."""

    ALL_ON = "all-on"
    PARTIAL = "partial"
    OFF = "off"


@dataclasses.dataclass(frozen=True)
class MemberResult:
    """일괄 실행에서 멤버 하나의 결과 (§6.5 요약 리포트)."""

    ref: str
    # installed·enabled·disabled·uninstalled·skipped·failed·broken-ref
    action: str
    ok: bool
    detail: str = ""


class PresetService:
    """preset CRUD + 일괄 실행 + apply(전환) (§6.5).

    Args:
        presets_store: §8.5 JsonStore.
        catalog: 멤버 ref → Plugin 해석.
        install: 설치/삭제 위임.
        activation: 켜기/끄기·상태 실측 위임.
        registry: apply의 "멤버 외 설치본" 열거용.
        now_factory: created_at 타임스탬프.
    """

    def __init__(
        self,
        presets_store: JsonStore,
        catalog: CatalogService,
        install: InstallService,
        activation: ActivationService,
        registry: ClaudePluginRegistry,
        now_factory: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._store = presets_store
        self._catalog = catalog
        self._install = install
        self._activation = activation
        self._registry = registry
        self._now = now_factory

    # --- CRUD (§6.5 — 정의 삭제 ≠ 멤버 삭제) ---

    def list_presets(self) -> List[Preset]:
        data = self._store.read()
        entries = data.get("presets", []) if isinstance(data, dict) else []
        return [Preset.from_dict(entry) for entry in entries]

    def get(self, name: str) -> Preset:
        """Raises PmError: 없는 preset."""
        for preset in self.list_presets():
            if preset.name == name:
                return preset
        raise PmError(f"없는 preset: {name}")

    def create(self, name: str) -> Preset:
        """Raises PmError: 이름 누락·중복 (§8.5 이름 유일)."""
        name = name.strip()
        if not name:
            raise PmError("preset 이름을 입력하세요")
        if any(preset.name == name for preset in self.list_presets()):
            raise PmError(f"이미 있는 preset: {name}")
        preset = Preset(name=name, members=(), created_at=self._now())
        self._store.update(lambda data: self._append(data, preset))
        return preset

    def delete(self, name: str) -> None:
        """정의만 제거 — 플러그인은 그대로 (§6.5)."""
        self.get(name)  # 존재 확인
        self._store.update(lambda data: {
            "presets": [
                entry for entry in data.get("presets", [])
                if entry.get("name") != name
            ]
        })

    def add_member(self, preset_name: str, ref: str) -> Preset:
        """멤버 추가 — ref는 ``org/name`` 형식 강제 (§6.5 단위=플러그인).

        Raises:
            PmError: 형식 위반·중복 멤버·없는 preset.
        """
        ref = ref.strip()
        org, sep, plugin_name = ref.partition("/")
        if not sep or not org or not plugin_name or "/" in plugin_name:
            raise PmError(f"멤버는 org/name 형식이어야 합니다: {ref!r}")
        preset = self.get(preset_name)
        if ref in preset.members:
            raise PmError(f"이미 멤버입니다: {ref}")
        updated = Preset(name=preset.name,
                         members=preset.members + (ref,),
                         created_at=preset.created_at)
        self._replace(updated)
        return updated

    def remove_member(self, preset_name: str, ref: str) -> Preset:
        """Raises PmError: 멤버가 아님·없는 preset."""
        preset = self.get(preset_name)
        if ref not in preset.members:
            raise PmError(f"멤버가 아닙니다: {ref}")
        updated = Preset(
            name=preset.name,
            members=tuple(m for m in preset.members if m != ref),
            created_at=preset.created_at,
        )
        self._replace(updated)
        return updated

    def remove_members_of_org(self, org: str) -> int:
        """org 삭제 경로의 멤버 정리 (§12.2) — 해당 org의 멤버를 전
        preset에서 제거하고 제거된 멤버 수를 반환. preset 정의 자체는
        비워져도 유지한다(정의 삭제는 별개 동작 §6.5).

        일반적인 '깨진 참조'는 자동 삭제하지 않지만(§6.5 — 일시 상태일
        수 있음), org 삭제는 사용자가 확인한 명시적 파괴 동작이므로
        참조도 함께 정리한다.
        """
        prefix = f"{org}/"
        removed = 0
        for preset in self.list_presets():
            kept = tuple(m for m in preset.members
                         if not m.startswith(prefix))
            if len(kept) == len(preset.members):
                continue
            removed += len(preset.members) - len(kept)
            self._replace(Preset(name=preset.name, members=kept,
                                 created_at=preset.created_at))
        return removed

    # --- 상태 뱃지 (§6.5 실측 도출) ---

    def badge(self, name: str) -> PresetBadge:
        """멤버 상태 실측으로 뱃지를 도출한다 — 저장 상태 없음 (§6.5)."""
        preset = self.get(name)
        if not preset.members:
            return PresetBadge.OFF
        enabled = sum(1 for ref in preset.members
                      if self._state(ref) is PluginState.ENABLED)
        if enabled == len(preset.members):
            return PresetBadge.ALL_ON
        return PresetBadge.PARTIAL if enabled else PresetBadge.OFF

    # --- 일괄 실행 (§6.5 — 부분 실패 무중단) ---

    def install(self, name: str) -> List[MemberResult]:
        """미설치 멤버만 설치."""
        return self._for_each(name, self._install_member)

    def enable(self, name: str) -> List[MemberResult]:
        """미설치 멤버는 자동 설치 후 켜기 — 세트가 바로 동작하는 상태 보장."""
        return self._for_each(name, self._enable_member)

    def disable(self, name: str) -> List[MemberResult]:
        """켜진 멤버 끄기."""
        return self._for_each(name, self._disable_member)

    def uninstall(self, name: str) -> List[MemberResult]:
        """멤버 전체 삭제 — 확인 UX는 presentation 몫 (웹 인라인 §12.2)."""
        return self._for_each(name, self._uninstall_member)

    def apply(self, name: str) -> List[MemberResult]:
        """전환: 멤버 전부 켜기 + 멤버 외 설치본 전부 끄기 (비파괴, §6.5).

        설치본 열거는 디스크 실측(§6.4) — 링크 1급이라 native 등록 여부와
        무관하게 standalone 설치본도 전환 대상이 된다.
        """
        results = self._for_each(name, self._enable_member)
        members = set(self.get(name).members)
        for org, plugin_name in self._activation.installed_refs():
            ref = f"{org}/{plugin_name}"
            if ref in members:
                continue
            if self._activation.state(org,
                                      plugin_name) is not PluginState.ENABLED:
                continue
            try:
                self._activation.disable(org, plugin_name)
                results.append(
                    MemberResult(ref, "disabled", True, "preset 외 — 전환"))
            except PmError as e:
                results.append(MemberResult(ref, "failed", False, str(e)))
        return results

    # --- 멤버 단위 동작 ---

    def _install_member(self, ref: str) -> MemberResult:
        if self._state(ref) is not PluginState.AVAILABLE:
            return MemberResult(ref, "skipped", True, "이미 설치됨")
        plugin = self._resolve(ref)
        if plugin is None:
            return self._broken(ref)
        self._install.install(plugin, enable=False)
        return MemberResult(ref, "installed", True)

    def _enable_member(self, ref: str) -> MemberResult:
        state = self._state(ref)
        if state is PluginState.ENABLED:
            return MemberResult(ref, "skipped", True, "이미 켜짐")
        if state is PluginState.AVAILABLE:
            plugin = self._resolve(ref)
            if plugin is None:
                return self._broken(ref)
            self._install.install(plugin, enable=True)  # 자동 설치 (§6.5)
            return MemberResult(ref, "installed+enabled", True)
        org, _, plugin_name = ref.partition("/")
        self._activation.enable(org, plugin_name)
        return MemberResult(ref, "enabled", True)

    def _disable_member(self, ref: str) -> MemberResult:
        if self._state(ref) is not PluginState.ENABLED:
            return MemberResult(ref, "skipped", True, "켜져 있지 않음")
        org, _, plugin_name = ref.partition("/")
        self._activation.disable(org, plugin_name)
        return MemberResult(ref, "disabled", True)

    def _uninstall_member(self, ref: str) -> MemberResult:
        if self._state(ref) is PluginState.AVAILABLE:
            return MemberResult(ref, "skipped", True, "설치돼 있지 않음")
        org, _, plugin_name = ref.partition("/")
        self._install.uninstall(org, plugin_name)
        return MemberResult(ref, "uninstalled", True)

    # --- 내부 ---

    def _for_each(
        self,
        name: str,
        action: Callable[[str], MemberResult],
    ) -> List[MemberResult]:
        """멤버 순회 — 한 멤버의 실패가 나머지를 막지 않는다 (§6.5)."""
        results: List[MemberResult] = []
        for ref in self.get(name).members:
            try:
                results.append(action(ref))
            except PmError as e:
                logger.warning("preset 멤버 실패(계속 진행): %s — %s", ref, e)
                results.append(MemberResult(ref, "failed", False, str(e)))
        return results

    def _state(self, ref: str) -> PluginState:
        org, _, plugin_name = ref.partition("/")
        return self._activation.state(org, plugin_name)

    def _resolve(self, ref: str) -> Optional[Plugin]:
        matches = self._catalog.find(ref)
        return matches[0] if matches else None

    @staticmethod
    def _broken(ref: str) -> MemberResult:
        return MemberResult(
            ref, "broken-ref", False,
            "카탈로그에 없음 — org 미등록·소멸, preset 편집에서 정리 (§6.5)")

    def _replace(self, preset: Preset) -> None:
        def _mutate(data):
            entries = data.get("presets", []) if isinstance(data, dict) else []
            return {
                "presets": [
                    preset.to_dict()
                    if entry.get("name") == preset.name else entry
                    for entry in entries
                ]
            }

        self._store.update(_mutate)

    @staticmethod
    def _append(data, preset: Preset):
        merged = data if isinstance(data, dict) else {}
        merged.setdefault("presets", []).append(preset.to_dict())
        return merged
