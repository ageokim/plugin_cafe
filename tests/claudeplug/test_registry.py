"""pm.claudeplug.registry 테스트 — §6.2 등록·충돌·enabledPlugins."""

from __future__ import annotations

# pytest fixture 패턴 — fixture 이름을 인자로 받는 것은 정상이다
# pylint: disable=redefined-outer-name

import json

import pytest

from pm.claudeplug.registry import (MARKETPLACE_NAME, ClaudePluginRegistry,
                                    parse_source, plugin_source,
                                    validate_convention)
from pm.errors import RegistryError
from pm.store.json_store import JsonStore


@pytest.fixture
def registry(tmp_paths):
    return ClaudePluginRegistry(
        JsonStore(tmp_paths.marketplace_file,
                  default=lambda: {"name": MARKETPLACE_NAME, "plugins": []}),
        JsonStore(tmp_paths.claude_settings_local_file, default=dict),
    )


def test_register_writes_spec_schema(registry, tmp_paths):
    entry = registry.register("org-a", "plugin-a")
    assert entry == "plugin-a"
    data = json.loads(tmp_paths.marketplace_file.read_text(encoding="utf-8"))
    assert data == {
        "name": "plugin-cafe",
        "plugins": [{
            "name": "plugin-a",
            "source": "./plugins/org-a/plugin-a",
        }],
    }  # §6.3 예시와 1:1


def test_register_is_idempotent_for_same_source(registry):
    first = registry.register("org-a", "plugin-a")
    second = registry.register("org-a", "plugin-a")
    assert first == second
    assert len(registry.registered()) == 1


def test_collision_renames_only_new_entry(registry):
    first = registry.register("org-a", "plugin-a")
    second = registry.register("org-b", "plugin-a")
    assert first == "plugin-a"
    assert second == "org-b-plugin-a"  # 신규만 접두 (§6.2)
    assert registry.entry_for("org-a", "plugin-a") == "plugin-a"


def test_set_enabled_and_is_enabled(registry, tmp_paths):
    entry = registry.register("org-a", "plugin-a")
    registry.set_enabled(entry, True)
    assert registry.is_enabled(entry) is True
    settings = json.loads(
        tmp_paths.claude_settings_local_file.read_text(encoding="utf-8"))
    assert settings["enabledPlugins"] == {"plugin-a@plugin-cafe": True}
    registry.set_enabled(entry, False)
    assert registry.is_enabled(entry) is False


def test_set_enabled_unregistered_raises(registry):
    with pytest.raises(RegistryError):
        registry.set_enabled("ghost", True)


def test_unregister_removes_enabled_key_and_entry(registry, tmp_paths):
    entry = registry.register("org-a", "plugin-a")
    registry.set_enabled(entry, True)
    registry.unregister(entry)
    assert registry.registered() == {}
    settings = json.loads(
        tmp_paths.claude_settings_local_file.read_text(encoding="utf-8"))
    assert settings.get("enabledPlugins", {}) == {}


def test_unregister_missing_raises(registry):
    with pytest.raises(RegistryError):
        registry.unregister("ghost")


def test_other_settings_keys_preserved(registry, tmp_paths):
    store = JsonStore(tmp_paths.claude_settings_local_file, default=dict)
    store.write({"env": {"ANTHROPIC_MODEL": "claude-fable-5"},
                 "enabledPlugins": {"x@other-market": True}})
    entry = registry.register("org-a", "plugin-a")
    registry.set_enabled(entry, True)
    settings = store.read()
    assert settings["env"] == {"ANTHROPIC_MODEL": "claude-fable-5"}
    assert settings["enabledPlugins"]["x@other-market"] is True


def test_prune_enabled_keys_only_own_marketplace(registry, tmp_paths):
    store = JsonStore(tmp_paths.claude_settings_local_file, default=dict)
    store.write({"enabledPlugins": {
        "ghost@plugin-cafe": True,   # 등록 없는 우리 키 — 제거 대상
        "x@other-market": True,        # 타 마켓 — 불변
    }})
    removed = registry.prune_enabled_keys()
    assert removed == ["ghost@plugin-cafe"]
    assert store.read()["enabledPlugins"] == {"x@other-market": True}


def test_source_helpers():
    assert plugin_source("org-a", "p") == "./plugins/org-a/p"
    assert parse_source("./plugins/org-a/p") == ("org-a", "p")
    assert parse_source("plugins/org-a/p") is None
    assert parse_source("./plugins/only") is None


def _make_plugin_dir(tmp_path, name="plugin-a", manifest=None,
                     component="skills"):
    plugin_dir = tmp_path / name
    (plugin_dir / ".claude-plugin").mkdir(parents=True)
    if manifest is not None:
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
            manifest, encoding="utf-8")
    if component:
        (plugin_dir / component).mkdir()
    return plugin_dir


def test_validate_convention_ok(tmp_path):
    plugin_dir = _make_plugin_dir(
        tmp_path, manifest='{"name": "plugin-a", "version": "0.1.0"}')
    assert validate_convention(plugin_dir) == ([], [])


def test_validate_convention_missing_manifest(tmp_path):
    plugin_dir = _make_plugin_dir(tmp_path, manifest=None)
    errors, _ = validate_convention(plugin_dir)
    assert any("plugin.json 없음" in error for error in errors)


def test_validate_convention_bad_json(tmp_path):
    plugin_dir = _make_plugin_dir(tmp_path, manifest="{oops")
    errors, _ = validate_convention(plugin_dir)
    assert any("파싱 불가" in error for error in errors)


def test_validate_convention_name_mismatch_is_warning(tmp_path):
    plugin_dir = _make_plugin_dir(tmp_path,
                                  manifest='{"name": "other-name"}')
    errors, warnings = validate_convention(plugin_dir)
    assert not errors
    assert any("권장 불일치" in warning for warning in warnings)


def test_validate_convention_no_component(tmp_path):
    plugin_dir = _make_plugin_dir(tmp_path,
                                  manifest='{"name": "plugin-a"}',
                                  component=None)
    errors, _ = validate_convention(plugin_dir)
    assert any("컴포넌트 없음" in error for error in errors)
