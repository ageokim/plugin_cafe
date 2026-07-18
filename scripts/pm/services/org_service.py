"""org 등록/삭제/재검증 (Architecture.md §10.2).

등록 게이트: URL 파싱 → 단일 host 정책 → (첫 org면 토큰·ID 검증) →
개인 계정 본인 확인 / org 멤버십 확인 → orgs.json 반영.
첫 org 성공 시 github_host를 config.json에 확정하고 보류 자격을 저장한다.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from pm.config import ConfigProvider
from pm.errors import AuthError, GitHubError, PmError
from pm.github.client import GitHubClient
from pm.github.urls import parse_target
from pm.models import Org, OrgKind, utc_now_iso
from pm.services.auth_service import AuthService
from pm.store.json_store import JsonStore

logger = logging.getLogger(__name__)


class OrgService:
    """org 등록·삭제·재검증 use case (§5).

    Args:
        config: ConfigProvider — github_host 정책.
        config_store: config.json JsonStore — 첫 org에서 host 확정 기록.
        orgs_store: orgs.json JsonStore (§8.2).
        client_factory: ``(host 또는 None) → GitHubClient``.
        auth: AuthService — 미검증 세션 처리(§10.2)·viewer 확인.
        now_factory: added_at 타임스탬프 (테스트 주입).
    """

    def __init__(
        self,
        config: ConfigProvider,
        config_store: JsonStore,
        orgs_store: JsonStore,
        client_factory: Callable[[Optional[str]], GitHubClient],
        auth: AuthService,
        now_factory: Callable[[], str] = utc_now_iso,
        installer=None,
    ) -> None:
        self._config = config
        self._config_store = config_store
        self._orgs_store = orgs_store
        self._client_factory = client_factory
        self._auth = auth
        self._now = now_factory
        self._installer = installer  # org 제거 시 설치본 정리 (§12.2)

    def list_orgs(self) -> List[Org]:
        data = self._orgs_store.read()
        entries = data.get("orgs", []) if isinstance(data, dict) else []
        return [Org.from_dict(entry) for entry in entries]

    def add(self, url_text: str) -> Org:
        """org URL 등록 — 권한 게이트 통과분만 orgs.json에 들어간다 (§10.2).

        Raises:
            AuthError: 토큰 무효·ID 불일치 → 로그인 창 복귀 라우팅.
            GitHubError: 다른 host·멤버십 거부·타인 개인계정 → 인라인 사유.
            PmError: 이미 등록된 org.
        """
        host, account = parse_target(url_text)
        target_host, first_org = self._resolve_host_policy(host)
        if any(org.name.lower() == account.lower()
               for org in self.list_orgs()):
            raise PmError(f"이미 등록된 org: {account}")

        # 미검증 세션이면 여기서 토큰·ID를 검증한다 (§10.2 첫 org 흐름)
        if self._auth.is_unverified():
            viewer = self._auth.verify_current(host=target_host)
        else:
            viewer = self._auth.current_id()
            if viewer is None:
                raise AuthError("로그인이 필요합니다")

        client = self._client_factory(target_host)
        kind = client.resolve_target(account)
        if kind is OrgKind.USER:
            if account.lower() != viewer.lower():
                raise GitHubError(
                    "개인 계정은 본인 계정만 등록할 수 있습니다 (§10.2)")
        elif not client.check_org_membership(account):
            raise GitHubError(f"권한 없음 — {account}의 활성 멤버십이 없습니다")

        resolved_host = (target_host
                         if first_org else self._config.github_host)
        if first_org:
            self._commit_host(resolved_host)
            if self._auth.is_unverified():
                self._auth.commit_pending()  # 이제 비로소 저장 (§10.2)
        org = Org(
            name=account,
            url=f"https://{resolved_host}/{account}",
            host=resolved_host,
            kind=kind,
            added_at=self._now(),
        )
        self._orgs_store.update(lambda data: self._append(data, org))
        return org

    def remove(self, name: str) -> int:
        """등록 해제 + 그 org의 설치본(clone) 전부 삭제 (§12.2).

        "org를 지운다 = 그 org 것을 더 안 쓴다" — 남은 설치본은 관리
        부담만 남기므로 함께 정리한다. 파괴적이므로 웹 UI는 확인 대화를
        거친다(삭제될 플러그인 수 명시).

        Returns:
            함께 삭제된 설치본 수.

        Raises:
            PmError: 등록되지 않은 org.
        """
        def _mutate(data):
            entries = data.get("orgs", []) if isinstance(data, dict) else []
            kept = [e for e in entries if e.get("name") != name]
            if len(kept) == len(entries):
                raise PmError(f"등록되지 않은 org: {name}")
            return {"orgs": kept}

        self._orgs_store.update(_mutate)
        removed = 0
        if self._installer is not None:
            for plugin_name in self._installer.installed_names(name):
                self._installer.uninstall(name, plugin_name)
                removed += 1
        return removed

    def revalidate_all(self) -> Dict[str, bool]:
        """매 시작 시 전 org 재검증 (§10.2) — {org명: 권한 유지 여부}.

        권한을 잃은 org는 False — 사이드바 잠금·스캔 제외 대상.
        판정 불능(GitHubError — 한도 등)은 False로 잠그고 사유는 로그.

        Raises:
            AuthError: 토큰 자체가 무효 → 로그인 창.
        """
        results: Dict[str, bool] = {}
        orgs = self.list_orgs()
        if not orgs:
            return results
        viewer = self._auth.current_id() or ""
        client = self._client_factory(None)
        for org in orgs:
            if org.kind is OrgKind.USER:
                results[org.name] = org.name.lower() == viewer.lower()
                continue
            try:
                results[org.name] = client.check_org_membership(org.name)
            except GitHubError as e:
                logger.warning("org 재검증 실패(잠금): %s — %s", org.name, e)
                results[org.name] = False
        return results

    # --- 내부 ---

    def _resolve_host_policy(self, host):
        """단일 host 정책 (§10.2) → (검증에 쓸 host 또는 None, 첫 org 여부).

        Raises:
            GitHubError: 첫 org의 bare 이름·확정 host와 다른 서버.
        """
        configured = self._config.github_host
        if configured is None:
            if host is None:
                raise GitHubError(
                    "최초 org는 전체 URL로 입력하세요 — host 미확정 (§10.2)")
            return host, True
        if host is not None and host != configured:
            raise GitHubError(
                f"다른 서버({host})의 URL — 단일 GitHub 서버 정책"
                f" (현재: {configured}, §10.2)")
        return None, False  # None = 확정 host 사용

    def _commit_host(self, host: str) -> None:
        """첫 org의 host를 config.json에 확정 기록 (§8.1)."""
        def _mutate(data):
            merged = dict(data) if isinstance(data, dict) else {}
            merged["github_host"] = host
            return merged

        self._config_store.update(_mutate)
        self._config.reload()

    @staticmethod
    def _append(data, org: Org):
        merged = data if isinstance(data, dict) else {}
        merged.setdefault("orgs", []).append(org.to_dict())
        return merged
