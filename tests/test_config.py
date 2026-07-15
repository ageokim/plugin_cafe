"""pm.config 테스트 — os.environ·실 파일 미접촉."""

from __future__ import annotations

import pytest

from pm.config import DEFAULTS, ConfigProvider
from pm.errors import ConfigError


def test_defaults_for_all_keys():
    provider = ConfigProvider()
    assert provider.github_host is None
    assert provider.github_api_base is None
    assert provider.plugin_tags == ["#plugin", "#release"]
    assert provider.ca_bundle is None
    assert provider.flask_port == 8765
    assert provider.http_timeout == 10.0
    assert provider.github_per_page == 100
    assert provider.snapshot() == {
        key: provider.get(key) for key in DEFAULTS
    }


def test_file_overrides_default():
    provider = ConfigProvider(file_loader=lambda: {"flask_port": 9000})
    assert provider.flask_port == 9000


def test_env_overrides_file():
    provider = ConfigProvider(
        file_loader=lambda: {"flask_port": 9000},
        env={"PM_FLASK_PORT": "9001"},
    )
    assert provider.flask_port == 9001


def test_env_alias_pm_port():
    provider = ConfigProvider(env={"PM_PORT": "9002"})
    assert provider.flask_port == 9002


def test_cli_overrides_env():
    provider = ConfigProvider(
        env={"PM_PORT": "9002"},
        cli_overrides={"flask_port": 9003},
    )
    assert provider.flask_port == 9003


def test_cli_none_falls_through():
    provider = ConfigProvider(
        env={"PM_PORT": "9002"},
        cli_overrides={"flask_port": None},
    )
    assert provider.flask_port == 9002


def test_env_list_parsing():
    provider = ConfigProvider(env={"PM_PLUGIN_TAGS": "#a, #b"})
    assert provider.plugin_tags == ["#a", "#b"]


def test_env_str_key():
    provider = ConfigProvider(env={"PM_GITHUB_HOST": "github.xxx.xxx"})
    assert provider.github_host == "github.xxx.xxx"


def test_env_float_conversion():
    provider = ConfigProvider(env={"PM_HTTP_TIMEOUT": "2.5"})
    assert provider.http_timeout == 2.5


def test_env_bad_int_raises():
    provider = ConfigProvider(env={"PM_PORT": "abc"})
    with pytest.raises(ConfigError):
        _ = provider.flask_port


def test_unknown_key_get_raises():
    with pytest.raises(ConfigError):
        ConfigProvider().get("nope")


def test_unknown_file_key_warns_and_ignored(caplog):
    with caplog.at_level("WARNING"):
        provider = ConfigProvider(file_loader=lambda: {"future_key": 1})
    assert "future_key" in caplog.text
    with pytest.raises(ConfigError):
        provider.get("future_key")


def test_file_non_dict_warns_and_uses_defaults(caplog):
    # config.json에 null·문자열 등 비객체 유효 JSON — 기동은 계속돼야 한다
    with caplog.at_level("WARNING"):
        provider = ConfigProvider(file_loader=lambda: None)
    assert provider.flask_port == 8765
    assert "객체가 아니라" in caplog.text


def test_file_null_value_means_unset():
    provider = ConfigProvider(file_loader=lambda: {"flask_port": None})
    assert provider.flask_port == 8765


def test_file_wrong_type_warns_and_ignored(caplog):
    with caplog.at_level("WARNING"):
        provider = ConfigProvider(file_loader=lambda: {"flask_port": "9000"})
    assert provider.flask_port == 8765
    assert "flask_port" in caplog.text


def test_file_bool_for_int_key_ignored(caplog):
    with caplog.at_level("WARNING"):
        provider = ConfigProvider(file_loader=lambda: {"flask_port": True})
    assert provider.flask_port == 8765


def test_file_float_key_accepts_int():
    provider = ConfigProvider(file_loader=lambda: {"http_timeout": 5})
    assert provider.http_timeout == 5


def test_empty_env_value_falls_through():
    # 빈 문자열 env는 미설정 취급 — PM_HOME 규약과 동일
    provider = ConfigProvider(
        file_loader=lambda: {"github_host": "github.xxx.xxx"},
        env={"PM_PORT": "", "PM_GITHUB_HOST": ""},
    )
    assert provider.flask_port == 8765
    assert provider.github_host == "github.xxx.xxx"


def test_returned_list_is_a_copy():
    provider = ConfigProvider()
    provider.plugin_tags.append("#hacked")
    assert provider.plugin_tags == ["#plugin", "#release"]
    assert DEFAULTS["plugin_tags"] == ["#plugin", "#release"]


def test_reload_picks_up_new_file_content():
    content = {}
    provider = ConfigProvider(file_loader=lambda: dict(content))
    assert provider.flask_port == 8765
    content["flask_port"] = 9100
    provider.reload()
    assert provider.flask_port == 9100


def test_os_environ_not_read(monkeypatch):
    monkeypatch.setenv("PM_FLASK_PORT", "1")
    provider = ConfigProvider(env={})
    assert provider.flask_port == 8765
