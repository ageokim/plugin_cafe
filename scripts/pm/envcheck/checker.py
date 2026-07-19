"""환경 체크 엔진 (§9.4) — Check Protocol + 2단계 실행기.

체크는 두 단계로 나뉜다(§9.4):
- BOOTSTRAP (A, 항목 1~5·13): Flask를 띄우기 위한 전제 — launcher가
  터미널 단계에서 검사·차단한다.
- WEB (B, 항목 6~12): Flask 기동 후 브라우저 체크리스트 화면으로 표시.

새 항목 추가 = Check 구현체 하나 추가 (OCP §2.2).
"""

from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from pm.models import CheckResult

BOOTSTRAP = "bootstrap"
WEB = "web"

# probe 반환형: (통과 여부, 상세 메시지, 수정 명령 또는 None)
ProbeResult = Tuple[bool, str, Optional[str]]


class ProbeCheck:
    """probe 콜러블 하나를 감싸는 표준 Check 구현.

    Args:
        check_id: §9.4 표의 항목 식별자 (예: "python_version").
        name: 사람용 이름.
        stage: BOOTSTRAP 또는 WEB.
        probe: () -> (passed, detail, fix_command).
        informational: True면 실패해도 전체 판정에 영향 없음 (§9.4
            4·11번 같은 정보성 항목).
    """

    def __init__(
        self,
        check_id: str,
        name: str,
        stage: str,
        probe: Callable[[], ProbeResult],
        informational: bool = False,
    ) -> None:
        self.check_id = check_id
        self.name = name
        self.stage = stage
        self._probe = probe
        self.informational = informational

    def run(self) -> CheckResult:
        """probe를 실행해 CheckResult로 변환. probe 예외 = 실패."""
        try:
            passed, detail, fix = self._probe()
        except Exception as exc:  # pylint: disable=broad-exception-caught
            passed, detail, fix = False, f"검사 실패: {exc}", None
        return CheckResult(
            check_id=self.check_id,
            name=self.name,
            passed=passed,
            detail=detail,
            fix_command=fix,
            informational=self.informational,
        )


class EnvCheckRunner:
    """등록된 체크 목록을 단계별로 실행한다."""

    def __init__(self, checks: Sequence[ProbeCheck]) -> None:
        self._checks = list(checks)

    def run(self, stage: Optional[str] = None) -> List[CheckResult]:
        """stage 지정 시 그 단계만, None이면 전체 실행."""
        return [
            check.run() for check in self._checks
            if stage is None or check.stage == stage
        ]

    @staticmethod
    def all_passed(results: Sequence[CheckResult]) -> bool:
        """정보성 항목을 제외한 전 항목 통과 여부."""
        return all(r.passed or r.informational for r in results)
