"""불변 도메인 모델 (Architecture.md §5·§6.4·§8).

pm 내부 어떤 모듈에도 의존하지 않는다 — stdlib만.
from_dict의 필수 키 누락은 KeyError로 자연 전파하고 호출자가 감싼다.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
from typing import Any, Dict, Mapping, Optional, Tuple


def utc_now_iso() -> str:
    """UTC ISO 8601(초 단위) 타임스탬프 — added_at/created_at 용 (§8)."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.isoformat(timespec="seconds")


class PluginState(enum.Enum):
    """플러그인 실측 상태 (§6.4) — UI 라벨(미설치/꺼짐/사용중)은 presentation 몫."""

    AVAILABLE = "available"
    INSTALLED = "installed"
    ENABLED = "enabled"


class OrgKind(enum.Enum):
    """등록 대상 계정 종류 (§8.2)."""

    ORG = "org"
    USER = "user"


def derive_state(*, cloned: bool, linked: bool) -> PluginState:
    """파일시스템 실측값에서 상태를 도출한다 (§6.4 — 상태는 저장하지 않는다).

    Installed = clone 존재, Enabled = clone 존재 ∧ plugin_roots 링크가
    그 clone을 가리킴. 링크만 남은 드리프트(clone 소실)는 AVAILABLE로
    보고한다 — 교정은 ``pm inspect --repair``(§7)의 몫.

    Args:
        cloned: ``plugins/{org}/{name}`` clone 존재 여부.
        linked: ``.claude/plugin_roots/{링크명}`` 링크 실측 (§6.2).

    Returns:
        도출된 PluginState.
    """
    if cloned:
        return PluginState.ENABLED if linked else PluginState.INSTALLED
    return PluginState.AVAILABLE


@dataclasses.dataclass(frozen=True)
class Plugin:
    """카탈로그의 플러그인 repo 항목 — §8.3 스키마와 1:1."""

    name: str
    org: str
    github_addr: str
    clone_url: str
    description: str
    private: bool
    has_tags: bool

    @property
    def ref(self) -> str:
        """CLI·preset 멤버가 쓰는 식별자 표기 ``org/name`` (§7)."""
        return f"{self.org}/{self.name}"

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Plugin:
        """dict에서 생성한다 — 미지 키는 무시 (§15 #3 ref 필드 전방 호환)."""
        return cls(
            name=data["name"],
            org=data["org"],
            github_addr=data["github_addr"],
            clone_url=data["clone_url"],
            description=data["description"],
            private=bool(data["private"]),
            has_tags=bool(data["has_tags"]),
        )


@dataclasses.dataclass(frozen=True)
class Org:
    """등록된 organization/개인 계정 (§5·§8.2).

    host는 쓰기 시점(org_service)에 확정값을 넣는다 — URL 재파싱으로
    models→github 의존이 생기는 것을 피한다.
    """

    name: str
    url: str
    host: str
    kind: OrgKind
    added_at: str

    def to_dict(self) -> Dict[str, Any]:
        data = dataclasses.asdict(self)
        data["kind"] = self.kind.value
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Org:
        return cls(
            name=data["name"],
            url=data["url"],
            host=data["host"],
            kind=OrgKind(data["kind"]),
            added_at=data["added_at"],
        )


@dataclasses.dataclass(frozen=True)
class Preset:
    """플러그인 묶음 정의 (§6.5·§8.5) — 상태 필드 없음(실측 도출)."""

    name: str
    members: Tuple[str, ...]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "members": list(self.members),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Preset:
        return cls(
            name=data["name"],
            members=tuple(data["members"]),
            created_at=data["created_at"],
        )


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """환경 체크 항목 하나의 결과 (§9.4)."""

    check_id: str
    name: str
    passed: bool
    detail: str
    fix_command: Optional[str] = None
    informational: bool = False
