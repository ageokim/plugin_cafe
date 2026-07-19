"""pm.paths 테스트 — 전부 tmp 경로, 실 FS 오염 없음."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import pm.paths
from pm.errors import ConfigError
from pm.paths import ProjectPaths, find_root

_CHECKOUT_ROOT = Path(pm.paths.__file__).resolve().parents[2]


def test_find_root_ignores_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert find_root(env={}) == _CHECKOUT_ROOT


def test_find_root_reads_os_environ_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PM_HOME", str(tmp_path))
    assert find_root() == tmp_path.resolve()


def test_pm_home_override(tmp_path):
    assert find_root(env={"PM_HOME": str(tmp_path)}) == tmp_path.resolve()


def test_pm_home_missing_dir_raises(tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ConfigError):
        find_root(env={"PM_HOME": str(missing)})


def test_pm_home_empty_string_falls_through():
    assert find_root(env={"PM_HOME": ""}) == _CHECKOUT_ROOT


def test_discover_uses_env(tmp_path):
    paths = ProjectPaths.discover(env={"PM_HOME": str(tmp_path)})
    assert paths.root == tmp_path.resolve()


def test_all_path_properties(tmp_paths, tmp_path):
    data = tmp_path / "data"
    assert tmp_paths.data_dir == data
    assert tmp_paths.config_file == data / "config.json"
    assert tmp_paths.orgs_file == data / "orgs.json"
    assert tmp_paths.catalog_file == data / "plugins.json"
    assert tmp_paths.credentials_file == data / "credentials.json"
    assert tmp_paths.presets_file == data / "presets.json"
    assert tmp_paths.env_file == data / "env.json"
    assert tmp_paths.plugins_dir == tmp_path / "plugins"
    assert (tmp_paths.plugin_clone_dir("org-a", "plugin-a") ==
            tmp_path / "plugins" / "org-a" / "plugin-a")
    assert tmp_paths.claude_dir == tmp_path / ".claude"
    assert (tmp_paths.claude_settings_file ==
            tmp_path / ".claude" / "settings.json")
    assert (tmp_paths.claude_settings_local_file ==
            tmp_path / ".claude" / "settings.local.json")
    assert tmp_paths.claude_plugin_dir == tmp_path / ".claude-plugin"
    assert (tmp_paths.marketplace_file ==
            tmp_path / ".claude-plugin" / "marketplace.json")
    assert tmp_paths.web_dir == tmp_path / "web"
    assert tmp_paths.bin_dir == tmp_path / "scripts" / "bin"


def test_frozen(tmp_paths, tmp_path):
    with pytest.raises(dataclasses.FrozenInstanceError):
        tmp_paths.root = tmp_path / "other"


def test_no_side_effects(tmp_paths):
    _ = tmp_paths.data_dir
    _ = tmp_paths.plugin_clone_dir("o", "p")
    assert not tmp_paths.data_dir.exists()
    assert not tmp_paths.plugins_dir.exists()
