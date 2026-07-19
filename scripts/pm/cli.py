"""pm CLI (§7) — argparse 디스패치. 로직은 전부 services에 위임.

종료코드: 0 정상 / 1 실행 오류(PmError 등) / 2 사용법 오류(argparse).
플러그인 식별자: ``org/name`` — bare name은 유일할 때만 허용(§7).
CLI 출력의 상태명은 영문(내부 상태명)이다 — 한국어 라벨은 웹 UI 몫(§12.2).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

from pm.errors import PmError
from pm.models import Plugin, PluginState

_NEW_SESSION_NOTE = "변경은 새 claude 세션부터 적용됩니다 (§12.3)"


# ──────────────────────────────────────────────────────────────
# 파서
# ──────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    """§7 전 명령의 argparse 트리를 만든다."""
    parser = argparse.ArgumentParser(
        prog="pm", description="Claude plugin 관리 (docs/Architecture.md §7)")
    sub = parser.add_subparsers(dest="command", required=True)

    org = sub.add_parser("org", help="organization 등록 관리")
    org_sub = org.add_subparsers(dest="org_command", required=True)
    org_add = org_sub.add_parser("add", help="org 등록 (권한 게이트)")
    org_add.add_argument("url", help="org URL 또는 이름")
    org_list = org_sub.add_parser("list", help="등록 org 목록·권한 상태")
    org_list.add_argument("--json", action="store_true", dest="as_json")
    org_remove = org_sub.add_parser("remove",
        help="org 등록 해제 + 설치본 전부 삭제·preset 멤버 정리 (즉시)")
    org_remove.add_argument("org", help="org 이름")

    lst = sub.add_parser("list", help="카탈로그 스캔·조회")
    lst.add_argument("--org", help="지정 org만")
    lst.add_argument("--cached", action="store_true", help="스캔 없이 캐시만")
    lst.add_argument("--all", action="store_true", dest="show_all",
                     help="태그 필터 해제 (같은 캐시)")
    lst.add_argument("--json", action="store_true", dest="as_json")

    install = sub.add_parser("install", help="플러그인 설치")
    install.add_argument("identifier", nargs="?",
                         help="org/name — 생략 시 번호 선택")
    install.add_argument("--no-enable", action="store_true")

    for name, help_text in (("uninstall", "삭제 (확인 없이 즉시 — §7)"),
                            ("enable", "켜기"), ("disable", "끄기")):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument("identifier", help="org/name 또는 유일한 name")

    inspect = sub.add_parser("inspect", help="실측 상태 리포트")
    inspect.add_argument("identifier", nargs="?")
    inspect.add_argument("--env", action="store_true", dest="env_check",
                         help="환경 체크리스트 (§9.4)")
    inspect.add_argument("--bootstrap", action="store_true",
                         help="--env를 부트스트랩 게이트(§9.4 A)로 한정 "
                              "— launcher 전용")
    inspect.add_argument("--repair", action="store_true")
    inspect.add_argument("--json", action="store_true", dest="as_json")

    update = sub.add_parser("update", help="git pull + 재등록 (§6.2)")
    update.add_argument("identifier", nargs="?", help="생략 시 설치 전체")

    preset = sub.add_parser("preset", help="플러그인 묶음 (§6.5)")
    preset_sub = preset.add_subparsers(dest="preset_command", required=True)
    for name in ("create", "delete"):
        p = preset_sub.add_parser(name)
        p.add_argument("name")
    for name in ("add", "remove"):
        p = preset_sub.add_parser(name)
        p.add_argument("name")
        p.add_argument("member", help="org/name")
    preset_list = preset_sub.add_parser("list")
    preset_list.add_argument("--json", action="store_true", dest="as_json")
    for name in ("install", "enable", "disable", "uninstall", "apply"):
        p = preset_sub.add_parser(name)
        p.add_argument("name")

    serve = sub.add_parser("serve", help="Flask 서버 (launcher 내부용)")
    serve.add_argument("--port", type=int, default=None)

    return parser


# ──────────────────────────────────────────────────────────────
# 식별자 해석 (§7)
# ──────────────────────────────────────────────────────────────
def _resolve_installable(container: Any, identifier: str) -> Plugin:
    """설치용 해석 — 카탈로그에서 Plugin(clone_url 포함)을 찾는다."""
    matches = container.catalog_service.find(identifier)
    return _require_unique(identifier, [(p.org, p.name) for p in matches],
                           payload=matches)


def _resolve_ref(container: Any, identifier: str) -> Tuple[str, str]:
    """(org, name) 해석 — 카탈로그 ∪ 설치본 (org 미등록 고아 포함 §12.2)."""
    refs = {(p.org, p.name)
            for p in container.catalog_service.find(identifier)}
    for status in container.inspect_service.report():
        candidate = (status.org, status.name)
        if "/" in identifier:
            org, _, name = identifier.partition("/")
            if candidate == (org, name):
                refs.add(candidate)
        elif status.name == identifier:
            refs.add(candidate)
    return _require_unique(identifier, sorted(refs))


def _require_unique(identifier: str, refs: Sequence[Tuple[str, str]],
                    payload: Optional[List[Plugin]] = None):
    """후보가 정확히 1개일 때만 통과 — 아니면 PmError (종료코드 1)."""
    if not refs:
        raise PmError(
            f"'{identifier}' 를 찾을 수 없습니다 — pm list로 스캔했는지, "
            "철자가 맞는지 확인하세요")
    if len(refs) > 1:
        candidates = ", ".join(f"{org}/{name}" for org, name in refs)
        raise PmError(
            f"'{identifier}' 가 모호합니다 — 다음 중 선택: {candidates}")
    return payload[0] if payload is not None else refs[0]


# ──────────────────────────────────────────────────────────────
# 출력 도우미
# ──────────────────────────────────────────────────────────────
def _emit_json(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _plugin_rows(container: Any,
                 catalog: Dict[str, List[Plugin]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for org_name in sorted(catalog):
        for plugin in catalog[org_name]:
            state = container.activation_service.state(
                plugin.org, plugin.name)
            rows.append({
                "ref": plugin.ref,
                "state": state.value,
                "description": plugin.description,
                "has_tags": plugin.has_tags,
            })
    return rows


def _print_plugin_table(rows: List[Dict[str, Any]]) -> None:
    if not rows:
        print("(비어 있음 — pm org add 후 pm list로 스캔하세요)")
        return
    width = max(len(r["ref"]) for r in rows)
    for row in rows:
        print(f"{row['ref']:<{width}}  {row['state']:<9}  "
              f"{row['description']}")


def _print_member_results(results: List[Any]) -> int:
    """preset 일괄 결과 표 출력 — 일부 실패 시 1 (§6.5)."""
    ok = True
    for r in results:
        mark = "ok" if r.ok else "FAIL"
        detail = f" — {r.detail}" if r.detail else ""
        print(f"[{mark}] {r.ref}: {r.action}{detail}")
        ok = ok and r.ok
    print(_NEW_SESSION_NOTE)
    return 0 if ok else 1


# ──────────────────────────────────────────────────────────────
# 명령 구현
# ──────────────────────────────────────────────────────────────
def _cmd_org(container: Any, args: argparse.Namespace) -> int:
    if args.org_command == "add":
        org = container.org_service.add(args.url)
        catalog = container.catalog_service.scan(org.name)
        count = len(catalog.get(org.name, []))
        print(f"등록됨: {org.name} ({org.host}) — 플러그인 {count}개 발견")
        return 0
    if args.org_command == "list":
        orgs = container.org_service.list_orgs()
        status = container.org_service.revalidate_all()
        rows = [{
            "name": o.name,
            "url": o.url,
            "kind": o.kind.value,
            "authorized": bool(status.get(o.name, False)),
        } for o in orgs]
        if args.as_json:
            _emit_json(rows)
        elif not rows:
            print("(등록된 org 없음 — pm org add <url>)")
        else:
            for row in rows:
                mark = "ok" if row["authorized"] else "권한 없음"
                print(f"{row['name']:<20} {mark:<8} {row['url']}")
        return 0
    removed, pruned = container.org_service.remove(args.org)
    line = f"등록 해제됨: {args.org} — 설치된 플러그인 {removed}개 함께 삭제"
    if pruned:
        line += f", preset 멤버 {pruned}개 정리"
    print(line)
    return 0


def _cmd_list(container: Any, args: argparse.Namespace) -> int:
    if not args.cached:
        container.catalog_service.scan(args.org)
    catalog = container.catalog_service.cached(args.org,
                                               include_all=args.show_all)
    rows = _plugin_rows(container, catalog)
    if args.as_json:
        _emit_json(rows)
    else:
        _print_plugin_table(rows)
    return 0


def _pick_interactive(container: Any) -> Plugin:
    """번호 선택 설치 (§7 — install 무인자)."""
    catalog = container.catalog_service.cached()
    plugins = [p for org in sorted(catalog) for p in catalog[org]]
    if not plugins:
        raise PmError("카탈로그가 비어 있습니다 — pm list로 스캔하세요")
    for idx, plugin in enumerate(plugins, start=1):
        print(f"{idx:>3}) {plugin.ref:<40} {plugin.description}")
    choice = input("설치할 번호: ").strip()
    try:
        return plugins[int(choice) - 1]
    except (ValueError, IndexError) as exc:
        raise PmError(f"잘못된 선택: {choice!r}") from exc


def _cmd_install(container: Any, args: argparse.Namespace) -> int:
    if args.identifier:
        plugin = _resolve_installable(container, args.identifier)
    else:
        plugin = _pick_interactive(container)
    result = container.install_service.install(
        plugin, enable=not args.no_enable)
    state = "enabled" if result.enabled else "installed"
    print(f"{plugin.ref} → {state} (등록명: {result.entry_name})")
    for warning in result.warnings:
        print(f"경고: {warning}", file=sys.stderr)
    print(_NEW_SESSION_NOTE)
    return 0


def _cmd_plugin_action(container: Any, args: argparse.Namespace) -> int:
    org, name = _resolve_ref(container, args.identifier)
    if args.command == "uninstall":
        container.install_service.uninstall(org, name)
        print(f"{org}/{name} 삭제됨")
    elif args.command == "enable":
        container.activation_service.enable(org, name)
        print(f"{org}/{name} → enabled")
    else:
        container.activation_service.disable(org, name)
        print(f"{org}/{name} → installed (disabled)")
    print(_NEW_SESSION_NOTE)
    return 0


def _cmd_inspect(container: Any, args: argparse.Namespace) -> int:
    if args.env_check:
        from pm.envcheck.checker import BOOTSTRAP, EnvCheckRunner
        from pm.envcheck.checks import build_checks
        stage = BOOTSTRAP if args.bootstrap else None
        results = EnvCheckRunner(
            build_checks(container.paths, container.config)).run(stage)
        if args.as_json:
            _emit_json([r.__dict__ for r in results])
        else:
            for r in results:
                mark = "PASS" if r.passed else "FAIL"
                info = " (정보)" if r.informational else ""
                print(f"[{mark}]{info} {r.name}: {r.detail}")
                if not r.passed and r.fix_command:
                    print(f"       → {r.fix_command}")
        return 0 if EnvCheckRunner.all_passed(results) else 1
    if args.repair:
        actions = container.inspect_service.repair()
        for action in actions:
            print(action)
        print(f"교정 {len(actions)}건")
        return 0
    report = container.inspect_service.report()
    if args.identifier:
        org, name = _resolve_ref(container, args.identifier)
        report = [s for s in report if (s.org, s.name) == (org, name)]
    if args.as_json:
        _emit_json([{
            "ref": f"{s.org}/{s.name}",
            "state": s.state.value,
            "entry_name": s.entry_name,
            "issues": list(s.issues),
        } for s in report])
    else:
        for s in report:
            issues = f"  [{'; '.join(s.issues)}]" if s.issues else ""
            print(f"{s.org}/{s.name:<30} {s.state.value}{issues}")
    return 0


def _cmd_update(container: Any, args: argparse.Namespace) -> int:
    if args.identifier:
        targets = [_resolve_ref(container, args.identifier)]
    else:
        targets = [(s.org, s.name)
                   for s in container.inspect_service.report()
                   if s.state is not PluginState.AVAILABLE]
        if not targets:
            print("설치된 플러그인이 없습니다")
            return 0
    for org, name in targets:
        head = container.install_service.update(org, name)
        print(f"{org}/{name} → {head}")
    print(_NEW_SESSION_NOTE)
    return 0


def _cmd_preset(container: Any, args: argparse.Namespace) -> int:
    service = container.preset_service
    cmd = args.preset_command
    if cmd == "create":
        service.create(args.name)
        print(f"preset 생성됨: {args.name}")
        return 0
    if cmd == "delete":
        service.delete(args.name)
        print(f"preset 정의 삭제됨: {args.name} (플러그인은 무영향 §6.5)")
        return 0
    if cmd == "add":
        preset = service.add_member(args.name, args.member)
        print(f"{args.name} ← {args.member} (멤버 {len(preset.members)}개)")
        return 0
    if cmd == "remove":
        preset = service.remove_member(args.name, args.member)
        print(f"{args.name} → {args.member} 제거 "
              f"(멤버 {len(preset.members)}개)")
        return 0
    if cmd == "list":
        rows = [{
            "name": p.name,
            "members": list(p.members),
            "badge": service.badge(p.name).value,
        } for p in service.list_presets()]
        if args.as_json:
            _emit_json(rows)
        elif not rows:
            print("(preset 없음 — pm preset create <name>)")
        else:
            for row in rows:
                print(f"{row['name']:<24} {row['badge']:<8} "
                      f"{len(row['members'])}개 멤버")
        return 0
    results = getattr(service, cmd)(args.name)
    return _print_member_results(results)


def _cmd_serve(container: Any, args: argparse.Namespace) -> int:
    try:
        from pm.api.app import serve  # M5에서 구현 (§5)
    except ImportError:
        print("serve는 M5(Flask API)에서 제공됩니다 — 아직 미구현",
              file=sys.stderr)
        return 1
    serve(container, port=args.port)
    return 0


_DISPATCH = {
    "org": _cmd_org,
    "list": _cmd_list,
    "install": _cmd_install,
    "uninstall": _cmd_plugin_action,
    "enable": _cmd_plugin_action,
    "disable": _cmd_plugin_action,
    "inspect": _cmd_inspect,
    "update": _cmd_update,
    "preset": _cmd_preset,
    "serve": _cmd_serve,
}


def main(argv: Optional[Sequence[str]] = None,
         container: Any = None) -> int:
    """CLI 진입점.

    Args:
        argv: 인자 목록 — None이면 sys.argv[1:].
        container: 테스트 주입용 — None이면 Container() 조립(§2.2).
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse 사용법 오류 = 2 (§7)
        return int(exc.code or 0)
    if container is None:
        overrides: Dict[str, Any] = {}
        if getattr(args, "port", None) is not None:
            overrides["flask_port"] = args.port
        from pm.container import Container
        container = Container(cli_overrides=overrides or None)
    try:
        return _DISPATCH[args.command](container, args)
    except PmError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
