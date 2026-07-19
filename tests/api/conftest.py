"""API 계약 테스트 픽스처 — app.test_client() + fake services (§13.3)."""

from __future__ import annotations

import pytest

from fakes import FakeChatBackend, FakeTerminalManager


@pytest.fixture
def chat_backend():
    return FakeChatBackend()


@pytest.fixture
def app(container, chat_backend):
    from pm.api.app import create_app
    return create_app(container, chat_backend=chat_backend,
                      terminal_manager=FakeTerminalManager())


@pytest.fixture
def client(app):
    return app.test_client()
