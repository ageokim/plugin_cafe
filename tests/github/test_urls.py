"""pm.github.urls 테스트 — §10.3·§10.4 입력 매트릭스."""

from __future__ import annotations

import pytest

from pm.errors import GitHubError
from pm.github.urls import ApiUrlBuilder, parse_host, parse_target


@pytest.mark.parametrize(
    "text,expected",
    [
        ("https://github.xxx.xxx/org-a", ("github.xxx.xxx", "org-a")),
        ("https://github.com/org-a/", ("github.com", "org-a")),
        ("http://GitHub.COM/org-a", ("github.com", "org-a")),
        ("github.xxx.xxx/org-a", ("github.xxx.xxx", "org-a")),
        ("github.com/org-a/repo-b", ("github.com", "org-a")),
        ("org-a", (None, "org-a")),
        ("git@github.xxx.xxx:org-a/repo.git", ("github.xxx.xxx", "org-a")),
        ("ssh://git@github.xxx.xxx/org-a", ("github.xxx.xxx", "org-a")),
        ("https://github.xxx.xxx:8443/org-a", ("github.xxx.xxx:8443", "org-a")),
        ("  https://github.com/org-a  ", ("github.com", "org-a")),
    ],
)
def test_parse_target(text, expected):
    assert parse_target(text) == expected


@pytest.mark.parametrize("text", ["", "   ", "https://", "github.xxx.xxx/"])
def test_parse_target_invalid(text):
    with pytest.raises(GitHubError):
        parse_target(text)


def test_parse_host():
    assert parse_host("https://github.xxx.xxx/org-a") == "github.xxx.xxx"
    assert parse_host("org-a") is None


def test_api_base_github_com():
    builder = ApiUrlBuilder()
    assert builder.api_base("github.com") == "https://api.github.com"
    assert builder.api_base("GitHub.com") == "https://api.github.com"
    assert builder.api_base("www.github.com") == "https://api.github.com"


def test_api_base_ghes():
    builder = ApiUrlBuilder()
    assert (builder.api_base("github.xxx.xxx") ==
            "https://github.xxx.xxx/api/v3")


def test_api_base_override_wins():
    builder = ApiUrlBuilder(override="https://custom.example/api/")
    assert builder.api_base("github.com") == "https://custom.example/api"
    assert builder.api_base("github.xxx.xxx") == "https://custom.example/api"
