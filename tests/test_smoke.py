"""M0 스모크 — 인터프리터 하한과 패키지 임포트만 확인한다."""

from __future__ import annotations

import sys


def test_python_floor():
    assert sys.version_info >= (3, 8)


def test_import_pm():
    # 임포트 자체가 검증 대상이라 함수 안에서 임포트한다.
    import pm  # pylint: disable=import-outside-toplevel
    assert pm.__name__ == "pm"
