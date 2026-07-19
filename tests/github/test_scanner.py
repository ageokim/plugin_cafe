"""pm.github.scanner 테스트 — 부록 A.1 태그 정책."""

from __future__ import annotations

from pm.github.scanner import filter_plugin_repos, has_plugin_tags

_TAGS = ["#plugin", "#release"]


def test_all_tags_present():
    assert has_plugin_tags("데모 #plugin #release", _TAGS)


def test_partial_tags_rejected():
    assert not has_plugin_tags("데모 #plugin", _TAGS)
    assert not has_plugin_tags("데모 #release", _TAGS)


def test_case_insensitive():
    assert has_plugin_tags("demo #PLUGIN #Release", _TAGS)
    assert has_plugin_tags("demo #plugin #release", ["#Plugin", "#RELEASE"])


def test_none_or_empty_description():
    assert not has_plugin_tags(None, _TAGS)
    assert not has_plugin_tags("", _TAGS)


def test_empty_tags_means_no_filter():
    assert has_plugin_tags("아무거나", [])
    assert has_plugin_tags(None, [])


def test_filter_plugin_repos():
    repos = [
        {"name": "a", "description": "#plugin #release"},
        {"name": "b", "description": "#plugin"},
        {"name": "c", "description": None},
        {"name": "d"},
    ]
    kept = filter_plugin_repos(repos, _TAGS)
    assert [repo["name"] for repo in kept] == ["a"]
