"""pm.models 테스트."""

from __future__ import annotations

import dataclasses
import itertools

import pytest

from pm.models import (CheckResult, Org, OrgKind, Plugin, PluginState, Preset,
                       derive_state)

_PLUGIN_DATA = {
    "name": "plugin-a",
    "org": "org-a",
    "github_addr": "https://github.xxx.xxx/org-a/plugin-a",
    "clone_url": "https://github.xxx.xxx/org-a/plugin-a.git",
    "description": "데모 #plugin #release",
    "private": True,
    "has_tags": True,
}

_ORG_DATA = {
    "name": "org-a",
    "url": "https://github.xxx.xxx/org-a",
    "host": "github.xxx.xxx",
    "kind": "org",
    "added_at": "2026-07-14T02:00:00+00:00",
}


def test_enum_values_are_stable():
    assert PluginState.AVAILABLE.value == "available"
    assert PluginState.INSTALLED.value == "installed"
    assert PluginState.ENABLED.value == "enabled"
    assert OrgKind.ORG.value == "org"
    assert OrgKind.USER.value == "user"


@pytest.mark.parametrize(
    "cloned,linked",
    list(itertools.product([True, False], repeat=2)),
)
def test_derive_state_truth_table(cloned, linked):
    state = derive_state(cloned=cloned, linked=linked)
    if cloned and linked:
        assert state is PluginState.ENABLED
    elif cloned:
        assert state is PluginState.INSTALLED
    else:
        assert state is PluginState.AVAILABLE  # 링크만 잔존 = 드리프트 (§6.4)


def test_plugin_roundtrip():
    plugin = Plugin.from_dict(_PLUGIN_DATA)
    assert plugin.to_dict() == _PLUGIN_DATA
    assert Plugin.from_dict(plugin.to_dict()) == plugin


def test_plugin_ref():
    assert Plugin.from_dict(_PLUGIN_DATA).ref == "org-a/plugin-a"


def test_plugin_from_dict_ignores_unknown_keys():
    data = dict(_PLUGIN_DATA, ref="v1.2", extra="future")
    assert Plugin.from_dict(data) == Plugin.from_dict(_PLUGIN_DATA)


def test_plugin_frozen():
    plugin = Plugin.from_dict(_PLUGIN_DATA)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plugin.name = "other"


def test_org_roundtrip_with_enum():
    org = Org.from_dict(_ORG_DATA)
    assert org.kind is OrgKind.ORG
    assert org.to_dict() == _ORG_DATA
    assert Org.from_dict(org.to_dict()) == org


def test_org_user_kind():
    data = dict(_ORG_DATA, name="ageokim", kind="user")
    assert Org.from_dict(data).kind is OrgKind.USER


def test_org_invalid_kind_raises():
    with pytest.raises(ValueError):
        Org.from_dict(dict(_ORG_DATA, kind="team"))


def test_preset_roundtrip_members_tuple():
    data = {
        "name": "code-review-set",
        "members": ["org-a/plugin-a", "org-b/plugin-x"],
        "created_at": "2026-07-14T03:00:00+00:00",
    }
    preset = Preset.from_dict(data)
    assert isinstance(preset.members, tuple)
    assert preset.to_dict() == data
    assert isinstance(preset.to_dict()["members"], list)


def test_check_result_defaults():
    result = CheckResult(
        check_id="python-version",
        name="python ≥ 3.8 발견",
        passed=True,
        detail="3.11.6",
    )
    assert result.fix_command is None
    assert result.informational is False
