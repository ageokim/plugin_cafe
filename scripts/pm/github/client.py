"""GitHubClient Protocol (Architecture.md §5).

§2.2 LSP: RestGitHubClient(구현) ↔ FakeGitHubClient(테스트) ↔ 향후
GhCliClient가 이 Protocol 뒤에서 호환된다. services는 이 타입에만 의존.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from pm.models import OrgKind


class GitHubClient(Protocol):
    """GitHub API 추상 인터페이스."""

    def verify_token(self) -> str:
        """토큰 소유자 login을 돌려준다 (§10.2 GET /user 판정).

        Raises:
            AuthError: 토큰 무효.
        """

    def resolve_target(self, name: str) -> OrgKind:
        """계정이 org인지 user인지 판별한다 (§10.1).

        Raises:
            GitHubError: 계정 없음·API 오류.
        """

    def fetch_repos(
        self,
        name: str,
        kind: OrgKind,
        viewer_login: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """3-way repo 목록 (§10.1) — 페이지네이션 완결 후 전체 반환.

        Args:
            name: 대상 계정명.
            kind: resolve_target 결과.
            viewer_login: 토큰 소유자 login — 본인 여부 판정(§10.1 3행).

        Returns:
            repo 요약 dict 목록 (name/description/private/html_url/clone_url).

        Raises:
            AuthError: 토큰 무효. GitHubError: 권한·한도·네트워크.
        """

    def check_org_membership(self, org: str) -> bool:
        """§10.2 멤버십 게이트 — state=active만 True.

        Raises:
            AuthError: 토큰 무효. GitHubError: 한도 소진 등 판정 불능.
        """
