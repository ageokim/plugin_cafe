"""InspectService 테스트 — §6.4 실측 대조·드리프트·repair."""

from __future__ import annotations

from pm.models import PluginState


def _status(env, org, name):
    for status in env.inspect_service.report():
        if (status.org, status.name) == (org, name):
            return status
    raise AssertionError(f"리포트에 없음: {org}/{name}")


def test_clean_install_has_no_issues(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    status = _status(env, "org-a", "plugin-a")
    assert status.state is PluginState.ENABLED
    assert status.issues == ()


def test_clone_only_is_standalone_installed(env):
    """링크 1급(§6.4): clone만 있으면 standalone 꺼짐 — 드리프트 아님."""
    env.login_and_register_org("org-a")
    env.paths.plugin_clone_dir("org-a", "stray").mkdir(parents=True)
    status = _status(env, "org-a", "stray")
    assert status.state is PluginState.INSTALLED
    assert not any("드리프트" in issue for issue in status.issues)


def test_entry_only_drift_flagged_and_repaired(env):
    env.login_and_register_org("org-a")
    env.registry.register("org-a", "ghost")  # clone 없는 등록
    env.registry.set_enabled("ghost", True)
    status = _status(env, "org-a", "ghost")
    assert any("clone 없음" in issue for issue in status.issues)

    actions = env.inspect_service.repair()
    assert any("등록 제거: ghost" in action for action in actions)
    assert env.registry.registered() == {}
    assert env.settings_store.read().get("enabledPlugins", {}) == {}
    assert env.inspect_service.report() == []


def test_repair_prunes_stale_enabled_keys(env):
    env.settings_store.write(
        {"enabledPlugins": {"phantom@plugin-cafe": True}})
    actions = env.inspect_service.repair()
    assert any("phantom" in action for action in actions)
    assert env.settings_store.read()["enabledPlugins"] == {}


def test_unregistered_org_flagged(env):
    """'미등록' 플래그는 비정상 잔존(크래시 잔재) 안전망 — 정상 org 제거는
    설치본까지 지우므로(§12.2) orgs.json만 직접 소실시켜 재현한다."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    env.orgs_store.write({"orgs": []})  # 크래시로 등록만 사라진 상황
    status = _status(env, "org-a", "plugin-a")
    assert status.state is PluginState.ENABLED  # 여전히 관리 가능
    assert any("미등록 org" in issue for issue in status.issues)


def test_convention_violation_reported(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    manifest = (env.paths.plugin_clone_dir("org-a", "plugin-a") /
                ".claude-plugin" / "plugin.json")
    manifest.write_text('{"version": "0.1.0"}', encoding="utf-8")  # name 소실
    status = _status(env, "org-a", "plugin-a")
    assert any("규약 위반" in issue for issue in status.issues)


def test_manifest_removed_flags_stale_native_entry(env):
    """plugin.json이 사라지면 standalone으로 강등 — 잔존 native 등록은 드리프트."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    (env.paths.plugin_clone_dir("org-a", "plugin-a") /
     ".claude-plugin" / "plugin.json").unlink()
    status = _status(env, "org-a", "plugin-a")
    assert status.state is PluginState.ENABLED  # 링크 기준 — 여전히 사용중
    assert any("native 등록 잔존" in issue for issue in status.issues)


def test_repair_keeps_healthy_install(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    assert env.inspect_service.repair() == []
    assert env.registry.entry_for("org-a", "plugin-a") == "plugin-a"
