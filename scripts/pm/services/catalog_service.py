"""카탈로그 스캔·조회 (Architecture.md §5·§7·§8.3).

스캔은 보이는 repo **전부**를 has_tags 플래그와 함께 저장하고,
출력 시에만 태그 필터를 적용한다 — ``--cached``/``--all`` 이 같은
캐시에서 동작한다(재스캔 없음).
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from pm.config import ConfigProvider
from pm.errors import PmError
from pm.github.client import GitHubClient
from pm.github.scanner import has_plugin_tags
from pm.models import Plugin, utc_now_iso
from pm.services.auth_service import AuthService
from pm.services.org_service import OrgService
from pm.store.json_store import JsonStore

logger = logging.getLogger(__name__)


class CatalogService:
    """스캔 캐시(data/plugins.json)의 유일한 관리자 (§5 PluginCatalog).

    Args:
        config: ConfigProvider — plugin_tags.
        catalog_store: §8.3 JsonStore.
        org_service: 등록 org 목록 공급.
        client_factory: ``(host 또는 None) → GitHubClient``.
        auth: viewer login(본인 판정 §10.1) 공급.
        now_factory: scanned_at 타임스탬프.
    """

    def __init__(
        self,
        config: ConfigProvider,
        catalog_store: JsonStore,
        org_service: OrgService,
        client_factory: Callable[[Optional[str]], GitHubClient],
        auth: AuthService,
        now_factory: Callable[[], str] = utc_now_iso,
    ) -> None:
        self._config = config
        self._catalog_store = catalog_store
        self._org_service = org_service
        self._client_factory = client_factory
        self._auth = auth
        self._now = now_factory

    def scan(self,
             org_name: Optional[str] = None) -> Dict[str, List[Plugin]]:
        """org 스캔 → 카탈로그 갱신(org별 병합) → 전체 목록 반환.

        Args:
            org_name: 지정 시 그 org만 재스캔 — 다른 org 캐시는 보존.

        Raises:
            PmError: 지정 org가 등록돼 있지 않음.
            AuthError/GitHubError: API 실패 (§10.2 라우팅).
        """
        orgs = self._org_service.list_orgs()
        if org_name is not None:
            orgs = [org for org in orgs if org.name == org_name]
            if not orgs:
                raise PmError(f"등록되지 않은 org: {org_name}")
        client = self._client_factory(None)
        viewer = self._auth.current_id()
        tags = self._config.plugin_tags
        data = self._catalog_store.read()
        if not isinstance(data, dict):
            data = {}
        orgs_map = data.setdefault("orgs", {})
        result: Dict[str, List[Plugin]] = {}
        for org in orgs:
            repos = client.fetch_repos(org.name, org.kind,
                                       viewer_login=viewer)
            plugins = [
                Plugin(
                    name=repo["name"],
                    org=org.name,
                    github_addr=repo["html_url"],
                    clone_url=repo["clone_url"],
                    description=repo["description"],
                    private=repo["private"],
                    has_tags=has_plugin_tags(repo["description"], tags),
                ) for repo in repos
            ]
            orgs_map[org.name] = {
                "scanned_at": self._now(),
                "plugins": [plugin.to_dict() for plugin in plugins],
            }
            result[org.name] = plugins
        data["updated_at"] = self._now()
        self._catalog_store.write(data)
        return result

    def cached(
        self,
        org_name: Optional[str] = None,
        include_all: bool = False,
    ) -> Dict[str, List[Plugin]]:
        """캐시 조회 — 기본은 태그 통과분만, include_all이면 전부 (§7)."""
        data = self._catalog_store.read()
        orgs_map = data.get("orgs", {}) if isinstance(data, dict) else {}
        result: Dict[str, List[Plugin]] = {}
        for name, entry in orgs_map.items():
            if org_name is not None and name != org_name:
                continue
            plugins = [
                Plugin.from_dict(item) for item in entry.get("plugins", [])
            ]
            if not include_all:
                plugins = [p for p in plugins if p.has_tags]
            result[name] = plugins
        return result

    def find(self, identifier: str) -> List[Plugin]:
        """식별자 해석 (§7) — ``org/name`` 정확 일치 또는 bare name 전 org 검색.

        bare name의 유일성 판정(후보 여러 개 → 오류)은 호출자(CLI)의 몫.
        """
        catalog = self.cached(include_all=True)
        if "/" in identifier:
            org, _, name = identifier.partition("/")
            return [
                plugin for plugins in catalog.values() for plugin in plugins
                if plugin.org == org and plugin.name == name
            ]
        return [
            plugin for plugins in catalog.values() for plugin in plugins
            if plugin.name == identifier
        ]
