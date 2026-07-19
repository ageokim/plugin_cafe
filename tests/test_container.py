"""Container 조립 스모크 — 결선이 실제로 이어지는지 (§4)."""

from __future__ import annotations

# pytest fixture 패턴 — fixture 이름을 인자로 받는 것은 정상이다
# pylint: disable=redefined-outer-name

import pytest

from pm.container import Container
from pm.errors import ConfigError
from pm.github.rest_client import RestGitHubClient


@pytest.fixture
def container(tmp_paths):
    return Container(paths=tmp_paths, env={})


def test_service_graph_constructs(container):
    assert container.org_service is not None
    assert container.catalog_service is not None
    assert container.install_service is not None
    assert container.activation_service is not None
    assert container.inspect_service is not None
    assert container.preset_service is not None
    assert container.auth is not None


def test_github_client_requires_host(container):
    with pytest.raises(ConfigError):
        container.github_client()  # host 미확정 (§10.2)


def test_github_client_with_candidate_host(container):
    client = container.github_client("github.xxx.xxx")
    assert isinstance(client, RestGitHubClient)


def test_github_client_uses_configured_host(container):
    container.config_store.write({"github_host": "github.xxx.xxx"})
    container.config.reload()
    assert isinstance(container.github_client(), RestGitHubClient)


def test_env_layer_reaches_config(tmp_paths):
    container = Container(paths=tmp_paths, env={"PM_PORT": "9999"})
    assert container.config.flask_port == 9999


def test_cli_overrides_win(tmp_paths):
    container = Container(paths=tmp_paths, env={"PM_PORT": "9999"},
                          cli_overrides={"flask_port": 7777})
    assert container.config.flask_port == 7777
