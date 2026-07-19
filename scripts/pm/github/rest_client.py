"""requests 기반 GitHubClient 구현 (Architecture.md §5·§10).

설정을 직접 읽지 않는다 — api base·토큰·인증서·타임아웃·페이지 크기
전부 생성자 주입 (§2.2 DIP). 오류 매핑: 401 → AuthError(로그인 라우팅
§10.2), rate limit 403 → 한도 안내 GitHubError(§10.1), 그 외 → GitHubError.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Mapping, Optional

import requests

from pm.errors import AuthError, GitHubError
from pm.models import OrgKind

logger = logging.getLogger(__name__)

_ACCEPT = "application/vnd.github+json"


def _summarize(item: Mapping[str, Any]) -> Dict[str, Any]:
    """repo API 응답에서 §8.3 카탈로그에 필요한 필드만 추린다."""
    return {
        "name": item["name"],
        "description": item.get("description") or "",
        "private": bool(item.get("private", False)),
        "html_url": item.get("html_url", ""),
        "clone_url": item.get("clone_url", ""),
    }


class RestGitHubClient:
    """GitHubClient의 REST 구현체.

    Args:
        api_base_url: §10.3 규칙으로 만든 API base.
        token_provider: 호출 시점의 PAT를 돌려주는 콜러블 — None이면 무인증.
        ca_bundle: §10.5 사내 인증서 번들 경로. None이면 시스템 기본.
        timeout: 요청 타임아웃 초 (§2.3).
        per_page: 페이지 크기 (§10.1).
        session: 테스트 주입용 — None이면 requests.Session().
    """

    def __init__(
        self,
        api_base_url: str,
        token_provider: Callable[[], Optional[str]],
        ca_bundle: Optional[str] = None,
        timeout: float = 10.0,
        per_page: int = 100,
        session: Optional[Any] = None,
    ) -> None:
        self._base = api_base_url.rstrip("/")
        self._token_provider = token_provider
        self._verify = ca_bundle if ca_bundle else True
        self._timeout = timeout
        self._per_page = per_page
        self._session = session if session is not None else requests.Session()

    # --- GitHubClient 구현 ---

    def verify_token(self) -> str:
        """§10.2: GET /user 성공 여부로만 판정 — 토큰 형식 검사 금지."""
        response = self._get(self._base + "/user")
        if response.status_code == 200:
            return response.json()["login"]
        raise AuthError(f"토큰 검증 실패 (HTTP {response.status_code})")

    def resolve_target(self, name: str) -> OrgKind:
        """GET /orgs/{name} 성공 → org, 실패 시 GET /users/{name} → user."""
        response = self._get(f"{self._base}/orgs/{name}")
        if response.status_code == 200:
            return OrgKind.ORG
        response = self._get(f"{self._base}/users/{name}")
        if response.status_code == 200:
            return OrgKind.USER
        raise self._error(response, f"계정을 찾을 수 없습니다: {name}")

    def fetch_repos(
        self,
        name: str,
        kind: OrgKind,
        viewer_login: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """3-way 분기(§10.1) + Link 헤더 페이지네이션."""
        if kind is OrgKind.ORG:
            url = f"{self._base}/orgs/{name}/repos"
            repo_type = "all"  # 토큰 권한 내 private 포함
        elif (viewer_login is not None
              and name.lower() == viewer_login.lower()):
            url = self._base + "/user/repos"
            repo_type = "owner"  # 본인 private는 이 경로만 반환
        else:
            url = f"{self._base}/users/{name}/repos"
            repo_type = "owner"  # type=all은 collaborator repo로 오염
        params: Optional[Dict[str, Any]] = {
            "type": repo_type,
            "per_page": self._per_page,
        }
        repos: List[Dict[str, Any]] = []
        while url:
            response = self._get(url, params=params)
            if response.status_code != 200:
                raise self._error(response, f"repo 목록 조회 실패: {name}")
            repos.extend(_summarize(item) for item in response.json())
            url = response.links.get("next", {}).get("url")
            params = None  # next URL에 쿼리가 이미 포함돼 있다
        return repos

    def check_org_membership(self, org: str) -> bool:
        """GET /user/memberships/orgs/{org} — state=active만 통과 (§10.2)."""
        response = self._get(f"{self._base}/user/memberships/orgs/{org}")
        if response.status_code == 200:
            return response.json().get("state") == "active"
        if response.status_code in (403, 404):
            if self._rate_limited(response):
                raise self._error(response, f"멤버십 확인 실패: {org}")
            return False  # 멤버 아님·비공개 멤버십 — 게이트 거부
        raise self._error(response, f"멤버십 확인 실패: {org}")

    # --- 내부 ---

    def _get(self, url: str, params: Optional[Mapping[str, Any]] = None):
        headers = {"Accept": _ACCEPT}
        token = self._token_provider()
        if token:
            headers["Authorization"] = f"token {token}"
        try:
            response = self._session.get(
                url,
                headers=headers,
                params=params,
                timeout=self._timeout,
                verify=self._verify,
            )
        except requests.RequestException as e:
            raise GitHubError(f"GitHub API 요청 실패: {url} ({e})") from e
        if response.status_code == 401:
            raise AuthError("토큰이 유효하지 않습니다 (HTTP 401)")
        return response

    @staticmethod
    def _rate_limited(response: Any) -> bool:
        """403이 권한 거부가 아니라 한도 소진인지 (§10.1).

        GHES는 rate limit이 꺼져 있을 수 있으므로 X-RateLimit-* 헤더
        존재를 가정하지 않고 본문 문구도 함께 본다.
        """
        if response.status_code != 403:
            return False
        if response.headers.get("X-RateLimit-Remaining") == "0":
            return True
        try:
            message = response.json().get("message", "")
        except ValueError:
            message = response.text or ""
        return "rate limit" in str(message).lower()

    def _error(self, response: Any, context: str) -> GitHubError:
        if self._rate_limited(response):
            reset = response.headers.get("X-RateLimit-Reset")
            hint = f" — X-RateLimit-Reset={reset}" if reset else ""
            return GitHubError(f"{context}: API 호출 한도 소진{hint}")
        return GitHubError(f"{context} (HTTP {response.status_code})")
