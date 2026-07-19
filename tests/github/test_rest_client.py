"""pm.github.rest_client 테스트 — fake session 주입, 네트워크 없음."""

from __future__ import annotations

import pytest

from pm.errors import AuthError, GitHubError
from pm.github.rest_client import RestGitHubClient
from pm.models import OrgKind

_BASE = "https://api.example/api/v3"


class FakeResponse:
    """requests.Response의 사용 표면(status/json/headers/links/text)만 흉내."""

    def __init__(self, status_code=200, json_data=None, headers=None,
                 links=None, text=""):
        self.status_code = status_code
        self._json = json_data
        self.headers = headers or {}
        self.links = links or {}
        self.text = text

    def json(self):
        if self._json is None:
            raise ValueError("본문이 JSON이 아님")
        return self._json


class FakeSession:
    """URL별 응답 큐 — 호출 인자를 전부 기록한다."""

    def __init__(self):
        self._routes = {}
        self.calls = []

    def queue(self, url, *responses):
        self._routes.setdefault(url, []).extend(responses)

    def get(self, url, headers=None, params=None, timeout=None, verify=None):
        """큐에서 응답을 꺼낸다 — 미등록 URL은 404."""
        self.calls.append({
            "url": url,
            "headers": headers,
            "params": params,
            "timeout": timeout,
            "verify": verify,
        })
        queued = self._routes.get(url)
        if not queued:
            return FakeResponse(404, json_data={"message": "Not Found"})
        return queued.pop(0)


def _client(session, token="ghp_x", **kwargs):
    return RestGitHubClient(
        _BASE,
        token_provider=lambda: token,
        session=session,
        **kwargs,
    )


def _repo(name, description="", private=False):
    return {
        "name": name,
        "description": description,
        "private": private,
        "html_url": f"https://example/{name}",
        "clone_url": f"https://example/{name}.git",
    }


# --- verify_token (§10.2) ---


def test_verify_token_returns_login():
    session = FakeSession()
    session.queue(_BASE + "/user", FakeResponse(200, {"login": "ageokim"}))
    assert _client(session).verify_token() == "ageokim"


def test_verify_token_401_raises_auth_error():
    session = FakeSession()
    session.queue(_BASE + "/user", FakeResponse(401, {"message": "Bad"}))
    with pytest.raises(AuthError):
        _client(session).verify_token()


def test_auth_header_present_with_token():
    session = FakeSession()
    session.queue(_BASE + "/user", FakeResponse(200, {"login": "x"}))
    _client(session, token="ghp_secret").verify_token()
    assert session.calls[0]["headers"]["Authorization"] == "token ghp_secret"


def test_no_auth_header_without_token():
    session = FakeSession()
    session.queue(_BASE + "/user", FakeResponse(200, {"login": "x"}))
    _client(session, token=None).verify_token()
    assert "Authorization" not in session.calls[0]["headers"]


def test_ca_bundle_and_timeout_passed_through():
    session = FakeSession()
    session.queue(_BASE + "/user", FakeResponse(200, {"login": "x"}))
    _client(session, ca_bundle="/etc/ca.pem", timeout=3.5).verify_token()
    assert session.calls[0]["verify"] == "/etc/ca.pem"
    assert session.calls[0]["timeout"] == 3.5


# --- resolve_target (§10.1) ---


def test_resolve_target_org():
    session = FakeSession()
    session.queue(_BASE + "/orgs/org-a", FakeResponse(200, {"login": "org-a"}))
    assert _client(session).resolve_target("org-a") is OrgKind.ORG


def test_resolve_target_user_after_org_miss():
    session = FakeSession()
    session.queue(_BASE + "/users/ageokim",
                  FakeResponse(200, {"login": "ageokim"}))
    assert _client(session).resolve_target("ageokim") is OrgKind.USER


def test_resolve_target_missing_raises():
    session = FakeSession()
    with pytest.raises(GitHubError):
        _client(session).resolve_target("ghost")


# --- fetch_repos 3-way (§10.1) ---


def test_fetch_repos_org_uses_type_all():
    session = FakeSession()
    session.queue(_BASE + "/orgs/org-a/repos",
                  FakeResponse(200, [_repo("r1", private=True)]))
    repos = _client(session).fetch_repos("org-a", OrgKind.ORG)
    call = session.calls[0]
    assert call["params"] == {"type": "all", "per_page": 100}
    assert repos[0]["name"] == "r1"
    assert repos[0]["private"] is True


