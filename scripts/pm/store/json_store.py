"""data/*.json 원자적 입출력 (Architecture.md §5·§8).

파일별 클래스를 두지 않는 제네릭 store 하나 — 파일별 차이(경로·기본값·
secure)는 container(§4)의 결선 인자다. dataclass 변환은 services의 몫.

동시 쓰기 참고: 원자적 replace는 "찢어진 파일"만 막는다. CLI·UI가 동시에
같은 파일을 고치면 나중 쓰기가 이긴다(lost update) — 단일 사용자 로컬
도구 전제로 수용한다.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class JsonStore:
    """JSON 파일 하나의 읽기/쓰기 담당.

    - read: 파일 없음/손상 → ``default()`` 반환. 손상은 경고 로그만 남기고
      파일은 보존한다(다음 write가 교체) — §5 "손상 시 기본값+경고".
    - write: 같은 디렉토리 임시파일 + ``os.replace`` — 부분 쓰기가 절대
      남지 않는다. mkstemp는 POSIX에서 0600으로 만들어지므로 토큰이
      임시파일 단계에서도 노출되지 않는다.
    - secure=True(credentials §8.4): POSIX에서 최종 파일 0600 보장.
      Windows의 chmod는 사실상 no-op이라 사용자 프로필 NTFS ACL에
      위임한다(envcheck 항목 11은 POSIX에서만 권한 검사).

    Args:
        path: 대상 파일 경로.
        default: 기본값 팩토리 — 값이 아닌 콜러블(공유 가변 기본값 사고 방지).
        secure: True면 쓰기 후 0600 강제 (POSIX 한정).
    """

    def __init__(self,
                 path: Path,
                 default: Callable[[], Any],
                 secure: bool = False) -> None:
        self._path = path
        self._default = default
        self._secure = secure

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def read(self) -> Any:
        """파일 내용을 돌려준다 — 없거나 손상이면 default()."""
        try:
            with open(self._path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except FileNotFoundError:
            return self._default()
        except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
            logger.warning("손상된 JSON을 기본값으로 대체합니다 (%s): %s",
                           self._path, e)
            return self._default()

    def write(self, data: Any) -> None:
        """원자적으로 쓴다 — 실패 시 기존 파일은 무손상, 임시파일은 정리.

        Raises:
            OSError: 디스크 쓰기 실패 (그대로 전파).
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self._path.parent),
            prefix=self._path.name + ".",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fp:
                json.dump(data, fp, indent=2, ensure_ascii=False)
                fp.write("\n")
                fp.flush()
                os.fsync(fp.fileno())
            os.replace(tmp_name, self._path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        if self._secure and os.name == "posix":
            os.chmod(self._path, 0o600)

    def update(self, mutator: Callable[[Any], Any]) -> Any:
        """read → mutator → write 편의 메서드. 쓴 값을 돌려준다."""
        data = mutator(self.read())
        self.write(data)
        return data
