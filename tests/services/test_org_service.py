"""OrgService 테스트 — §10.2 권한 게이트·host 정책·첫 org 흐름."""

from __future__ import annotations

import pytest

from pm.errors import AuthError, GitHubError, PmError
from pm.models import OrgKind

FIXED_NOW = "2026-07-15T00:00:00+00:00"
HOST = "github.xxx.xxx"


def test_first_org_full_flow(env):
    """미검증 로그인 → 첫 org: host 확정 + credentials 기록 (§10.2)."""
    org = env.login_and_register_org("org-a")
    assert env.config.github_host == HOST  # config.json 확정·reload됨
    assert env.credentials_store.read() == {"id": "ageokim",
                                            "token": "ghp_x"}
    assert env.auth.is_unverified() is False
    assert org.host == HOST
    assert org.kind is OrgKind.ORG
    assert org.added_at == FIXED_NOW
    assert [o.name for o in env.org_service.list_orgs()] == ["org-a"]


def test_first_org_bare_name_rejected(env):
    env.auth.login("ageokim", "ghp_x")
    with pytest.raises(GitHubError):
        env.org_service.add("org-a")  # host 미확정 — 전체 URL 필요


def test_membership_gate_rejects_and_writes_nothing(env):
    env.github.org_kinds["org-x"] = OrgKind.ORG  # 멤버십은 없음
    env.auth.login("ageokim", "ghp_x")
    with pytest.raises(GitHubError):
        env.org_service.add(f"https://{HOST}/org-x")
    assert env.org_service.list_orgs() == []
    assert not env.credentials_store.exists()  # 검증 실패 — 저장 안 함


def test_invalid_token_routes_to_login(env):
    env.github.fail_token = True
    env.auth.login("ageokim", "ghp_bad")
    with pytest.raises(AuthError):
        env.org_service.add(f"https://{HOST}/org-a")


def test_other_host_rejected_after_first(env):
    env.login_and_register_org("org-a")
    env.github.org_kinds["org-b"] = OrgKind.ORG
    env.github.memberships.add("org-b")
    with pytest.raises(GitHubError) as exc_info:
        env.org_service.add("https://other.host/org-b")
    assert "단일" in str(exc_info.value)


def test_second_org_bare_name_uses_configured_host(env):
    env.login_and_register_org("org-a")
    org = env.register_extra_org("org-b")
    assert org.host == HOST
    assert org.url == f"https://{HOST}/org-b"


def test_duplicate_org_rejected(env):
    env.login_and_register_org("org-a")
    with pytest.raises(PmError):
        env.org_service.add(f"https://{HOST}/org-a")


def test_personal_account_self_allowed(env):
    env.github.org_kinds["ageokim"] = OrgKind.USER
    env.auth.login("ageokim", "ghp_x")
    org = env.org_service.add(f"https://{HOST}/ageokim")
    assert org.kind is OrgKind.USER


def test_personal_account_other_rejected(env):
    env.github.org_kinds["octocat"] = OrgKind.USER
    env.auth.login("ageokim", "ghp_x")
    with pytest.raises(GitHubError) as exc_info:
        env.org_service.add(f"https://{HOST}/octocat")
    assert "본인" in str(exc_info.value)


def test_add_without_login_raises(env):
    env.config_store.write({"github_host": HOST})
    env.config.reload()
    env.github.org_kinds["org-a"] = OrgKind.ORG
    with pytest.raises(AuthError):
        env.org_service.add("org-a")


def test_remove_keeps_other_orgs(env):
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    assert env.org_service.remove("org-a") == (0, 0)  # 설치본·preset 없음
    assert [o.name for o in env.org_service.list_orgs()] == ["org-b"]


def test_remove_deletes_installed_clones(env):
    """org 제거 = 그 org의 설치본(clone·링크·활성)까지 함께 정리 (§12.2)."""
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    env.install_service.install(env.catalog_plugin("org-a", "plugin-a"))
    env.install_service.install(env.catalog_plugin("org-a", "plugin-c"))
    env.install_service.install(env.catalog_plugin("org-b", "plugin-x"))

    assert env.org_service.remove("org-a") == (2, 0)
    assert not env.paths.plugin_clone_dir("org-a", "plugin-a").exists()
    assert not env.paths.plugin_clone_dir("org-a", "plugin-c").exists()
    # 다른 org 설치본은 무영향
    assert env.paths.plugin_clone_dir("org-b", "plugin-x").is_dir()
    from pm.models import PluginState
    assert env.activation_service.state(
        "org-b", "plugin-x") is PluginState.ENABLED


def test_remove_prunes_preset_members(env):
    """org 삭제 시 preset에서 그 org 멤버가 빠진다 — 정의는 유지 (§12.2)."""
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    env.install_service.install(env.catalog_plugin("org-a", "plugin-a"))
    env.preset_service.create("세트")
    env.preset_service.add_member("세트", "org-a/plugin-a")
    env.preset_service.add_member("세트", "org-b/plugin-x")

    assert env.org_service.remove("org-a") == (1, 1)
    preset = env.preset_service.get("세트")
    assert preset.members == ("org-b/plugin-x",)  # 타 org 멤버는 유지


def test_remove_missing_raises(env):
    with pytest.raises(PmError):
        env.org_service.remove("ghost")


def test_revalidate_all(env):
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    env.github.org_kinds["ageokim"] = OrgKind.USER
    env.org_service.add("ageokim")
    env.github.memberships.discard("org-b")  # 권한 상실 (§10.2)
    results = env.org_service.revalidate_all()
    assert results == {"org-a": True, "org-b": False, "ageokim": True}
