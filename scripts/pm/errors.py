"""pm 전역 예외 계층 (Architecture.md §5).

CLI 종료코드 매핑·사용자 메시지 포맷은 presentation(cli.py)의 몫이다.
store의 손상 파일은 예외가 아니라 "기본값 + 경고" 정책이므로(§5)
StoreError는 두지 않는다.
"""

from __future__ import annotations


class PmError(Exception):
    """pm의 모든 도메인 오류의 공통 부모."""


class ConfigError(PmError):
    """설정 키·값이 없거나 형식이 잘못됨."""


class GitHubError(PmError):
    """GitHub API 호출 실패 (인증·권한·네트워크·응답 형식)."""


class GitOpsError(PmError):
    """git 명령(clone/pull 등) 실행 실패."""


class RegistryError(PmError):
    """marketplace.json·enabledPlugins 등록/해제 실패."""


class AuthError(PmError):
    """로그인/토큰 검증 실패."""
