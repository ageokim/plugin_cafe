"""pm.store.json_store 테스트 — 전부 tmp_path, 실 FS 오염 없음."""

from __future__ import annotations

import json
import os
import stat

import pytest

import pm.store.json_store as json_store_module
from pm.store.json_store import JsonStore


def _store(tmp_path, **kwargs):
    return JsonStore(tmp_path / "data" / "sample.json",
                     default=dict,
                     **kwargs)


def test_roundtrip_korean_nested(tmp_path):
    store = _store(tmp_path)
    data = {"presets": [{"name": "코드리뷰", "members": ["org-a/플러그인"]}]}
    store.write(data)
    assert store.read() == data
    raw = store.path.read_text(encoding="utf-8")
    assert "코드리뷰" in raw  # ensure_ascii=False


def test_missing_file_returns_default_factory(tmp_path):
    store = JsonStore(tmp_path / "none.json", default=lambda: {"orgs": []})
    first = store.read()
    second = store.read()
    assert first == {"orgs": []}
    assert first is not second  # 호출마다 새 객체


def test_exists(tmp_path):
    store = _store(tmp_path)
    assert not store.exists()
    store.write({})
    assert store.exists()


@pytest.mark.parametrize("corrupt", ["{oops", ""])
def test_corrupt_file_returns_default_and_warns(tmp_path, caplog, corrupt):
    store = _store(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(corrupt, encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert store.read() == {}
    assert str(store.path) in caplog.text
    # 손상 파일은 지우지 않는다 — 다음 write가 교체
    assert store.path.read_text(encoding="utf-8") == corrupt


def test_atomic_write_failure_preserves_original(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.write({"ok": 1})

    def _boom(*_args, **_kwargs):
        raise RuntimeError("mid-write failure")

    monkeypatch.setattr(json_store_module.json, "dump", _boom)
    with pytest.raises(RuntimeError):
        store.write({"ok": 2})
    monkeypatch.undo()

    assert store.read() == {"ok": 1}
    assert not list(store.path.parent.glob("*.tmp"))


def test_no_tmp_leftover_after_normal_write(tmp_path):
    store = _store(tmp_path)
    store.write({"a": 1})
    store.write({"a": 2})  # 덮어쓰기 (os.replace 경로)
    assert store.read() == {"a": 2}
    assert not list(store.path.parent.glob("*.tmp"))


def test_parent_dir_auto_created(tmp_path):
    store = JsonStore(tmp_path / "data" / "deep" / "config.json",
                      default=dict)
    store.write({"x": 1})
    assert store.read() == {"x": 1}


@pytest.mark.skipif(os.name != "posix", reason="POSIX 권한 모델 한정")
def test_secure_file_is_0600(tmp_path):
    store = JsonStore(tmp_path / "data" / "credentials.json",
                      default=dict,
                      secure=True)
    store.write({"id": "ageokim", "token": "ghp_x"})
    mode = stat.S_IMODE(store.path.stat().st_mode)
    assert mode == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX 권한 모델 한정")
def test_non_secure_write_still_works_after_replace(tmp_path):
    store = _store(tmp_path)
    store.write({"a": 1})
    assert stat.S_IMODE(store.path.stat().st_mode) in (0o600, 0o644, 0o664)


def test_update(tmp_path):
    store = JsonStore(tmp_path / "orgs.json", default=lambda: {"orgs": []})

    def _add(data):
        data["orgs"].append({"name": "org-a"})
        return data

    result = store.update(_add)
    assert result == {"orgs": [{"name": "org-a"}]}
    assert store.read() == result


def test_written_file_is_valid_json_with_trailing_newline(tmp_path):
    store = _store(tmp_path)
    store.write({"k": "v"})
    raw = store.path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert json.loads(raw) == {"k": "v"}
