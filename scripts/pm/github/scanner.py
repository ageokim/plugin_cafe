"""플러그인 repo 필터 — 도메인 정책 (Architecture.md §5, 부록 A.1).

description이 설정된 태그(``plugin_tags``)를 **모두** 포함해야 통과.
대소문자 무관. 태그 목록이 비어 있으면 필터 해제로 보고 전부 통과.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


def has_plugin_tags(description: Optional[str],
                    tags: Sequence[str]) -> bool:
    """description이 태그를 전부(대소문자 무관) 포함하는지 (부록 A.1)."""
    text = (description or "").lower()
    return all(tag.lower() in text for tag in tags)


def filter_plugin_repos(
    repos: Iterable[Mapping[str, Any]],
    tags: Sequence[str],
) -> List[Dict[str, Any]]:
    """repo 요약 목록에서 태그 통과분만 추린다 (§6.2 스캔 흐름)."""
    return [
        dict(repo) for repo in repos
        if has_plugin_tags(repo.get("description"), tags)
    ]
