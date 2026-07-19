"""envcheck 엔진·체크 테스트 (§9.4, M4) — 실 환경 오염 없이 검증."""

from __future__ import annotations

import json
import socket

import pytest

from pm.config import ConfigProvider
from pm.envcheck.checker import BOOTSTRAP, WEB, EnvCheckRunner, ProbeCheck
from pm.envcheck.checks import build_checks


def _config(**values) -> ConfigProvider:
    return ConfigProvider(file_loader=lambda: dict(values), env={},
                          cli_overrides=None)


def _check_by_id(checks, check_id):
    return next(c for c in checks if c.check_id == check_id)


# ── checker 엔진 ─────────────────────────────────────────────
def test_runner_filters_by_stage():
    checks = [
        ProbeCheck("a", "a", BOOTSTRAP, lambda: (True, "", None)),
        ProbeCheck("b", "b", WEB, lambda: (True, "", None)),
    ]
    runner = EnvCheckRunner(checks)
    assert [r.check_id for r in runner.run(BOOTSTRAP)] == ["a"]
    assert [r.check_id for r in runner.run(WEB)] == ["b"]
    assert len(runner.run()) == 2


def test_informational_failure_does_not_block():
    results = EnvCheckRunner([
        ProbeCheck("info", "info", WEB, lambda: (False, "", None),
                   informational=True),
        ProbeCheck("real", "real", WEB, lambda: (True, "", None)),
    ]).run()
    assert EnvCheckRunner.all_passed(results)


def test_probe_exception_becomes_failure():
    def boom():
        raise RuntimeError("터짐")

    result = ProbeCheck("x", "x", WEB, boom).run()
    assert not result.passed and "터짐" in result.detail


def test_stage_split_matches_spec(tmp_paths):
    """§9.4: A(부트스트랩)=1~5·13 → 6개, B(웹)=6~12 → 7개."""
    checks = build_checks(tmp_paths, _config())
    assert len([c for c in checks if c.stage == BOOTSTRAP]) == 6
    assert len([c for c in checks if c.stage == WEB]) == 7


# ── 개별 체크 ────────────────────────────────────────────────
def test_python_version_check(tmp_paths):
    old = _check_by_id(
        build_checks(tmp_paths, _config(), version=(3, 7, 0)),
        "python_version").run()
    assert not old.passed and old.fix_command

    py38 = _check_by_id(
        build_checks(tmp_paths, _config(), version=(3, 8, 19)),
        "python_version").run()
    assert py38.passed and "폴백" in py38.detail  # SDK 안내 (§12.3)

    py312 = _check_by_id(
        build_checks(tmp_paths, _config(), version=(3, 12, 0)),
        "python_version").run()
    assert py312.passed and "폴백" not in py312.detail


def test_pinned_interpreter_check(tmp_paths):
    check = _check_by_id(build_checks(tmp_paths, _config()),
                         "pinned_interpreter")
    assert not check.run().passed  # env.json 없음

    tmp_paths.env_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_paths.env_file.write_text(json.dumps({"python": "/없는/경로"}),
                                  encoding="utf-8")
    assert not check.run().passed  # 경로 소실

    import sys
    tmp_paths.env_file.write_text(json.dumps({"python": sys.executable}),
                                  encoding="utf-8")
    assert check.run().passed


def test_port_free_check(tmp_paths):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    try:
        busy = _check_by_id(  # 무관 프로세스 점유 → FAIL 유지
            build_checks(tmp_paths, _config(flask_port=port),
                         prober=lambda p: None),
            "port_free").run()
        assert not busy.passed and str(port) in busy.detail

        import pm.system.takeover as takeover_mod
        orig_can_signal = takeover_mod.can_signal
        takeover_mod.can_signal = lambda pid: True
        try:
            cafe = _check_by_id(  # 이전 Plugin Cafe 서버 점유 → 자동 인계
                build_checks(tmp_paths, _config(flask_port=port),
                             prober=lambda p: 4242),
                "port_free").run()
            assert cafe.passed and "자동 인계" in cafe.detail

            takeover_mod.can_signal = lambda pid: False
            foreign_own = _check_by_id(  # 다른 사용자 소유 → 인계 불가 FAIL
                build_checks(tmp_paths, _config(flask_port=port),
                             prober=lambda p: 4242),
                "port_free").run()
            assert not foreign_own.passed and "권한" in foreign_own.detail
        finally:
            takeover_mod.can_signal = orig_can_signal
    finally:
        sock.close()
    free = _check_by_id(
        build_checks(tmp_paths, _config(flask_port=port)),
        "port_free").run()
    assert free.passed


@pytest.mark.parametrize("mode,expected", [(0o600, True), (0o644, False)])
def test_credentials_perms_check(tmp_paths, mode, expected):
    tmp_paths.credentials_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_paths.credentials_file.write_text("{}", encoding="utf-8")
    tmp_paths.credentials_file.chmod(mode)
    check = _check_by_id(
        build_checks(tmp_paths, _config(), system=lambda: "Linux"),
        "credentials_perms")
    result = check.run()
    assert result.passed is expected
    assert result.informational  # 실패해도 전체 판정은 막지 않음(§9.4)


def test_credentials_perms_absent_passes(tmp_paths):
    check = _check_by_id(build_checks(tmp_paths, _config()),
                         "credentials_perms")
    assert check.run().passed


def test_host_unset_skips_reachability(tmp_paths):
    result = _check_by_id(build_checks(tmp_paths, _config()),
                          "host_reachable").run()
    assert result.passed and "skip" in result.detail


def test_which_based_checks(tmp_paths, monkeypatch):
    # claude_cli는 which 밖 폴백(SDK 번들 등)까지 탐색하므로(§12.3)
    # '완전 미발견' 케이스는 해석기를 직접 막아 검증한다.
    import pm.system.claudebin as claudebin
    monkeypatch.setattr(claudebin, "resolve_claude_bin",
                        lambda *a, **k: None)
    missing = build_checks(tmp_paths, _config(), which=lambda name: None)
    assert not _check_by_id(missing, "git").run().passed
    assert not _check_by_id(missing, "claude_cli").run().passed
    assert not _check_by_id(missing, "pm_path").run().passed

    shim = tmp_paths.root / "scripts" / "bin" / "pm"

    def fake_which(name):
        return str(shim) if name in ("pm", "git", "claude") else None

    found = build_checks(tmp_paths, _config(), which=fake_which)
    assert _check_by_id(found, "git").run().passed
    assert _check_by_id(found, "pm_path").run().passed


def test_pm_path_detects_foreign_checkout(tmp_paths):
    checks = build_checks(tmp_paths, _config(),
                          which=lambda name: "/다른곳/scripts/bin/pm")
    result = _check_by_id(checks, "pm_path").run()
    assert not result.passed and "다른 checkout" in result.detail


def test_claude_structure_detects_corruption(tmp_paths):
    check = _check_by_id(build_checks(tmp_paths, _config()),
                         "claude_structure")
    assert check.run().passed  # 파일 없음 = 생성 전 정상
    tmp_paths.marketplace_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_paths.marketplace_file.write_text("{깨진 json", encoding="utf-8")
    result = check.run()
    assert not result.passed and result.fix_command == "pm inspect --repair"
