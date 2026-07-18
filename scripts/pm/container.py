"""조립 루트 (Architecture.md §2.2·§4).

**여기서만** 구현체를 생성·주입한다 — 다른 어떤 모듈도 구체 클래스를
만들거나 os.environ·전역 설정을 직접 읽지 않는다(DIP). CLI(M4)와
Flask API(M5)는 Container 하나를 만들어 services를 꺼내 쓴다.
"""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional

from pm.claudeplug.links import PluginLinks
from pm.claudeplug.registry import MARKETPLACE_NAME, ClaudePluginRegistry
from pm.config import ConfigProvider
from pm.errors import ConfigError
from pm.github.rest_client import RestGitHubClient
from pm.github.urls import ApiUrlBuilder
from pm.gitops import SubprocessGitRunner
from pm.paths import ProjectPaths
from pm.services.activation_service import ActivationService
from pm.services.auth_service import AuthService
from pm.services.catalog_service import CatalogService
from pm.services.install_service import InstallService
from pm.services.inspect_service import InspectService
from pm.services.org_service import OrgService
from pm.services.preset_service import PresetService
from pm.store.json_store import JsonStore


class Container:
    """전 서비스 그래프의 유일한 조립 지점.

    Args:
        paths: 테스트에서 tmp ProjectPaths 주입. None이면 탐색(§9.3).
        env: 환경변수 매핑 — None이면 os.environ.
        cli_overrides: CLI 플래그 (§2.3 최우선 계층).
    """

    def __init__(
        self,
        paths: Optional[ProjectPaths] = None,
        env: Optional[Mapping[str, str]] = None,
        cli_overrides: Optional[Mapping[str, Any]] = None,
    ) -> None:
        environ = dict(env) if env is not None else dict(os.environ)
        self.paths = paths if paths is not None else ProjectPaths.discover(
            environ)

        # --- stores (§8) ---
        self.config_store = JsonStore(self.paths.config_file, default=dict)
        self.orgs_store = JsonStore(self.paths.orgs_file,
                                    default=lambda: {"orgs": []})
        self.catalog_store = JsonStore(
            self.paths.catalog_file,
            default=lambda: {"updated_at": None, "orgs": {}})
        self.credentials_store = JsonStore(self.paths.credentials_file,
                                           default=dict, secure=True)
        self.presets_store = JsonStore(self.paths.presets_file,
                                       default=lambda: {"presets": []})

        # --- config (§2.3) ---
        self.config = ConfigProvider(file_loader=self.config_store.read,
                                     env=environ,
                                     cli_overrides=cli_overrides)

        # --- infrastructure ---
        self.registry = ClaudePluginRegistry(
            marketplace_store=JsonStore(
                self.paths.marketplace_file,
                default=lambda: {"name": MARKETPLACE_NAME, "plugins": []}),
            settings_store=JsonStore(self.paths.claude_settings_local_file,
                                     default=dict),
        )
        self.links = PluginLinks(self.paths)
        self.auth = AuthService(self.credentials_store, self.github_client,
                                self.config)
        self.git = SubprocessGitRunner(
            token_provider=self.auth.current_token,
            ca_bundle_provider=lambda: self.config.ca_bundle,
        )

        # --- services (§4) ---
        self.install_service = InstallService(self.paths, self.git,
                                              self.registry, self.links)
        self.org_service = OrgService(self.config, self.config_store,
                                      self.orgs_store, self.github_client,
                                      self.auth,
                                      installer=self.install_service)
        self.catalog_service = CatalogService(self.config, self.catalog_store,
                                              self.org_service,
                                              self.github_client, self.auth)
        self.activation_service = ActivationService(self.registry, self.paths,
                                                    self.links)
        self.inspect_service = InspectService(self.paths, self.registry,
                                              self.orgs_store, self.links)
        self.preset_service = PresetService(self.presets_store,
                                            self.catalog_service,
                                            self.install_service,
                                            self.activation_service,
                                            self.registry)

    def github_client(self, host: Optional[str] = None) -> RestGitHubClient:
        """client factory — auth·org·catalog services에 결선된다.

        Args:
            host: 첫 org 추가처럼 아직 확정 전인 후보 host. None이면
                config의 확정 host.

        Raises:
            ConfigError: host를 알 수 없음 (§10.2 미검증 세션에서 org
                추가 전에 API가 필요한 경우는 설계상 없다).
        """
        target = host if host is not None else self.config.github_host
        if target is None:
            raise ConfigError(
                "GitHub host 미확정 — 첫 org URL을 추가하세요 (§10.2)")
        api_base = ApiUrlBuilder(self.config.github_api_base).api_base(target)
        return RestGitHubClient(
            api_base,
            token_provider=self.auth.current_token,
            ca_bundle=self.config.ca_bundle,
            timeout=self.config.http_timeout,
            per_page=self.config.github_per_page,
        )
