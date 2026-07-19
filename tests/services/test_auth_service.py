"""AuthService 테스트 — §10.2 로그인·미검증 세션·자동 저장."""

from __future__ import annotations

import pytest

from pm.errors import AuthError


def _set_host(env, host="github.xxx.xxx"):
    env.config_store.write({"github_host": host})
    env.config.reload()


def test_login_without_host_enters_unverified_session(env):
    result = env.auth.login("ageokim", "ghp_x")
    assert result.verified is False
    assert env.auth.is_unverified() is True
    assert not env.credentials_store.exists()  # 저장은 첫 org 검증 후 (§10.2)
    assert env.auth.current_token() == "ghp_x"  # 메모리에만


def test_login_with_host_verifies_and_saves(env):
    _set_host(env)
    result = env.auth.login("ageokim", "ghp_x")
    assert result.verified is True
    assert result.login == "ageokim"
    assert result.first_save is True
    assert env.credentials_store.read() == {"id": "ageokim",
                                            "token": "ghp_x"}
    assert env.auth.is_unverified() is False


def test_second_login_is_not_first_save(env):
    _set_host(env)
    env.auth.login("ageokim", "ghp_x")
    result = env.auth.login("ageokim", "ghp_y")
    assert result.first_save is False
    assert env.auth.current_token() == "ghp_y"


def test_login_id_case_insensitive(env):
    _set_host(env)
    assert env.auth.login("AgeoKim", "ghp_x").verified is True


def test_login_id_mismatch_raises_and_clears_pending(env):
    _set_host(env)
    with pytest.raises(AuthError):
        env.auth.login("someone-else", "ghp_x")
    assert env.auth.is_unverified() is False
    assert not env.credentials_store.exists()


def test_login_invalid_token_raises(env):
    _set_host(env)
    env.github.fail_token = True
    with pytest.raises(AuthError):
        env.auth.login("ageokim", "ghp_bad")
    assert not env.credentials_store.exists()


def test_login_empty_inputs_raise(env):
    with pytest.raises(AuthError):
        env.auth.login("", "ghp_x")
    with pytest.raises(AuthError):
        env.auth.login("ageokim", "   ")


def test_commit_pending_without_pending_raises(env):
    with pytest.raises(AuthError):
        env.auth.commit_pending()


def test_verify_current_without_login_raises(env):
    with pytest.raises(AuthError):
        env.auth.verify_current()


def test_logout_keeps_file_and_new_login_overwrites(env):
    # 로그아웃은 화면 복귀일 뿐 — 파일 유지, 새 계정 로그인이 덮어씀 (§12.6)
    _set_host(env)
    env.auth.login("ageokim", "ghp_x")
    env.auth.logout()
    assert env.credentials_store.exists()
    assert env.auth.load_saved() == {"id": "ageokim", "token": "ghp_x"}

    env.github.login = "other-user"
    env.auth.login("other-user", "ghp_new")
    assert env.auth.load_saved() == {"id": "other-user", "token": "ghp_new"}


def test_current_token_prefers_pending_over_saved(env):
    _set_host(env)
    env.auth.login("ageokim", "ghp_saved")
    env.config_store.write({})  # host 제거 → 다음 로그인은 미검증 보류
    env.config.reload()
    env.auth.login("ageokim", "ghp_pending")
    assert env.auth.current_token() == "ghp_pending"
