"""로그인(ID/PAT) 검증과 자동 저장 (Architecture.md §10.2·§8.4·§12.6).

host 결정 규칙(§10.2): config에 github_host가 있으면 즉시 검증·저장,
최초 실행(host 미정)이면 **미검증 세션** — 자격은 메모리에만 두고
첫 org 추가가 검증을 통과했을 때 비로소 credentials.json을 기록한다.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Callable, Dict, Optional

from pm.config import ConfigProvider
from pm.errors import AuthError
from pm.github.client import GitHubClient
from pm.store.json_store import JsonStore

logger = logging.getLogger(__name__)


@dataclasses.dataclass(frozen=True)
class LoginResult:
    """로그인 시도의 결과."""

    verified: bool  # False = 미검증 세션 (§10.2 최초 실행)
    login: Optional[str] = None
    first_save: bool = False  # credentials.json 최초 생성 — 경고 1회 (§8.4)


class AuthService:
    """로그인·credentials 수명 관리.

    Args:
        credentials_store: §8.4 저장소 (secure=True 결선).
        client_factory: ``(host 또는 None) → GitHubClient`` — None이면
            config의 확정 host 사용 (container 결선).
        config: ConfigProvider.
    """

    def __init__(
        self,
        credentials_store: JsonStore,
        client_factory: Callable[[Optional[str]], GitHubClient],
        config: ConfigProvider,
    ) -> None:
        self._store = credentials_store
        self._client_factory = client_factory
        self._config = config
        self._pending: Optional[Dict[str, str]] = None

    # --- 조회 ---

    def load_saved(self) -> Optional[Dict[str, str]]:
        """저장된 자격 — 자동 로그인 경로 (§8.4). 없으면 None."""
        data = self._store.read()
        if isinstance(data, dict) and data.get("id") and data.get("token"):
            return {"id": data["id"], "token": data["token"]}
        return None

    def current_id(self) -> Optional[str]:
        if self._pending is not None:
            return self._pending["id"]
        saved = self.load_saved()
        return saved["id"] if saved else None

    def current_token(self) -> Optional[str]:
        """토큰 제공자 — github/gitops에 token_provider로 결선된다 (§11)."""
        if self._pending is not None:
            return self._pending["token"]
        saved = self.load_saved()
        return saved["token"] if saved else None

    def is_unverified(self) -> bool:
        """미검증 세션 여부 — org 추가 외 기능 잠금 판정 (§10.2)."""
        return self._pending is not None

    # --- 로그인 흐름 (§10.2) ---

    def login(self, user_id: str, token: str) -> LoginResult:
        """ID/PAT 로그인.

        host 확정 상태면 즉시 검증·저장, 미정이면 미검증 세션으로 보류.

        Raises:
            AuthError: 입력 누락·토큰 무효·ID 불일치.
        """
        user_id = user_id.strip()
        token = token.strip()
        if not user_id or not token:
            raise AuthError("ID와 PAT를 모두 입력하세요")
        self._pending = {"id": user_id, "token": token}
        if self._config.github_host is None:
            logger.info("host 미확정 — 미검증 세션으로 진입 (§10.2)")
            return LoginResult(verified=False)
        try:
            login_name = self.verify_current()
        except AuthError:
            self._pending = None
            raise
        return self._commit(login_name)

    def verify_current(self, host: Optional[str] = None) -> str:
        """토큰 유효 + ID 교차 검증 (§10.2) — 저장하지 않는다.

        Args:
            host: 검증에 쓸 host — 첫 org 추가 시 아직 config에 없는
                후보 host를 넘긴다. None이면 config의 확정 host.

        Returns:
            GET /user가 돌려준 토큰 소유자 login.

        Raises:
            AuthError: 토큰 무효(401) 또는 ID 불일치 → 로그인 창 복귀.
        """
        expected = self.current_id()
        if expected is None:
            raise AuthError("로그인 정보가 없습니다")
        login_name = self._client_factory(host).verify_token()
        if login_name.lower() != expected.lower():
            raise AuthError(
                f"토큰 소유자({login_name})가 입력한 ID({expected})와 다릅니다")
        return login_name

    def commit_pending(self) -> LoginResult:
        """첫 org 검증 통과 후 비로소 credentials.json 기록 (§10.2).

        Raises:
            AuthError: 보류 중인 자격이 없음.
        """
        if self._pending is None:
            raise AuthError("보류 중인 로그인 정보가 없습니다")
        return self._commit(self._pending["id"])

    def logout(self) -> None:
        """보류 자격만 파기 — 저장 파일은 유지 (§12.6).

        로그아웃은 로그인 화면으로 돌아가는 동작일 뿐, 저장된 자격은
        지우지 않는다 — 다른 계정으로 로그인 성공하면 그 정보로
        덮어써 교체된다(2026-07-19 결정). 파일 제거가 필요하면
        data/credentials.json을 직접 삭제한다.
        """
        self._pending = None

    def _commit(self, login_name: str) -> LoginResult:
        assert self._pending is not None
        first_save = not self._store.exists()
        self._store.write(dict(self._pending))
        self._pending = None
        if first_save:
            logger.warning(
                "credentials.json 생성 — 평문 토큰 파일입니다 (권한 600, §8.4)")
        return LoginResult(verified=True, login=login_name,
                           first_save=first_save)
