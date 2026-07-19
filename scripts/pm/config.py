"""계층 설정 (Architecture.md §2.3·§8.1).

우선순위: CLI 플래그 > 환경변수(PM_*) > data/config.json > 기본값.
이 모듈은 os.environ·파일을 직접 읽지 않는다 — 전부 생성자 주입(§2.2 DIP).
config.json 쓰기(github_host 자동 확정 등)는 org_service의 몫이고,
쓰기 후에는 reload()로 반영한다.

'미설정' 규약: CLI의 None, 빈 문자열 환경변수(paths의 PM_HOME과 동일),
config.json의 null(§8.1 예시의 github_api_base: null)은 모두 미설정으로
보고 다음 계층으로 넘어간다.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Callable, Dict, List, Mapping, Optional

from pm.errors import ConfigError

logger = logging.getLogger(__name__)

# §2.3 "변할 수 있는 값" 전 항목 (org 목록=orgs.json, 경로=paths.py 제외).
# 값의 기대 타입은 기본값에서 도출한다 — None 기본값 키는 문자열.
DEFAULTS: Dict[str, Any] = {
    "github_host": None,  # 첫 org add 때 자동 확정·저장 (§8.1)
    "github_api_base": None,  # null이면 host에서 규칙 유도 (§10.3)
    "plugin_tags": ["#plugin", "#release"],
    "ca_bundle": None,  # 사내 인증서 (§10.5)
    "claude_bin": None,  # claude 실행 파일 명시 경로 — null이면 자동 탐색 (§12.3)
    "flask_port": 8765,
    "http_timeout": 10.0,
    "github_per_page": 100,
}

_ENV_PREFIX = "PM_"
# 키 → 추가로 응답하는 별칭 환경변수 (기본 이름 PM_<KEY대문자>는 항상 응답)
_ENV_ALIASES: Dict[str, str] = {"flask_port": "PM_PORT"}


def _expected_type(key: str) -> type:
    """키의 기대 타입 — DEFAULTS에서 도출, None 기본값 키는 str."""
    default = DEFAULTS[key]
    return str if default is None else type(default)


def _env_names(key: str) -> List[str]:
    """키가 응답하는 환경변수 이름들."""
    names = [_ENV_PREFIX + key.upper()]
    alias = _ENV_ALIASES.get(key)
    if alias:
        names.append(alias)
    return names


def _convert(key: str, raw: str) -> Any:
    """환경변수 문자열을 키의 기대 타입으로 변환한다.

    Raises:
        ConfigError: 숫자 변환 실패.
    """
    target = _expected_type(key)
    if target is list:
        return [item.strip() for item in raw.split(",") if item.strip()]
    if target in (int, float):
        try:
            return target(raw)
        except ValueError as e:
            raise ConfigError(
                f"환경변수 값이 {target.__name__} 이 아닙니다: {key}={raw!r}") from e
    return raw


def _valid_file_value(key: str, value: Any) -> bool:
    """config.json 값이 키의 기대 타입인지 — float 키는 int도 허용."""
    if isinstance(value, bool):
        # bool은 int의 하위 타입이라 명시적으로 차단 (bool 키는 없다)
        return False
    target = _expected_type(key)
    if target is float:
        return isinstance(value, (int, float))
    return isinstance(value, target)


class ConfigProvider:
    """읽기 전용 계층 설정 제공자 (§2.3).

    Args:
        file_loader: config.json 내용을 반환하는 콜러블 —
            container가 ``JsonStore.read`` 를 주입한다. None이면 파일 없음.
        env: 환경변수 매핑 — container가 ``os.environ`` 을 주입한다.
        cli_overrides: CLI 플래그로 받은 값 — cli.py가 None 아닌 것만 넣는다.
    """

    def __init__(
        self,
        file_loader: Optional[Callable[[], Mapping[str, Any]]] = None,
        env: Optional[Mapping[str, str]] = None,
        cli_overrides: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._file_loader = file_loader
        self._env: Dict[str, str] = dict(env) if env is not None else {}
        self._cli: Dict[str, Any] = (dict(cli_overrides)
                                     if cli_overrides is not None else {})
        self._file: Dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        """file_loader를 다시 실행해 파일 계층을 갱신한다.

        §5 "손상 시 기본값+경고" 정책의 연장으로, 이상 입력은 전부
        경고 후 무시하고 계속 동작한다: 최상위가 객체가 아니면 파일
        전체 무시, 미지 키·타입 불일치 값은 그 키만 무시, null 값은
        '미설정'(§8.1)으로 다음 계층에 위임.
        """
        raw = self._file_loader() if self._file_loader is not None else {}
        if not isinstance(raw, dict):
            logger.warning("config.json 최상위가 객체가 아니라 무시합니다: %s",
                           type(raw).__name__)
            self._file = {}
            return
        known: Dict[str, Any] = {}
        for key, value in raw.items():
            if key not in DEFAULTS:
                logger.warning("config.json의 알 수 없는 키를 무시합니다: %s", key)
                continue
            if value is None:
                continue  # null = 미설정 (§8.1 github_api_base: null)
            if not _valid_file_value(key, value):
                logger.warning("config.json 값의 타입이 맞지 않아 무시합니다: %s=%r",
                               key, value)
                continue
            known[key] = value
        self._file = known

    def get(self, key: str) -> Any:
        """우선순위(cli > env > file > 기본값)에 따라 값을 돌려준다.

        Raises:
            ConfigError: 알 수 없는 키(오타 즉발) 또는 env 값 형변환 실패.
        """
        if key not in DEFAULTS:
            raise ConfigError(f"알 수 없는 설정 키: {key}")
        if self._cli.get(key) is not None:
            return copy.copy(self._cli[key])
        for env_name in _env_names(key):
            env_value = self._env.get(env_name)
            if env_value:  # 빈 문자열은 미설정 취급 (PM_HOME과 동일 규약)
                return _convert(key, env_value)
        if key in self._file:
            return copy.copy(self._file[key])
        return copy.copy(DEFAULTS[key])

    def snapshot(self) -> Dict[str, Any]:
        """전 키의 병합 결과 사본 (--json·디버그용)."""
        return {key: self.get(key) for key in DEFAULTS}

    # --- 타입 안전 속성 (주입 지점의 오타 방지) ---

    @property
    def github_host(self) -> Optional[str]:
        return self.get("github_host")

    @property
    def github_api_base(self) -> Optional[str]:
        return self.get("github_api_base")

    @property
    def plugin_tags(self) -> List[str]:
        return self.get("plugin_tags")

    @property
    def ca_bundle(self) -> Optional[str]:
        return self.get("ca_bundle")

    @property
    def flask_port(self) -> int:
        return self.get("flask_port")

    @property
    def claude_bin(self):
        return self.get("claude_bin")

    @property
    def http_timeout(self) -> float:
        return self.get("http_timeout")

    @property
    def github_per_page(self) -> int:
        return self.get("github_per_page")
