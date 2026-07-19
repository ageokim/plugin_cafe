"""공용 fake services — CLI(M4)·API(M5) 계약 테스트가 공유 (§13.3).

루트 conftest가 이 디렉토리를 sys.path에 넣는다 → `from fakes import …`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from pm.errors import AuthError
from pm.models import Org, OrgKind, Plugin, PluginState, Preset, utc_now_iso
from pm.services.auth_service import LoginResult
from pm.services.inspect_service import PluginStatus
from pm.services.install_service import InstallResult
from pm.services.preset_service import MemberResult, PresetBadge


def make_plugin(org: str, name: str, description: str = "",
                has_tags: bool = True) -> Plugin:
    return Plugin(name=name, org=org,
                  github_addr=f"https://ghes/{org}/{name}",
                  clone_url=f"https://ghes/{org}/{name}.git",
                  description=description, private=False,
                  has_tags=has_tags)


class FakeCatalogService:

    def __init__(self, plugins: Optional[List[Plugin]] = None) -> None:
        self.plugins = list(plugins or [])
        self.scanned: List[Optional[str]] = []

    def scan(self, org_name=None) -> Dict[str, List[Plugin]]:
        self.scanned.append(org_name)
        return self.cached(org_name, include_all=True)

    def cached(self, org_name=None,
               include_all: bool = False) -> Dict[str, List[Plugin]]:
        result: Dict[str, List[Plugin]] = {}
        for plugin in self.plugins:
            if org_name is not None and plugin.org != org_name:
                continue
            if not include_all and not plugin.has_tags:
                continue
            result.setdefault(plugin.org, []).append(plugin)
        return result

    def find(self, identifier: str) -> List[Plugin]:
        if "/" in identifier:
            org, _, name = identifier.partition("/")
            return [p for p in self.plugins
                    if p.org == org and p.name == name]
        return [p for p in self.plugins if p.name == identifier]


class FakeActivationService:

    def __init__(self) -> None:
        self.states: Dict[Tuple[str, str], PluginState] = {}
        self.calls: List[Tuple[str, str, str]] = []

    def state(self, org: str, name: str) -> PluginState:
        return self.states.get((org, name), PluginState.AVAILABLE)

    def enable(self, org: str, name: str) -> None:
        self.calls.append(("enable", org, name))
        self.states[(org, name)] = PluginState.ENABLED

    def disable(self, org: str, name: str) -> None:
        self.calls.append(("disable", org, name))
        self.states[(org, name)] = PluginState.INSTALLED


class FakeInstallService:

    def __init__(self) -> None:
        self.calls: List[Tuple[str, ...]] = []

    def install(self, plugin: Plugin, enable: bool = True) -> InstallResult:
        self.calls.append(("install", plugin.ref, str(enable)))
        return InstallResult(plugin=plugin, entry_name=plugin.name,
                             enabled=enable)

    def uninstall(self, org: str, name: str) -> None:
        self.calls.append(("uninstall", org, name))

    def update(self, org: str, name: str) -> str:
        self.calls.append(("update", org, name))
        return "abc1234"


class FakeOrgService:

    def __init__(self) -> None:
        self.orgs: List[Org] = []
        self.removed: List[str] = []
        self.add_error: Optional[Exception] = None

    def add(self, url_text: str) -> Org:
        if self.add_error is not None:
            raise self.add_error
        name = url_text.rstrip("/").rsplit("/", 1)[-1]
        org = Org(name=name, url=url_text, host="ghes", kind=OrgKind.ORG,
                  added_at=utc_now_iso())
        self.orgs.append(org)
        return org

    def list_orgs(self) -> List[Org]:
        return list(self.orgs)

    def remove(self, name: str):
        self.removed.append(name)
        return 2, 1  # (설치본, preset 멤버) 함께 정리 수 (§12.2)

    def revalidate_all(self) -> Dict[str, bool]:
        return {org.name: True for org in self.orgs}


class FakeInspectService:

    def __init__(self, statuses: Optional[List[PluginStatus]] = None) -> None:
        self.statuses = list(statuses or [])

    def report(self) -> List[PluginStatus]:
        return list(self.statuses)

    def repair(self) -> List[str]:
        return ["repaired: marketplace 재동기화"]


class FakePresetService:

    def __init__(self) -> None:
        self.presets: Dict[str, Preset] = {}
        self.batch_results: List[MemberResult] = []

    def create(self, name: str) -> Preset:
        preset = Preset(name=name, members=(), created_at=utc_now_iso())
        self.presets[name] = preset
        return preset

    def delete(self, name: str) -> None:
        self.presets.pop(name, None)

    def add_member(self, preset_name: str, ref: str) -> Preset:
        preset = self.presets[preset_name]
        preset = Preset(name=preset.name, members=preset.members + (ref,),
                        created_at=preset.created_at)
        self.presets[preset_name] = preset
        return preset

    def remove_member(self, preset_name: str, ref: str) -> Preset:
        preset = self.presets[preset_name]
        members = tuple(m for m in preset.members if m != ref)
        preset = Preset(name=preset.name, members=members,
                        created_at=preset.created_at)
        self.presets[preset_name] = preset
        return preset

    def list_presets(self) -> List[Preset]:
        return list(self.presets.values())

    def badge(self, name: str) -> PresetBadge:
        return PresetBadge.OFF

    def install(self, name: str) -> List[MemberResult]:
        return list(self.batch_results)

    enable = disable = uninstall = apply = install


class FakeAuthService:
    """§10.2 로그인·미검증 세션 흐름의 계약만 흉내."""

    def __init__(self) -> None:
        self.saved: Optional[Dict[str, str]] = None
        self.unverified = False
        self.login_error: Optional[Exception] = None
        self.logged_out = False

    def login(self, user_id: str, token: str) -> LoginResult:
        if self.login_error is not None:
            raise self.login_error
        if self.unverified:
            return LoginResult(verified=False)
        self.saved = {"id": user_id, "token": token}
        return LoginResult(verified=True, login=user_id, first_save=True)

    def load_saved(self) -> Optional[Dict[str, str]]:
        return self.saved

    def current_id(self) -> Optional[str]:
        return self.saved["id"] if self.saved else None

    def current_token(self) -> Optional[str]:
        return self.saved["token"] if self.saved else None

    def is_unverified(self) -> bool:
        return self.unverified

    def verify_current(self, host=None) -> str:
        if self.login_error is not None:
            raise self.login_error
        if not self.saved:
            raise AuthError("저장된 로그인 없음")
        return self.saved["id"]

    def logout(self) -> None:
        self.saved = None
        self.logged_out = True


class FakeConfig:

    def __init__(self, **values) -> None:
        self.github_host = values.get("github_host")
        self.flask_port = values.get("flask_port", 8765)
        self.plugin_tags = values.get("plugin_tags", ["#plugin", "#release"])
        self.ca_bundle = None
        self.http_timeout = 5.0
        self.github_api_base = None


class FakeChatBackend:
    """SSE 챗 백엔드 fake — 대본을 재생하고 호출을 기록 (§12.3)."""

    def __init__(self, script: Optional[List[dict]] = None) -> None:
        self.script = script or [
            {"type": "delta", "text": "안녕"},
            {"type": "done", "session_id": "sess-1"},
        ]
        self.calls: List[Tuple[str, Optional[str]]] = []

    def stream(self, message: str, session_id: Optional[str] = None):
        self.calls.append((message, session_id))
        return iter(self.script)


class FakeTerminalSession:

    def __init__(self) -> None:
        self.session_id = "term-1"
        self.written: List[str] = []
        self.closed = False

    def read(self, timeout: float = 0.1) -> bytes:
        del timeout
        raise OSError("fake 세션 — 읽을 것 없음")

    def write(self, data: str) -> None:
        self.written.append(data)

    def resize(self, rows: int, cols: int) -> None:
        pass

    def alive(self) -> bool:
        return not self.closed

    def close(self) -> None:
        self.closed = True


class FakeTerminalManager:

    def __init__(self) -> None:
        self.sessions: List[FakeTerminalSession] = []
        self.closed_all = False

    def create(self) -> FakeTerminalSession:
        session = FakeTerminalSession()
        self.sessions.append(session)
        return session

    def discard(self, session_id: str) -> None:
        pass

    def close_all(self) -> None:
        self.closed_all = True


class FakeContainer:
    """cli.main / api.create_app에 주입되는 최소 조립체."""

    def __init__(self, tmp_paths, config: Optional[FakeConfig] = None) -> None:
        self.paths = tmp_paths
        self.config = config if config is not None else FakeConfig()
        self.auth = FakeAuthService()
        self.catalog_service = FakeCatalogService()
        self.activation_service = FakeActivationService()
        self.install_service = FakeInstallService()
        self.org_service = FakeOrgService()
        self.inspect_service = FakeInspectService()
        self.preset_service = FakePresetService()
