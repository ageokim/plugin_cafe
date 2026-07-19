"""services 테스트 공용 fake·조립 fixture (§13.3 — 네트워크·실 git 없음)."""

from __future__ import annotations

import json

import pytest

from pm.claudeplug.links import PluginLinks
from pm.claudeplug.registry import MARKETPLACE_NAME, ClaudePluginRegistry
from pm.config import ConfigProvider
from pm.errors import AuthError, GitHubError, GitOpsError
from pm.models import OrgKind
from pm.services.activation_service import ActivationService
from pm.services.auth_service import AuthService
from pm.services.catalog_service import CatalogService
from pm.services.install_service import InstallService
from pm.services.inspect_service import InspectService
from pm.services.org_service import OrgService
from pm.services.preset_service import PresetService
from pm.store.json_store import JsonStore

FIXED_NOW = "2026-07-15T00:00:00+00:00"
HOST = "github.xxx.xxx"


class FakeGitHubClient:
    """GitHubClient Protocol의 설정형 fake."""

    def __init__(self):
        self.login = "ageokim"
        self.fail_token = False
        self.org_kinds = {}
        self.memberships = set()
        self.repos = {}
        self.last_fetch = None

    def verify_token(self):
        if self.fail_token:
            raise AuthError("토큰이 유효하지 않습니다 (HTTP 401)")
        return self.login

    def resolve_target(self, name):
        if name in self.org_kinds:
            return self.org_kinds[name]
        raise GitHubError(f"계정을 찾을 수 없습니다: {name}")

    def fetch_repos(self, name, kind, viewer_login=None):
        self.last_fetch = (name, kind, viewer_login)
        return [dict(repo) for repo in self.repos.get(name, [])]

    def check_org_membership(self, org):
        return org in self.memberships


