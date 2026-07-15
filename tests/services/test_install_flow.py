"""설치→활성→비활성→삭제 전 흐름 + 충돌·되감기·보존 (§6.2·§6.4)."""

from __future__ import annotations

import pytest

from pm.errors import GitOpsError, PmError, RegistryError
from pm.models import PluginState


def test_full_lifecycle(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")

    def state():
        return env.activation_service.state("org-a", "plugin-a")

    assert state() is PluginState.AVAILABLE

    result = env.install_service.install(plugin)
    assert result.entry_name == "plugin-a"
    assert env.paths.plugin_clone_dir("org-a", "plugin-a").is_dir()
    assert state() is PluginState.ENABLED  # install = clone+등록+활성 (§6.2)

    env.activation_service.disable("org-a", "plugin-a")
    assert state() is PluginState.INSTALLED

    env.activation_service.enable("org-a", "plugin-a")
    assert state() is PluginState.ENABLED

    env.install_service.uninstall("org-a", "plugin-a")
    assert state() is PluginState.AVAILABLE
    assert not env.paths.plugin_clone_dir("org-a", "plugin-a").exists()
    assert env.registry.registered() == {}
    assert env.settings_store.read().get("enabledPlugins", {}) == {}


def test_install_no_enable(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    result = env.install_service.install(plugin, enable=False)
    assert result.enabled is False
    assert (env.activation_service.state("org-a", "plugin-a")
            is PluginState.INSTALLED)


def test_install_native_violation_rolls_back(env):
    """native형(plugin.json 보유)인데 name이 없으면 설치 차단·되감기 (부록 A.3)."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "bad-plugin")
    env.git.broken_native = True  # plugin.json은 있으나 name 없음
    with pytest.raises(RegistryError):
        env.install_service.install(plugin)
    assert not env.paths.plugin_clone_dir("org-a", "bad-plugin").exists()
    assert env.registry.registered() == {}  # 부분 산출물 없음 (§6.2)
    assert not env.links.is_enabled("org-a", "bad-plugin")


def test_install_standalone_without_manifest(env):
    """plugin.json 없는 사내형 repo도 설치된다 — 링크 2개 생성 (부록 A.2)."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "inhouse")
    env.git.valid_plugin = False  # 맨 repo (standalone)
    result = env.install_service.install(plugin)
    assert result.profile == "standalone"
    assert env.registry.registered() == {}  # native 등록 없음
    clone = env.paths.plugin_clone_dir("org-a", "inhouse")
    root_link = env.paths.plugin_roots_dir / "inhouse"
    abs_link = env.paths.plugin_links_dir / "inhouse"
    assert root_link.resolve() == clone.resolve()  # 사내 관례 1번 (§6.2)
    assert abs_link.resolve() == clone.resolve()  # 2번 — 절대경로판
    import os
    assert not os.path.isabs(os.readlink(str(root_link)))  # 1번은 상대
    assert os.path.isabs(os.readlink(str(abs_link)))


def test_install_clone_failure_propagates(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.git.fail_urls.add(plugin.clone_url)
    with pytest.raises(GitOpsError):
        env.install_service.install(plugin)
    assert env.registry.registered() == {}


def test_install_twice_raises(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    with pytest.raises(PmError):
        env.install_service.install(plugin)


def test_name_collision_keeps_first_entry(env):
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    first = env.catalog_plugin("org-a", "plugin-a")
    second = env.catalog_plugin("org-b", "plugin-a")

    first_result = env.install_service.install(first)
    second_result = env.install_service.install(second)
    assert first_result.entry_name == "plugin-a"
    assert second_result.entry_name == "org-b-plugin-a"  # 신규만 접두 (§6.2)
    enabled = env.settings_store.read()["enabledPlugins"]
    assert enabled == {
        "plugin-a@plugin-market": True,
        "org-b-plugin-a@plugin-market": True,
    }
    # 첫 항목 삭제해도 둘째는 무관
    env.install_service.uninstall("org-a", "plugin-a")
    assert (env.activation_service.state("org-b", "plugin-a")
            is PluginState.ENABLED)


def test_uninstall_not_installed_raises(env):
    with pytest.raises(PmError):
        env.install_service.uninstall("org-a", "ghost")


def test_update_preserves_disabled_state(env):
    """§6.2 — 꺼진 플러그인은 꺼진 채 새 버전이 된다."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    env.activation_service.disable("org-a", "plugin-a")

    head = env.install_service.update("org-a", "plugin-a")
    assert head == "abc1234"
    assert ("pull", str(env.paths.plugin_clone_dir("org-a", "plugin-a"))) in (
        env.git.calls)
    assert (env.activation_service.state("org-a", "plugin-a")
            is PluginState.INSTALLED)  # 활성 상태 보존


def test_update_not_installed_raises(env):
    with pytest.raises(PmError):
        env.install_service.update("org-a", "ghost")


def test_enable_not_installed_raises(env):
    with pytest.raises(RegistryError):
        env.activation_service.enable("org-a", "ghost")
