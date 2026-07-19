"""하이브리드 등록의 핵심 — Claude Code 네이티브 위임 (Architecture.md §6).

pm은 marketplace.json 항목과 settings.local.json의 ``enabledPlugins`` 만
다룬다. settings.local.json의 다른 키(env·permissions 등)는 보존한다.
구현은 settings 파일 직접 편집 — `claude plugin` CLI 위임으로 바꿔도
이 클래스 뒤에 숨는다(§6.2 OCP).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pm.errors import RegistryError
from pm.store.json_store import JsonStore

logger = logging.getLogger(__name__)

MARKETPLACE_NAME = "plugin-cafe"  # §6.3 — 브랜드 "Plugin Cafe"의 소문자-하이픈 식별자 (디렉토리명과 무관)

# 부록 A.3 — 최소 1개 제공해야 하는 컴포넌트
_COMPONENTS = ("commands", "agents", "skills", "hooks", ".mcp.json")


def plugin_source(org: str, name: str) -> str:
    """marketplace 항목의 source — 상대경로라 저장소를 옮겨도 유효 (§6.2)."""
    return f"./plugins/{org}/{name}"


def parse_source(source: str) -> Optional[Tuple[str, str]]:
    """``./plugins/{org}/{name}`` → (org, name). 형식이 다르면 None."""
    parts = source.split("/")
    if len(parts) == 4 and parts[0] == "." and parts[1] == "plugins":
        if parts[2] and parts[3]:
            return parts[2], parts[3]
    return None


def detect_profile(clone_dir: Path) -> str:
    """프로파일 자동 감지 (§6.1 표).

    Returns:
        "native" (``.claude-plugin/plugin.json`` 보유 — marketplace 병행)
        또는 "standalone" (기본 — 링크만. 사내 표준 구조 ``plugin/`` 포함,
        부록 A.2).
    """
    manifest = clone_dir / ".claude-plugin" / "plugin.json"
    return "native" if manifest.is_file() else "standalone"


def _load_manifest(path: Path) -> Optional[Dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return data if isinstance(data, dict) else None


def manifest_name(clone_dir: Path) -> Optional[str]:
    """링크명으로 쓸 매니페스트 name (§6.2·부록 A.2).

    사내 매니페스트(``plugin/plugin.json``) 우선, native
    (``.claude-plugin/plugin.json``) 차선 — 없거나 파싱 불가면 None
    (호출자는 repo명으로 폴백).
    """
    for relative in ("plugin/plugin.json", ".claude-plugin/plugin.json"):
        data = _load_manifest(clone_dir / relative)
        if data and isinstance(data.get("name"), str) and data["name"]:
            return data["name"]
    return None


def validate_inhouse(clone_dir: Path) -> List[str]:
    """사내 표준 구조 검사 — **권장 경고만** (부록 A.2·A.4, 차단 없음)."""
    warnings: List[str] = []
    manifest_path = clone_dir / "plugin" / "plugin.json"
    if not manifest_path.is_file():
        warnings.append(
            "사내 표준 구조 미보유 — plugin/plugin.json 권장 (부록 A.2)")
        return warnings
    data = _load_manifest(manifest_path)
    if data is None:
        warnings.append("plugin/plugin.json 파싱 불가 (부록 A.2)")
        return warnings
    declared = data.get("name")
    if not declared:
        warnings.append("plugin/plugin.json에 name 없음 (부록 A.2)")
    elif declared != clone_dir.name:
        warnings.append(
            f"plugin/plugin.json name({declared}) ≠ repo명({clone_dir.name})"
            " — 링크명은 매니페스트 name을 따른다 (§6.2)")
    return warnings


def validate_convention(clone_dir: Path) -> Tuple[List[str], List[str]]:
    """native 프로파일 규약 검사 → (오류, 경고) (부록 A.3·A.4).

    standalone repo에는 호출하지 않는다 — 검사할 것이 없다(부록 A.2).
    오류(설치 차단): plugin.json 파싱 불가·name 부재, 컴포넌트 없음.
    경고(권장 위반): plugin.json name ≠ repo 디렉토리명.
    """
    errors: List[str] = []
    warnings: List[str] = []
    manifest = clone_dir / ".claude-plugin" / "plugin.json"
    if not manifest.is_file():
        errors.append(".claude-plugin/plugin.json 없음 (부록 A.2)")
    else:
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            declared = data.get("name") if isinstance(data, dict) else None
            if not declared:
                errors.append("plugin.json에 name 없음 (부록 A.2)")
            elif declared != clone_dir.name:
                warnings.append(
                    f"plugin.json name({declared}) ≠ repo명({clone_dir.name})"
                    " — 권장 불일치 (부록 A.2)")
        except (ValueError, OSError):
            errors.append("plugin.json 파싱 불가 (부록 A.2)")
    if not any((clone_dir / component).exists() for component in _COMPONENTS):
        errors.append(
            "제공 컴포넌트 없음 — commands/agents/skills/hooks/.mcp.json 중"
            " 1개 필요 (부록 A.3)")
    return errors, warnings


class ClaudePluginRegistry:
    """marketplace.json 생성·갱신 + enabledPlugins 토글 (§5·§6.2).

    Args:
        marketplace_store: ``.claude-plugin/marketplace.json`` JsonStore.
        settings_store: ``.claude/settings.local.json`` JsonStore.
        marketplace_name: enabledPlugins 키의 ``@`` 뒤 부분.
    """

    def __init__(
        self,
        marketplace_store: JsonStore,
        settings_store: JsonStore,
        marketplace_name: str = MARKETPLACE_NAME,
    ) -> None:
        self._marketplace_store = marketplace_store
        self._settings_store = settings_store
        self._name = marketplace_name

    # --- marketplace 항목 (§6.2) ---

    def register(self, org: str, name: str) -> str:
        """항목을 추가하고 등록명을 돌려준다 — 재등록(update)은 멱등.

        이름 충돌 규칙: 기존 항목은 절대 리네임하지 않는다 — 신규만
        ``{org}-{name}`` 을 받는다 (기존 활성 상태 보존, §6.2).
        """
        data = self._read_marketplace()
        plugins = data["plugins"]
        source = plugin_source(org, name)
        for entry in plugins:
            if entry.get("source") == source:
                return entry["name"]  # 멱등 재등록 — update 흐름
        entry_name = name
        if any(entry.get("name") == name for entry in plugins):
            entry_name = f"{org}-{name}"
        if any(entry.get("name") == entry_name for entry in plugins):
            raise RegistryError(f"이름 충돌을 해소할 수 없습니다: {entry_name}")
        plugins.append({"name": entry_name, "source": source})
        self._marketplace_store.write(data)
        return entry_name

    def unregister(self, entry_name: str) -> None:
        """enabledPlugins 키 제거 → marketplace 항목 제거 (§6.2 순서)."""
        self._remove_enabled_key(entry_name)
        data = self._read_marketplace()
        kept = [e for e in data["plugins"] if e.get("name") != entry_name]
        if len(kept) == len(data["plugins"]):
            raise RegistryError(f"등록되지 않은 항목: {entry_name}")
        data["plugins"] = kept
        self._marketplace_store.write(data)

    def registered(self) -> Dict[str, str]:
        """등록 전체 — {등록명: source}."""
        return {
            entry["name"]: entry.get("source", "")
            for entry in self._read_marketplace()["plugins"]
            if entry.get("name")
        }

    def entry_for(self, org: str, name: str) -> Optional[str]:
        """source(정체성) 기준 조회 — 등록명 또는 None."""
        source = plugin_source(org, name)
        for entry_name, entry_source in self.registered().items():
            if entry_source == source:
                return entry_name
        return None

    def entry_source(self, entry_name: str) -> Optional[str]:
        return self.registered().get(entry_name)

    # --- enabledPlugins (§6.2·§8.7) ---

    def set_enabled(self, entry_name: str, enabled: bool) -> None:
        """``{등록명}@{marketplace}`` 키를 토글한다.

        Raises:
            RegistryError: marketplace 미등록 항목.
        """
        if self.entry_source(entry_name) is None:
            raise RegistryError(f"marketplace에 등록되지 않음: {entry_name}")
        settings = self._read_settings()
        settings.setdefault("enabledPlugins", {})[self._key(entry_name)] = (
            enabled)
        self._settings_store.write(settings)

    def is_enabled(self, entry_name: str) -> bool:
        enabled_map = self._read_settings().get("enabledPlugins", {})
        return enabled_map.get(self._key(entry_name)) is True

    def prune_enabled_keys(self) -> List[str]:
        """등록이 사라진 enabledPlugins 키 정리 — 타 마켓플레이스 키는 불변.

        Returns:
            제거한 키 목록 (inspect --repair 리포트용, §6.4).
        """
        settings = self._read_settings()
        enabled_map = settings.get("enabledPlugins", {})
        valid = {self._key(entry) for entry in self.registered()}
        suffix = "@" + self._name
        stale = [
            key for key in enabled_map
            if key.endswith(suffix) and key not in valid
        ]
        if stale:
            for key in stale:
                del enabled_map[key]
            self._settings_store.write(settings)
        return stale

    # --- 내부 ---

    def _key(self, entry_name: str) -> str:
        return f"{entry_name}@{self._name}"

    def _read_marketplace(self) -> Dict:
        data = self._marketplace_store.read()
        if not isinstance(data, dict):
            data = {}
        data.setdefault("name", self._name)
        data.setdefault("plugins", [])
        return data

    def _read_settings(self) -> Dict:
        data = self._settings_store.read()
        return data if isinstance(data, dict) else {}

    def _remove_enabled_key(self, entry_name: str) -> None:
        settings = self._read_settings()
        enabled_map = settings.get("enabledPlugins", {})
        if self._key(entry_name) in enabled_map:
            del enabled_map[self._key(entry_name)]
            self._settings_store.write(settings)