class RecordingGitRunner:
    """GitRunner fake — clone 시 규약을 만족하는 뼈대를 실제로 만든다."""

    def __init__(self):
        self.calls = []
        self.valid_plugin = True  # True=native 뼈대 / False=standalone(맨 repo)
        self.broken_native = False  # True=plugin.json은 있으나 name 없음
        self.inhouse_plugin = False  # True=사내 표준 구조(plugin/ 폴더)
        self.inhouse_name = None  # 사내 매니페스트 name override
        self.fail_urls = set()

    def clone(self, clone_url, dest):
        """fail_urls면 실패, 아니면 프로파일별 뼈대를 만든다 (§6.1)."""
        self.calls.append(("clone", clone_url, str(dest)))
        if clone_url in self.fail_urls:
            raise GitOpsError(f"clone 실패: {clone_url}")
        dest.mkdir(parents=True)
        if self.broken_native:
            manifest_dir = dest / ".claude-plugin"
            manifest_dir.mkdir()
            (manifest_dir / "plugin.json").write_text(
                json.dumps({"version": "0.1.0"}), encoding="utf-8")
        elif self.valid_plugin:
            manifest_dir = dest / ".claude-plugin"
            manifest_dir.mkdir()
            manifest = {"name": dest.name, "version": "0.1.0"}
            (manifest_dir / "plugin.json").write_text(
                json.dumps(manifest), encoding="utf-8")
            (dest / "skills").mkdir()
        elif self.inhouse_plugin:
            plugin_dir = dest / "plugin"
            plugin_dir.mkdir()
            (plugin_dir / "plugin.json").write_text(
                json.dumps({"name": self.inhouse_name or dest.name,
                            "version": "1.0.0"}), encoding="utf-8")
            (plugin_dir / "commands").mkdir()
            (plugin_dir / "commands" / "hello.md").write_text(
                "인사 명령", encoding="utf-8")
            (plugin_dir / "skills" / "greet").mkdir(parents=True)
            (plugin_dir / "skills" / "greet" / "SKILL.md").write_text(
                "---\nname: greet\n---\n", encoding="utf-8")
            (plugin_dir / "workflows").mkdir()
            (plugin_dir / "workflows" / "flow.js").write_text(
                "export const meta = {}", encoding="utf-8")
        else:
            (dest / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")

    def pull(self, repo_dir):
        self.calls.append(("pull", str(repo_dir)))

    def head_commit(self, repo_dir):
        self.calls.append(("head_commit", str(repo_dir)))
        return "abc1234"


class ServicesEnv:
    """tmp 경로 위에 전 서비스 그래프를 fake로 조립한 테스트 환경."""

    def __init__(self, paths):
        self.paths = paths
        self.github = FakeGitHubClient()
        self.git = RecordingGitRunner()

        def factory(host=None):  # noqa: ARG001 — Protocol 시그니처 맞춤
            del host
            return self.github

        self.config_store = JsonStore(paths.config_file, default=dict)
        self.orgs_store = JsonStore(paths.orgs_file,
                                    default=lambda: {"orgs": []})
        self.catalog_store = JsonStore(
            paths.catalog_file,
            default=lambda: {"updated_at": None, "orgs": {}})
        self.credentials_store = JsonStore(paths.credentials_file,
                                           default=dict, secure=True)
        self.presets_store = JsonStore(paths.presets_file,
                                       default=lambda: {"presets": []})
        self.marketplace_store = JsonStore(
            paths.marketplace_file,
            default=lambda: {"name": MARKETPLACE_NAME, "plugins": []})
        self.settings_store = JsonStore(paths.claude_settings_local_file,
                                        default=dict)

        self.config = ConfigProvider(file_loader=self.config_store.read,
                                     env={})
        self.registry = ClaudePluginRegistry(self.marketplace_store,
                                             self.settings_store)
        self.links = PluginLinks(paths)
        self.auth = AuthService(self.credentials_store, factory, self.config)

        def now():
            return FIXED_NOW
        self.install_service = InstallService(paths, self.git,
                                              self.registry, self.links)
        self.org_service = OrgService(self.config, self.config_store,
                                      self.orgs_store, factory, self.auth,
                                      now_factory=now,
                                      installer=self.install_service,
                                      preset_pruner=lambda org:
                                      self.preset_service
                                      .remove_members_of_org(org))
        self.catalog_service = CatalogService(self.config, self.catalog_store,
                                              self.org_service, factory,
                                              self.auth, now_factory=now)
        self.activation_service = ActivationService(self.registry, paths,
                                                    self.links)
        self.inspect_service = InspectService(paths, self.registry,
                                              self.orgs_store, self.links)
        self.preset_service = PresetService(self.presets_store,
                                            self.catalog_service,
                                            self.install_service,
                                            self.activation_service,
                                            self.registry, now_factory=now)

    # --- 시나리오 헬퍼 ---

    def login_and_register_org(self, org="org-a", kind=OrgKind.ORG):
        """미검증 로그인 → 첫 org 등록까지 (§10.2 최초 실행 흐름)."""
        self.github.org_kinds[org] = kind
        self.github.memberships.add(org)
        self.auth.login("ageokim", "ghp_x")
        return self.org_service.add(f"https://{HOST}/{org}")

    def register_extra_org(self, org, kind=OrgKind.ORG):
        self.github.org_kinds[org] = kind
        self.github.memberships.add(org)
        return self.org_service.add(org)

    def catalog_plugin(self, org="org-a", name="plugin-a", has_tags=True):
        """repo를 fake에 넣고 스캔해 Plugin을 돌려준다."""
        description = "데모 #plugin #release" if has_tags else "일반 repo"
        self.github.repos.setdefault(org, []).append({
            "name": name,
            "description": description,
            "private": False,
            "html_url": f"https://{HOST}/{org}/{name}",
            "clone_url": f"https://{HOST}/{org}/{name}.git",
        })
        self.catalog_service.scan(org)
        return self.catalog_service.find(f"{org}/{name}")[0]


@pytest.fixture
def env(tmp_paths):
    """전 서비스가 fake 위에 조립된 환경."""
    return ServicesEnv(tmp_paths)