def test_fetch_repos_other_user_uses_type_owner():
    session = FakeSession()
    session.queue(_BASE + "/users/octocat/repos",
                  FakeResponse(200, [_repo("r1")]))
    _client(session).fetch_repos("octocat", OrgKind.USER,
                                 viewer_login="ageokim")
    assert session.calls[0]["url"] == _BASE + "/users/octocat/repos"
    assert session.calls[0]["params"]["type"] == "owner"


def test_fetch_repos_self_uses_user_repos():
    session = FakeSession()
    session.queue(_BASE + "/user/repos", FakeResponse(200, [_repo("mine")]))
    _client(session).fetch_repos("AgeoKim", OrgKind.USER,
                                 viewer_login="ageokim")  # 대소문자 무관
    assert session.calls[0]["url"] == _BASE + "/user/repos"
    assert session.calls[0]["params"]["type"] == "owner"


def test_fetch_repos_without_viewer_falls_back_to_users_path():
    session = FakeSession()
    session.queue(_BASE + "/users/ageokim/repos", FakeResponse(200, []))
    _client(session).fetch_repos("ageokim", OrgKind.USER)
    assert session.calls[0]["url"] == _BASE + "/users/ageokim/repos"


def test_fetch_repos_pagination_follows_link_header():
    session = FakeSession()
    page2_url = _BASE + "/orgs/org-a/repos?page=2"
    session.queue(
        _BASE + "/orgs/org-a/repos",
        FakeResponse(200, [_repo("r1")],
                     links={"next": {"url": page2_url}}),
    )
    session.queue(page2_url, FakeResponse(200, [_repo("r2")]))
    repos = _client(session).fetch_repos("org-a", OrgKind.ORG)
    assert [repo["name"] for repo in repos] == ["r1", "r2"]
    # 두 번째 호출은 next URL 그대로 — params를 다시 붙이지 않는다
    assert session.calls[1]["url"] == page2_url
    assert session.calls[1]["params"] is None


def test_fetch_repos_description_none_becomes_empty():
    session = FakeSession()
    session.queue(_BASE + "/orgs/org-a/repos",
                  FakeResponse(200, [{"name": "r1", "description": None}]))
    repos = _client(session).fetch_repos("org-a", OrgKind.ORG)
    assert repos[0]["description"] == ""


def test_fetch_repos_401_raises_auth_error():
    session = FakeSession()
    session.queue(_BASE + "/orgs/org-a/repos", FakeResponse(401))
    with pytest.raises(AuthError):
        _client(session).fetch_repos("org-a", OrgKind.ORG)


def test_fetch_repos_403_rate_limit_message():
    session = FakeSession()
    session.queue(
        _BASE + "/orgs/org-a/repos",
        FakeResponse(
            403,
            {"message": "API rate limit exceeded"},
            headers={"X-RateLimit-Reset": "1752555600"},
        ),
    )
    with pytest.raises(GitHubError) as exc_info:
        _client(session).fetch_repos("org-a", OrgKind.ORG)
    assert "한도" in str(exc_info.value)
    assert "1752555600" in str(exc_info.value)


def test_fetch_repos_plain_403_is_permission_error():
    session = FakeSession()
    session.queue(_BASE + "/orgs/org-a/repos",
                  FakeResponse(403, {"message": "Forbidden"}))
    with pytest.raises(GitHubError) as exc_info:
        _client(session).fetch_repos("org-a", OrgKind.ORG)
    assert "403" in str(exc_info.value)
    assert "한도" not in str(exc_info.value)


# --- check_org_membership (§10.2) ---


def test_membership_active():
    session = FakeSession()
    session.queue(_BASE + "/user/memberships/orgs/org-a",
                  FakeResponse(200, {"state": "active"}))
    assert _client(session).check_org_membership("org-a") is True


def test_membership_pending_rejected():
    session = FakeSession()
    session.queue(_BASE + "/user/memberships/orgs/org-a",
                  FakeResponse(200, {"state": "pending"}))
    assert _client(session).check_org_membership("org-a") is False


def test_membership_404_rejected():
    session = FakeSession()
    assert _client(session).check_org_membership("org-a") is False


def test_membership_401_raises_auth_error():
    session = FakeSession()
    session.queue(_BASE + "/user/memberships/orgs/org-a", FakeResponse(401))
    with pytest.raises(AuthError):
        _client(session).check_org_membership("org-a")


def test_membership_rate_limit_raises_not_false():
    session = FakeSession()
    session.queue(
        _BASE + "/user/memberships/orgs/org-a",
        FakeResponse(403, {"message": "API rate limit exceeded"}),
    )
    with pytest.raises(GitHubError):
        _client(session).check_org_membership("org-a")
