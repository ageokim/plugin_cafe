"""CatalogService 테스트 — §8.3 전량 저장·태그 필터·병합."""

from __future__ import annotations

import pytest

from pm.errors import PmError
from pm.models import OrgKind

HOST = "github.xxx.xxx"


def _add_repo(env, org, name, description):
    env.github.repos.setdefault(org, []).append({
        "name": name,
        "description": description,
        "private": False,
        "html_url": f"https://{HOST}/{org}/{name}",
        "clone_url": f"https://{HOST}/{org}/{name}.git",
    })


def test_scan_stores_all_repos_with_has_tags_flag(env):
    env.login_and_register_org("org-a")
    _add_repo(env, "org-a", "tagged", "데모 #plugin #release")
    _add_repo(env, "org-a", "plain", "그냥 repo")
    env.catalog_service.scan()

    stored = env.catalog_store.read()["orgs"]["org-a"]["plugins"]
    assert {p["name"]: p["has_tags"] for p in stored} == {
        "tagged": True, "plain": False}  # 보이는 repo 전부 저장 (§7)


def test_cached_filters_tags_by_default(env):
    env.login_and_register_org("org-a")
    _add_repo(env, "org-a", "tagged", "#plugin #release")
    _add_repo(env, "org-a", "plain", "x")
    env.catalog_service.scan()

    default = env.catalog_service.cached()
    assert [p.name for p in default["org-a"]] == ["tagged"]
    everything = env.catalog_service.cached(include_all=True)
    assert len(everything["org-a"]) == 2  # --all은 같은 캐시 (§7)


def test_scan_single_org_merges_cache(env):
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    _add_repo(env, "org-a", "a1", "#plugin #release")
    _add_repo(env, "org-b", "b1", "#plugin #release")
    env.catalog_service.scan()
    _add_repo(env, "org-a", "a2", "#plugin #release")
    env.catalog_service.scan("org-a")  # org-a만 재스캔

    cached = env.catalog_service.cached()
    assert [p.name for p in cached["org-a"]] == ["a1", "a2"]
    assert [p.name for p in cached["org-b"]] == ["b1"]  # 보존


def test_scan_passes_viewer_login_for_3way(env):
    env.github.org_kinds["ageokim"] = OrgKind.USER
    env.auth.login("ageokim", "ghp_x")
    env.org_service.add(f"https://{HOST}/ageokim")
    env.catalog_service.scan()
    name, kind, viewer = env.github.last_fetch
    assert (name, kind, viewer) == ("ageokim", OrgKind.USER, "ageokim")


def test_scan_unknown_org_raises(env):
    env.login_and_register_org("org-a")
    with pytest.raises(PmError):
        env.catalog_service.scan("ghost")


def test_find_by_ref_and_bare_name(env):
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    _add_repo(env, "org-a", "plugin-a", "#plugin #release")
    _add_repo(env, "org-b", "plugin-a", "#plugin #release")
    env.catalog_service.scan()

    exact = env.catalog_service.find("org-a/plugin-a")
    assert len(exact) == 1 and exact[0].org == "org-a"
    bare = env.catalog_service.find("plugin-a")
    assert {p.org for p in bare} == {"org-a", "org-b"}  # 유일성 판정은 CLI 몫
    assert env.catalog_service.find("ghost") == []


def test_plugin_fields_match_schema(env):
    env.login_and_register_org("org-a")
    _add_repo(env, "org-a", "plugin-a", "설명 #plugin #release")
    env.catalog_service.scan()
    plugin = env.catalog_service.find("org-a/plugin-a")[0]
    assert plugin.github_addr == f"https://{HOST}/org-a/plugin-a"
    assert plugin.clone_url == f"https://{HOST}/org-a/plugin-a.git"
    assert plugin.ref == "org-a/plugin-a"
