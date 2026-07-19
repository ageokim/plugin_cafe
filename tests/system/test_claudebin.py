"""claude 실행 파일 해석기 테스트 (§12.3 — PATH 밖 설치 대응)."""

from __future__ import annotations

import os
from types import SimpleNamespace

from pm.system.claudebin import ensure_claude_on_path, resolve_claude_bin


def _make_exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def test_config_claude_bin_wins(tmp_path):
    configured = _make_exe(tmp_path / "custom" / "claude")
    config = SimpleNamespace(claude_bin=str(configured))
    found = resolve_claude_bin(config, which=lambda n: "/path/other",
                               home=tmp_path, system=lambda: "Linux")
    assert found == str(configured)


def test_invalid_config_falls_back_to_which(tmp_path):
    config = SimpleNamespace(claude_bin=str(tmp_path / "없는파일"))
    found = resolve_claude_bin(config, which=lambda n: "/which/claude",
                               home=tmp_path, system=lambda: "Linux")
    assert found == "/which/claude"


def test_known_location_fallback(tmp_path):
    local = _make_exe(tmp_path / ".claude" / "local" / "claude")
    found = resolve_claude_bin(None, which=lambda n: None,
                               home=tmp_path, system=lambda: "Linux",
                               sdk_locator=lambda: None)
    assert found == str(local)


def test_vscode_extension_latest_version(tmp_path):
    _make_exe(tmp_path / ".vscode" / "extensions"
              / "anthropic.claude-code-1.0.0" / "resources"
              / "native-binary" / "claude")
    newer = _make_exe(tmp_path / ".vscode" / "extensions"
                      / "anthropic.claude-code-2.0.0" / "resources"
                      / "native-binary" / "claude")
    found = resolve_claude_bin(None, which=lambda n: None,
                               home=tmp_path, system=lambda: "Linux",
                               sdk_locator=lambda: None)
    assert found == str(newer)


def test_nothing_found_returns_none(tmp_path):
    assert resolve_claude_bin(None, which=lambda n: None, home=tmp_path,
                              system=lambda: "Linux",
                              sdk_locator=lambda: None) is None


def test_ensure_on_path_prepends_idempotently(tmp_path):
    exe = _make_exe(tmp_path / ".claude" / "local" / "claude")
    env = {"PATH": "/usr/bin"}
    for _ in range(2):  # 멱등 — 중복 prepend 없음
        resolved = ensure_claude_on_path(None, environ=env,
                                         which=lambda n: None,
                                         home=tmp_path,
                                         system=lambda: "Linux",
                                         sdk_locator=lambda: None)
        assert resolved == str(exe)
    assert env["PATH"].split(os.pathsep).count(str(exe.parent)) == 1
    assert env["PATH"].startswith(str(exe.parent))


def test_ensure_on_path_not_found_keeps_path(tmp_path):
    env = {"PATH": "/usr/bin"}
    assert ensure_claude_on_path(None, environ=env, which=lambda n: None,
                                 home=tmp_path,
                                 system=lambda: "Linux",
                                 sdk_locator=lambda: None) is None
    assert env["PATH"] == "/usr/bin"
