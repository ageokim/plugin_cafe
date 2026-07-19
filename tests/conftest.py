"""pytest 공용 설정 — 미설치 상태에서 `import pm` 성립 + 환경 격리.

pm 패키지는 pip으로 설치하지 않으므로(§9 no-venv) scripts/를
import path 맨 앞에 넣는다. insert(0)은 타 checkout·설치본보다
이 checkout이 우선하게 한다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "scripts")
# 위치까지 확인한다 — 타 checkout이 sys.path 앞에 있으면 그쪽 pm이 잡힌다.
if not sys.path or sys.path[0] != _SCRIPTS_DIR:
    sys.path.insert(0, _SCRIPTS_DIR)

# 공용 fake 모듈(tests/support/fakes.py) — `from fakes import …`
_SUPPORT_DIR = str(Path(__file__).resolve().parent / "support")
if _SUPPORT_DIR not in sys.path:
    sys.path.insert(1, _SUPPORT_DIR)


@pytest.fixture(autouse=True)
def _isolate_pm_env(monkeypatch):
    """개발 머신의 잔류 PM_* 환경변수가 테스트를 오염시키지 않게 한다."""
    for key in list(os.environ):
        if key.startswith("PM_"):
            monkeypatch.delenv(key, raising=False)


@pytest.fixture
def tmp_paths(tmp_path):
    """실 파일시스템을 오염시키지 않는 ProjectPaths (§13.3)."""
    # sys.path 조작이 끝난 뒤에만 pm을 임포트할 수 있어 지연 임포트한다.
    from pm.paths import ProjectPaths  # pylint: disable=import-outside-toplevel
    return ProjectPaths(root=tmp_path)


@pytest.fixture
def container(tmp_paths):
    """CLI·API 계약 테스트 공용 fake 조립체 (tests/support/fakes.py)."""
    from fakes import FakeContainer  # pylint: disable=import-outside-toplevel
    return FakeContainer(tmp_paths)
