"""프로젝트 경로의 유일한 정의처 (Architecture.md §5·§9.3).

ROOT 탐색은 cwd와 무관하다: ``PM_HOME`` 환경변수(override) →
이 모듈의 위치(``scripts/pm/paths.py`` 기준 두 단계 위, 최종 방어).
§9.3의 1순위 "shim 자기위치"는 shim이 **PM_HOME을 자기 ROOT로 export**
하고 실행하는 것으로 실현된다(상속된 사용자 PM_HOME을 덮어써 shim
위치가 항상 이긴다 — M4). 따라서 파이썬 쪽 탐색은 이 두 단계로 충분하다.
"""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path
from typing import Mapping, Optional

from pm.errors import ConfigError

_ENV_PM_HOME = "PM_HOME"


def find_root(env: Optional[Mapping[str, str]] = None) -> Path:
    """프로젝트 ROOT 절대경로를 찾는다 (cwd 무관).

    Args:
        env: 환경변수 매핑. None이면 os.environ (테스트에서는 주입).

    Returns:
        프로젝트 루트의 resolve된 절대경로.

    Raises:
        ConfigError: PM_HOME이 존재하지 않는 디렉토리를 가리킴.
    """
    if env is None:
        env = os.environ
    override = env.get(_ENV_PM_HOME)
    if override:
        root = Path(override).expanduser().resolve()
        if not root.is_dir():
            raise ConfigError(
                f"PM_HOME이 존재하지 않는 경로를 가리킵니다: {override}")
        return root
    return Path(__file__).resolve().parents[2]


@dataclasses.dataclass(frozen=True)
class ProjectPaths:
    """프로젝트 내 모든 경로의 정의처 — 순수 값 객체 (mkdir 등 부수효과 없음).

    테스트에서는 ``ProjectPaths(root=tmp_path)`` 로 통째로 갈아끼운다 (§2.3).
    """

    root: Path

    @classmethod
    def discover(cls,
                 env: Optional[Mapping[str, str]] = None) -> ProjectPaths:
        """find_root() 결과로 생성한다 — 조립(container)에서 쓰는 경로."""
        return cls(root=find_root(env))

    # --- data/*.json (§8) ---

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def config_file(self) -> Path:
        """§8.1 설정."""
        return self.data_dir / "config.json"

    @property
    def orgs_file(self) -> Path:
        """§8.2 등록 org 목록."""
        return self.data_dir / "orgs.json"

    @property
    def catalog_file(self) -> Path:
        """§8.3 스캔 카탈로그(data/plugins.json) — 설치 폴더(plugins_dir)와 다르다."""
        return self.data_dir / "plugins.json"

    @property
    def credentials_file(self) -> Path:
        """§8.4 로그인 자동 저장 (권한 600)."""
        return self.data_dir / "credentials.json"

    @property
    def presets_file(self) -> Path:
        """§8.5 preset 정의."""
        return self.data_dir / "presets.json"

    @property
    def env_file(self) -> Path:
        """§8.6 고정된 인터프리터."""
        return self.data_dir / "env.json"

    # --- 설치·등록 (§6·§8.7) ---

    @property
    def plugins_dir(self) -> Path:
        return self.root / "plugins"

    def plugin_clone_dir(self, org: str, name: str) -> Path:
        """설치 clone 위치 ``plugins/{org}/{name}`` (§6.2)."""
        return self.plugins_dir / org / name

    @property
    def claude_dir(self) -> Path:
        return self.root / ".claude"

    @property
    def plugin_roots_dir(self) -> Path:
        """설치 링크 — plugin의 root 해석 규약 (§6.2, 사내 관례 1번)."""
        return self.claude_dir / "plugin_roots"

    @property
    def plugin_links_dir(self) -> Path:
        """설치 링크 — 절대경로판 (§6.2, 사내 관례 2번)."""
        return self.claude_dir / "plugins"

    @property
    def claude_settings_file(self) -> Path:
        """팀 공통 설정(커밋 대상) — allowlist 등 (§8.7)."""
        return self.claude_dir / "settings.json"

    @property
    def claude_settings_local_file(self) -> Path:
        """머신별 설정(비추적) — enabledPlugins (§8.7)."""
        return self.claude_dir / "settings.local.json"

    @property
    def claude_plugin_dir(self) -> Path:
        return self.root / ".claude-plugin"

    @property
    def marketplace_file(self) -> Path:
        """pm이 관리하는 로컬 마켓플레이스 (§6.2·§8.7)."""
        return self.claude_plugin_dir / "marketplace.json"

    # --- 기타 ---

    @property
    def web_dir(self) -> Path:
        """정적 프론트 — Flask가 서빙 (§12·§13.2)."""
        return self.root / "web"

    @property
    def bin_dir(self) -> Path:
        """pm shim 위치 — envcheck 항목 8이 참조 (§9.3)."""
        return self.root / "scripts" / "bin"
