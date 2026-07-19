"""pm.errors 계층 테스트."""

from __future__ import annotations

import pytest

from pm import errors

_SUBCLASSES = [
    errors.ConfigError,
    errors.GitHubError,
    errors.GitOpsError,
    errors.RegistryError,
    errors.AuthError,
]


@pytest.mark.parametrize("exc_type", _SUBCLASSES)
def test_subclass_is_pm_error(exc_type):
    assert issubclass(exc_type, errors.PmError)
    assert isinstance(exc_type("x"), errors.PmError)


def test_siblings_are_unrelated():
    assert not isinstance(errors.GitHubError("x"), errors.AuthError)
    assert not isinstance(errors.ConfigError("x"), errors.GitOpsError)


def test_raise_from_preserves_cause():
    original = ValueError("root cause")
    with pytest.raises(errors.GitHubError) as exc_info:
        try:
            raise original
        except ValueError as e:
            raise errors.GitHubError("api failed") from e
    assert exc_info.value.__cause__ is original
