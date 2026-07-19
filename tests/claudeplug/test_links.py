"""PluginLinks 단위 테스트 (§6.2, M10) — 실제 tmp 파일시스템 링크."""

from __future__ import annotations

import os

import pytest

from pm.claudeplug.links import PluginLinks
from pm.errors import RegistryError


@pytest.fixture
def links(tmp_paths):
    return PluginLinks(tmp_paths)


def clone(tmp_paths, org, name):
    d = tmp_paths.plugin_clone_dir(org, name)
    d.mkdir(parents=True)
    (d / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return d


def test_enable_creates_both_links(tmp_paths, links):
    target = clone(tmp_paths, "org-a", "plugin-a")
    assert links.enable("org-a", "plugin-a") == "plugin-a"
    root_link = tmp_paths.plugin_roots_dir / "plugin-a"
    abs_link = tmp_paths.plugin_links_dir / "plugin-a"
    assert root_link.resolve() == target.resolve()
    assert abs_link.resolve() == target.resolve()
    # 사내 관례: 1번은 상대, 2번은 절대 (§6.2)
    assert not os.path.isabs(os.readlink(str(root_link)))
    assert os.path.isabs(os.readlink(str(abs_link)))
    assert links.is_enabled("org-a", "plugin-a")


def test_enable_is_idempotent(tmp_paths, links):
    clone(tmp_paths, "org-a", "plugin-a")
    assert links.enable("org-a", "plugin-a") == "plugin-a"
    assert links.enable("org-a", "plugin-a") == "plugin-a"  # 재호출 무해


def test_enable_requires_clone(links):
    with pytest.raises(RegistryError):
        links.enable("org-a", "ghost")


def test_collision_gets_org_prefixed_name(tmp_paths, links):
    """§6.2 — 먼저 설치된 쪽 링크는 리네임하지 않고 신규만 {org}-{name}."""
    clone(tmp_paths, "org-a", "dup")
    clone(tmp_paths, "org-b", "dup")
    assert links.enable("org-a", "dup") == "dup"
    assert links.enable("org-b", "dup") == "org-b-dup"
    assert links.link_name_for("org-a", "dup") == "dup"  # 선점 유지
    assert links.link_name_for("org-b", "dup") == "org-b-dup"


def test_disable_removes_links_only(tmp_paths, links):
    target = clone(tmp_paths, "org-a", "plugin-a")
    links.enable("org-a", "plugin-a")
    assert links.disable("org-a", "plugin-a") == "plugin-a"
    assert not (tmp_paths.plugin_roots_dir / "plugin-a").exists()
    assert not (tmp_paths.plugin_links_dir / "plugin-a").exists()
    assert (target / "run.sh").is_file()  # 원본 무손상 (§6.2 안전 규칙)
    assert not links.is_enabled("org-a", "plugin-a")
    assert links.disable("org-a", "plugin-a") is None  # 멱등


def test_dangling_detection_and_cleanup(tmp_paths, links):
    import shutil
    target = clone(tmp_paths, "org-a", "plugin-a")
    links.enable("org-a", "plugin-a")
    shutil.rmtree(target)  # clone이 밖에서 지워진 드리프트
    assert links.dangling() == ["plugin-a"]
    assert links.remove_dangling() == ["plugin-a"]
    assert links.dangling() == []
    assert not (tmp_paths.plugin_roots_dir / "plugin-a").exists()


def test_all_links_lists_targets(tmp_paths, links):
    a = clone(tmp_paths, "org-a", "a")
    clone(tmp_paths, "org-b", "b")
    links.enable("org-a", "a")
    links.enable("org-b", "b")
    mapping = links.all_links()
    assert mapping["a"] == a.resolve()
    assert set(mapping) == {"a", "b"}
