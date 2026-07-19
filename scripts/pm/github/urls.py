"""GitHub URL 파싱과 API base 규칙 (Architecture.md §10.3·§10.4).

입력은 이름/URL/SSH 어느 형태든 허용하는 dot-heuristic:
스킴 제거 → ``git@host:path`` 정규화 → userinfo(@) 제거 →
첫 조각에 점(또는 포트 콜론)이 있으면 호스트로 본다 —
GitHub 계정명에는 점이 올 수 없다.
"""

from __future__ import annotations

from typing import Optional, Tuple

from pm.errors import GitHubError

_GITHUB_COM = "github.com"
_SCHEMES = ("https://", "http://", "ssh://", "git://")


def _normalize(text: str) -> str:
    """스킴·SSH 콜론·userinfo를 제거해 ``host/segments`` 꼴로 만든다."""
    cleaned = text.strip().rstrip("/")
    lower = cleaned.lower()
    for scheme in _SCHEMES:
        if lower.startswith(scheme):
            cleaned = cleaned[len(scheme):]
            break
    head = cleaned.split("/", 1)[0]
    if "@" in head and ":" in head.split("@", 1)[1]:
        # git@host:org/repo → git@host/org/repo (SSH scp 문법)
        prefix, _, path = cleaned.partition(":")
        cleaned = prefix + "/" + path
        head = cleaned.split("/", 1)[0]
    if "@" in head:
        # userinfo 제거: git@host/... → host/...
        cleaned = head.split("@", 1)[1] + cleaned[len(head):]
    return cleaned


def parse_target(text: str) -> Tuple[Optional[str], str]:
    """입력에서 ``(host, account)`` 를 뽑는다 (§10.4).

    호스트가 없는 입력(bare 이름)이면 host는 None이다.

    Args:
        text: org URL·SSH 주소·계정명 등 사용자 입력.

    Returns:
        (host 또는 None, account 이름).

    Raises:
        GitHubError: 계정명을 찾을 수 없는 입력.
    """
    cleaned = _normalize(text)
    segments = [seg for seg in cleaned.split("/") if seg]
    if not segments:
        raise GitHubError(f"org URL을 해석할 수 없습니다: {text!r}")
    host: Optional[str] = None
    if "." in segments[0] or ":" in segments[0]:
        host = segments[0].lower()
        segments = segments[1:]
    if not segments:
        raise GitHubError(f"org URL에서 계정명을 찾을 수 없습니다: {text!r}")
    return host, segments[0]


def parse_host(text: str) -> Optional[str]:
    """입력에서 호스트만 뽑는다 — 없으면 None (§5)."""
    return parse_target(text)[0]


class ApiUrlBuilder:
    """host → API base 규칙 (§10.3).

    Args:
        override: ``config.github_api_base`` — 지정 시 규칙보다 우선
            (GHE Cloud 등 비표준 대응).
    """

    def __init__(self, override: Optional[str] = None) -> None:
        self._override = override.rstrip("/") if override else None

    def api_base(self, host: str) -> str:
        """github.com → api.github.com, 그 외(GHES) → https://{host}/api/v3."""
        if self._override:
            return self._override
        normalized = host.strip().lower().rstrip("/")
        if normalized in (_GITHUB_COM, "www." + _GITHUB_COM):
            return "https://api.github.com"
        return f"https://{normalized}/api/v3"
