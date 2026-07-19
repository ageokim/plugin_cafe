"""cli.py 계약 테스트 — 인자 파싱·종료코드·식별자 규칙 (§7, M4)."""

from __future__ import annotations

import json

from pm.cli import main
from pm.models import Plugin, PluginState
from pm.services.inspect_service import PluginStatus
from pm.services.preset_service import MemberResult


def make_plugin(org: str, name: str, has_tags: bool = True) -> Plugin:
    return Plugin(name=name, org=org,
                  github_addr=f"https://ghes/{org}/{name}",
                  clone_url=f"https://ghes/{org}/{name}.git",
                  description="", private=False, has_tags=has_tags)


def test_usage_error_exits_2(container):
    assert main(["없는명령"], container=container) == 2
    assert main([], container=container) == 2
    assert main(["org"], container=container) == 2


def test_enable_unique_bare_name(container, capsys):
    container.catalog_service.plugins = [make_plugin("org-a", "plugin-a")]
    assert main(["enable", "plugin-a"], container=container) == 0
    assert ("enable", "org-a", "plugin-a") in \
        container.activation_service.calls
    assert "새 claude 세션부터" in capsys.readouterr().out


def test_ambiguous_bare_name_lists_candidates(container, capsys):
    container.catalog_service.plugins = [
        make_plugin("org-a", "plugin-a"),
        make_plugin("org-b", "plugin-a"),
    ]
    assert main(["enable", "plugin-a"], container=container) == 1
    err = capsys.readouterr().err
    assert "org-a/plugin-a" in err and "org-b/plugin-a" in err


def test_unknown_identifier_exits_1(container, capsys):
    assert main(["enable", "ghost"], container=container) == 1
    assert "찾을 수 없습니다" in capsys.readouterr().err


def test_org_qualified_name_disambiguates(container):
    container.catalog_service.plugins = [
        make_plugin("org-a", "plugin-a"),
        make_plugin("org-b", "plugin-a"),
    ]
    assert main(["disable", "org-b/plugin-a"], container=container) == 0
    assert ("disable", "org-b", "plugin-a") in \
        container.activation_service.calls


def test_uninstall_resolves_orphan_from_inspect(container):
    """카탈로그에 없는 설치본(org 미등록 §12.2)도 삭제 가능해야 한다."""
    container.inspect_service.statuses = [
        PluginStatus(org="gone-org", name="plugin-z", entry_name="plugin-z",
                     state=PluginState.INSTALLED),
    ]
    assert main(["uninstall", "plugin-z"], container=container) == 0
    assert ("uninstall", "gone-org", "plugin-z") in \
        container.install_service.calls


def test_list_json_and_tag_filter(container, capsys):
    container.catalog_service.plugins = [
        make_plugin("org-a", "tagged", has_tags=True),
        make_plugin("org-a", "untagged", has_tags=False),
    ]
    assert main(["list", "--cached", "--json"], container=container) == 0
    rows = json.loads(capsys.readouterr().out)
    assert [r["ref"] for r in rows] == ["org-a/tagged"]

    assert main(["list", "--cached", "--all", "--json"],
                container=container) == 0
    rows = json.loads(capsys.readouterr().out)
    assert {r["ref"] for r in rows} == {"org-a/tagged", "org-a/untagged"}


def test_list_scans_unless_cached(container):
    main(["list"], container=container)
    assert container.catalog_service.scanned == [None]
    main(["list", "--cached"], container=container)
    assert container.catalog_service.scanned == [None]  # 추가 스캔 없음


def test_install_flags(container, capsys):
    container.catalog_service.plugins = [make_plugin("org-a", "plugin-a")]
    assert main(["install", "org-a/plugin-a"], container=container) == 0
    assert ("install", "org-a/plugin-a", "True") in \
        container.install_service.calls
    assert main(["install", "org-a/plugin-a", "--no-enable"],
                container=container) == 0
    assert ("install", "org-a/plugin-a", "False") in \
        container.install_service.calls


def test_org_add_registers_and_scans(container, capsys):
    assert main(["org", "add", "https://ghes/org-c"],
                container=container) == 0
    assert container.catalog_service.scanned == ["org-c"]
    assert "등록됨: org-c" in capsys.readouterr().out


def test_org_list_json(container, capsys):
    container.org_service.add("https://ghes/org-a")
    assert main(["org", "list", "--json"], container=container) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["name"] == "org-a" and rows[0]["authorized"] is True


def test_preset_batch_partial_failure_exits_1(container, capsys):
    container.preset_service.batch_results = [
        MemberResult(ref="org-a/plugin-a", action="enabled", ok=True),
        MemberResult(ref="org-b/plugin-x", action="failed", ok=False,
                     detail="clone 실패"),
    ]
    assert main(["preset", "enable", "세트"], container=container) == 1
    out = capsys.readouterr().out
    assert "[FAIL] org-b/plugin-x" in out and "[ok] org-a/plugin-a" in out


def test_preset_batch_all_ok_exits_0(container):
    container.preset_service.batch_results = [
        MemberResult(ref="org-a/plugin-a", action="enabled", ok=True),
    ]
    assert main(["preset", "apply", "세트"], container=container) == 0


def test_preset_crud_and_list(container, capsys):
    assert main(["preset", "create", "세트"], container=container) == 0
    assert main(["preset", "add", "세트", "org-a/plugin-a"],
                container=container) == 0
    capsys.readouterr()  # create·add 출력 비움 — 아래는 JSON만 캡처
    assert main(["preset", "list", "--json"], container=container) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[-1]["members"] == ["org-a/plugin-a"]


def test_inspect_json_and_repair(container, capsys):
    container.inspect_service.statuses = [
        PluginStatus(org="org-a", name="plugin-a", entry_name="plugin-a",
                     state=PluginState.ENABLED),
    ]
    assert main(["inspect", "--json"], container=container) == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["state"] == "enabled"
    assert main(["inspect", "--repair"], container=container) == 0
    assert "repaired" in capsys.readouterr().out


def test_update_without_arg_updates_all_installed(container, capsys):
    container.inspect_service.statuses = [
        PluginStatus(org="org-a", name="a", entry_name="a",
                     state=PluginState.ENABLED),
        PluginStatus(org="org-a", name="b", entry_name="b",
                     state=PluginState.INSTALLED),
    ]
    assert main(["update"], container=container) == 0
    calls = container.install_service.calls
    assert ("update", "org-a", "a") in calls
    assert ("update", "org-a", "b") in calls


def test_inspect_env_bootstrap_gate(container, capsys):
    """--bootstrap은 §9.4 A(6항목)만 돌리고 통과 여부를 종료코드로 낸다."""
    import json as _json
    import sys as _sys
    container.paths.env_file.parent.mkdir(parents=True, exist_ok=True)
    container.paths.env_file.write_text(
        _json.dumps({"python": _sys.executable}), encoding="utf-8")
    code = main(["inspect", "--env", "--bootstrap"], container=container)
    out = capsys.readouterr().out
    assert code == 0
    assert out.count("[PASS]") + out.count("[FAIL]") == 6  # A단계만
    assert "git" not in out  # B(웹) 항목은 제외
