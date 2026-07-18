"""REST 전 엔드포인트 계약 테스트 (M5) — 정상·오류 코드 (§10.2 라우팅)."""

from __future__ import annotations

import json

from pm.errors import AuthError, PmError
from pm.models import PluginState
from pm.services.inspect_service import PluginStatus
from pm.services.preset_service import MemberResult

from fakes import make_plugin


def _sse_events(response):
    events = []
    for line in response.get_data(as_text=True).splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


# ── auth (§12.6) ─────────────────────────────────────────────
def test_login_success_and_session(client, container):
    res = client.post("/api/login", json={"id": "ageokim", "token": "t"})
    assert res.status_code == 200
    assert res.get_json()["verified"] is True

    session = client.get("/api/session").get_json()
    assert session["logged_in"] is True and session["id"] == "ageokim"


def test_login_missing_fields_400(client):
    assert client.post("/api/login", json={"id": "x"}).status_code == 400


def test_login_invalid_token_401(client, container):
    container.auth.login_error = AuthError("토큰 무효")
    res = client.post("/api/login", json={"id": "x", "token": "bad"})
    assert res.status_code == 401
    assert "토큰" in res.get_json()["error"]


def test_unverified_session_reported(client, container):
    container.auth.unverified = True
    res = client.post("/api/login", json={"id": "x", "token": "t"})
    assert res.get_json()["verified"] is False  # 미검증 세션 (§10.2)
    assert client.get("/api/session").get_json()["unverified"] is True


def test_logout(client, container):
    container.auth.saved = {"id": "a", "token": "t"}
    assert client.post("/api/logout").status_code == 200
    assert container.auth.logged_out


# ── orgs (§10.2 실패 라우팅) ─────────────────────────────────
def test_org_add_scan_and_list(client, container):
    container.catalog_service.plugins = [make_plugin("org-a", "p1")]
    res = client.post("/api/orgs", json={"url": "https://ghes/org-a"})
    assert res.status_code == 201
    assert res.get_json()["plugin_count"] == 1
    assert container.catalog_service.scanned == ["org-a"]

    rows = client.get("/api/orgs").get_json()
    assert rows[0]["name"] == "org-a" and rows[0]["authorized"] is True


def test_org_add_token_invalid_routes_401(client, container):
    container.org_service.add_error = AuthError("토큰 무효")
    res = client.post("/api/orgs", json={"url": "https://ghes/org-x"})
    assert res.status_code == 401  # 로그인 창 복귀 (§10.2)


def test_org_add_membership_denied_routes_400(client, container):
    container.org_service.add_error = PmError("이 organization에 권한 없음")
    res = client.post("/api/orgs", json={"url": "https://ghes/org-x"})
    assert res.status_code == 400  # 인라인 표시 — 세션 유지 (§10.2)


def test_org_remove_deletes_installs(client, container):
    res = client.delete("/api/orgs/org-a")
    assert res.status_code == 200
    body = res.get_json()
    assert body["removed_plugins"] == 2  # 설치본 함께 삭제 (§12.2)
    assert "함께 삭제" in body["note"]
    assert container.org_service.removed == ["org-a"]


# ── plugins ──────────────────────────────────────────────────
def test_plugins_list_cached_states(client, container):
    container.catalog_service.plugins = [make_plugin("org-a", "p1")]
    container.activation_service.states[("org-a", "p1")] = \
        PluginState.ENABLED
    rows = client.get("/api/plugins?cached=1").get_json()
    assert rows == [{
        "ref": "org-a/p1", "org": "org-a", "name": "p1",
        "state": "enabled", "description": "", "has_tags": True,
    }]
    assert container.catalog_service.scanned == []  # cached=1 → 스캔 없음


def test_plugins_actions(client, container):
    container.catalog_service.plugins = [make_plugin("org-a", "p1")]
    res = client.post("/api/plugins/org-a/p1/install",
                      json={"enable": False})
    assert res.status_code == 200 and res.get_json()["enabled"] is False

    assert client.post("/api/plugins/org-a/p1/enable").status_code == 200
    assert ("enable", "org-a", "p1") in container.activation_service.calls

    res = client.post("/api/plugins/org-a/p1/update")
    assert res.get_json()["head"] == "abc1234"

    assert client.post("/api/plugins/org-a/p1/uninstall").status_code == 200
    assert ("uninstall", "org-a", "p1") in container.install_service.calls

    assert client.post("/api/plugins/org-a/p1/폭파").status_code == 400


