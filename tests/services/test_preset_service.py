"""PresetService 테스트 — §6.5 CRUD·일괄·부분 실패 무중단·apply."""

from __future__ import annotations

# pytest fixture 패턴 — fixture 이름을 인자로 받는 것은 정상이다
# pylint: disable=redefined-outer-name

import pytest

from pm.errors import PmError
from pm.models import PluginState
from pm.services.preset_service import PresetBadge

FIXED_NOW = "2026-07-15T00:00:00+00:00"


@pytest.fixture
def ready(env):
    """org 등록 + 카탈로그에 plugin-a/plugin-b가 있는 상태."""
    env.login_and_register_org("org-a")
    env.catalog_plugin("org-a", "plugin-a")
    env.catalog_plugin("org-a", "plugin-b")
    return env


def _state(env, ref):
    org, _, name = ref.partition("/")
    return env.activation_service.state(org, name)


# --- CRUD (§6.5·§8.5) ---


def test_create_and_persist_schema(env):
    env.preset_service.create("code-review-set")
    env.preset_service.add_member("code-review-set", "org-a/plugin-a")
    assert env.presets_store.read() == {
        "presets": [{
            "name": "code-review-set",
            "members": ["org-a/plugin-a"],
            "created_at": FIXED_NOW,
        }]
    }  # §8.5 스키마와 1:1


def test_create_duplicate_or_empty_raises(env):
    env.preset_service.create("s")
    with pytest.raises(PmError):
        env.preset_service.create("s")
    with pytest.raises(PmError):
        env.preset_service.create("   ")


@pytest.mark.parametrize("bad_ref", ["plain", "a/b/c", "/x", "x/", " / "])
def test_add_member_requires_org_slash_name(env, bad_ref):
    env.preset_service.create("s")
    with pytest.raises(PmError):
        env.preset_service.add_member("s", bad_ref)


def test_add_and_remove_member(env):
    env.preset_service.create("s")
    env.preset_service.add_member("s", "org-a/plugin-a")
    with pytest.raises(PmError):
        env.preset_service.add_member("s", "org-a/plugin-a")  # 중복
    preset = env.preset_service.remove_member("s", "org-a/plugin-a")
    assert preset.members == ()
    with pytest.raises(PmError):
        env.preset_service.remove_member("s", "org-a/plugin-a")


def test_delete_definition_keeps_plugins(ready):
    """정의 삭제 ≠ 멤버 삭제 (§6.5)."""
    plugin = ready.catalog_service.find("org-a/plugin-a")[0]
    ready.install_service.install(plugin)
    ready.preset_service.create("s")
    ready.preset_service.add_member("s", "org-a/plugin-a")
    ready.preset_service.delete("s")
    assert ready.preset_service.list_presets() == []
    assert _state(ready, "org-a/plugin-a") is PluginState.ENABLED


def test_get_missing_raises(env):
    with pytest.raises(PmError):
        env.preset_service.get("ghost")


# --- 뱃지 (§6.5 실측 도출) ---


def test_badge_derivation(ready):
    ready.preset_service.create("s")
    assert ready.preset_service.badge("s") is PresetBadge.OFF  # 빈 preset
    ready.preset_service.add_member("s", "org-a/plugin-a")
    ready.preset_service.add_member("s", "org-a/plugin-b")
    assert ready.preset_service.badge("s") is PresetBadge.OFF

    ready.preset_service.enable("s")
    assert ready.preset_service.badge("s") is PresetBadge.ALL_ON

    ready.activation_service.disable("org-a", "plugin-b")
    assert ready.preset_service.badge("s") is PresetBadge.PARTIAL


# --- 일괄 실행 (§6.5) ---


def test_enable_auto_installs_missing_members(ready):
    ready.preset_service.create("s")
    ready.preset_service.add_member("s", "org-a/plugin-a")
    ready.preset_service.add_member("s", "org-a/plugin-b")
    results = ready.preset_service.enable("s")
    assert [(r.ref, r.action, r.ok) for r in results] == [
        ("org-a/plugin-a", "installed+enabled", True),
        ("org-a/plugin-b", "installed+enabled", True),
    ]
    assert _state(ready, "org-a/plugin-a") is PluginState.ENABLED
    assert _state(ready, "org-a/plugin-b") is PluginState.ENABLED


def test_enable_partial_failure_continues(ready):
    """한 멤버(깨진 참조)가 실패해도 나머지는 진행 (§6.5)."""
    ready.preset_service.create("s")
    ready.preset_service.add_member("s", "org-x/ghost")  # 카탈로그에 없음
    ready.preset_service.add_member("s", "org-a/plugin-a")
    results = ready.preset_service.enable("s")
    assert results[0].action == "broken-ref"
    assert results[0].ok is False
    assert results[1].ok is True  # 계속 진행됨
    assert _state(ready, "org-a/plugin-a") is PluginState.ENABLED


def test_install_only_missing_and_skips(ready):
    plugin = ready.catalog_service.find("org-a/plugin-a")[0]
    ready.install_service.install(plugin)  # 이미 설치
    ready.preset_service.create("s")
    ready.preset_service.add_member("s", "org-a/plugin-a")
    ready.preset_service.add_member("s", "org-a/plugin-b")
    results = ready.preset_service.install("s")
    assert results[0].action == "skipped"
    assert results[1].action == "installed"
    assert _state(ready, "org-a/plugin-b") is PluginState.INSTALLED


def test_disable_and_uninstall_members(ready):
    ready.preset_service.create("s")
    ready.preset_service.add_member("s", "org-a/plugin-a")
    ready.preset_service.enable("s")

    disabled = ready.preset_service.disable("s")
    assert disabled[0].action == "disabled"
    assert _state(ready, "org-a/plugin-a") is PluginState.INSTALLED

    removed = ready.preset_service.uninstall("s")
    assert removed[0].action == "uninstalled"
    assert _state(ready, "org-a/plugin-a") is PluginState.AVAILABLE
    # 재실행은 skipped — 멱등
    assert ready.preset_service.uninstall("s")[0].action == "skipped"


def test_apply_disables_non_members(ready):
    """전환: 멤버만 켜고 나머지 설치본은 끔 — 비파괴 (§6.5)."""
    outsider = ready.catalog_service.find("org-a/plugin-b")[0]
    ready.install_service.install(outsider)  # 켜진 비멤버
    ready.preset_service.create("s")
    ready.preset_service.add_member("s", "org-a/plugin-a")

    results = ready.preset_service.apply("s")
    assert _state(ready, "org-a/plugin-a") is PluginState.ENABLED
    # 껐지만 삭제하지는 않는다 (비파괴)
    assert _state(ready, "org-a/plugin-b") is PluginState.INSTALLED
    disabled = [r for r in results if r.action == "disabled"]
    assert [r.ref for r in disabled] == ["org-a/plugin-b"]


def test_apply_leaves_disabled_non_members_alone(ready):
    outsider = ready.catalog_service.find("org-a/plugin-b")[0]
    ready.install_service.install(outsider, enable=False)
    ready.preset_service.create("s")
    ready.preset_service.add_member("s", "org-a/plugin-a")
    results = ready.preset_service.apply("s")
    assert all(r.ref != "org-a/plugin-b" or r.action != "disabled"
               for r in results)
    assert _state(ready, "org-a/plugin-b") is PluginState.INSTALLED