def test_plugin_install_unknown_404(client):
    assert client.post("/api/plugins/x/y/install").status_code == 404


def test_inspect_and_repair(client, container):
    container.inspect_service.statuses = [
        PluginStatus(org="org-a", name="p1", entry_name="p1",
                     state=PluginState.INSTALLED, issues=("버전차",)),
    ]
    rows = client.get("/api/inspect").get_json()
    assert rows[0]["state"] == "installed" and rows[0]["issues"] == ["버전차"]
    res = client.post("/api/inspect/repair")
    assert "repaired" in res.get_json()["actions"][0]


# ── presets (§6.5) ───────────────────────────────────────────
def test_preset_crud_members_and_batch(client, container):
    assert client.post("/api/presets",
                       json={"name": "세트"}).status_code == 201
    res = client.post("/api/presets/세트/members",
                      json={"ref": "org-a/p1", "op": "add"})
    assert res.get_json()["members"] == ["org-a/p1"]

    container.preset_service.batch_results = [
        MemberResult(ref="org-a/p1", action="enabled", ok=True),
        MemberResult(ref="org-b/p2", action="failed", ok=False,
                     detail="clone 실패"),
    ]
    res = client.post("/api/presets/세트/apply")
    body = res.get_json()
    assert body["ok"] is False and len(body["results"]) == 2  # 부분 실패

    assert client.delete("/api/presets/세트").status_code == 200
    assert client.post("/api/presets/세트/폭파").status_code == 400
    assert client.post("/api/presets", json={}).status_code == 400


# ── chat (§12.3) ─────────────────────────────────────────────
def test_chat_streams_backend_events(client, chat_backend):
    res = client.post("/api/chat", json={"message": "안녕하세요"})
    assert res.status_code == 200
    assert res.mimetype == "text/event-stream"
    events = _sse_events(res)
    assert events[0] == {"type": "delta", "text": "안녕"}
    assert events[-1]["type"] == "done"
    assert chat_backend.calls == [("안녕하세요", None)]


def test_chat_resumes_session(client, chat_backend):
    client.post("/api/chat", json={"message": "이어서", "session_id": "s9"})
    assert chat_backend.calls == [("이어서", "s9")]


def test_chat_intercepts_pm_allowlist(client, chat_backend, container):
    res = client.post("/api/chat", json={"message": "pm list --cached"})
    events = _sse_events(res)
    assert events[0]["type"] == "pm-result"
    assert "비어 있음" in events[0]["text"]
    assert chat_backend.calls == []  # claude로 가지 않음


def test_chat_pm_escape_and_disallowed_pass_through(client, chat_backend):
    client.post("/api/chat", json={"message": " pm list"})  # 공백 이스케이프
    client.post("/api/chat", json={"message": "pm serve"})  # allowlist 밖
    assert [c[0] for c in chat_backend.calls] == [" pm list", "pm serve"]


def test_chat_empty_message_400(client):
    assert client.post("/api/chat", json={"message": "  "}).status_code == 400


# ── terminal token (§11) ─────────────────────────────────────
def test_term_token_requires_login(client, container):
    assert client.post("/api/term/token").status_code == 401
    container.auth.saved = {"id": "a", "token": "t"}
    res = client.post("/api/term/token")
    assert res.status_code == 200 and res.get_json()["token"]


# ── lifecycle (§12.5) ────────────────────────────────────────
def test_heartbeat_and_tab_close(client, app):
    assert client.post("/api/heartbeat", json={}).status_code == 400
    assert client.post("/api/heartbeat",
                       json={"session": "tab-1"}).status_code == 200
    manager = app.extensions["pm"]["lifecycle"]
    assert manager.active_sessions() == ["tab-1"]
    # sendBeacon은 text/plain 본문으로 세션 ID만 보낸다
    assert client.post("/api/tab-close", data="tab-1").status_code == 200
    assert manager.active_sessions() == []


def test_index_serves_static_web(client, container):
    web = container.paths.root / "web"
    web.mkdir(parents=True, exist_ok=True)
    (web / "index.html").write_text("<h1>pm</h1>", encoding="utf-8")
    res = client.get("/")
    assert res.status_code == 200 and b"pm" in res.data
