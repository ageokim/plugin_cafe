"""플러그인 API (§5) — 카탈로그·액션·inspect. 상태명은 내부 영문
(사용중/꺼짐/미설치 라벨 변환은 프론트 몫 §12.2)."""

from __future__ import annotations

from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

_NEW_SESSION_NOTE = "새 claude 세션부터 적용됩니다 (§12.3)"
_ACTIONS = ("install", "uninstall", "enable", "disable", "update")


def make_plugins_bp(catalog_service: Any, activation_service: Any,
                    install_service: Any, inspect_service: Any) -> Blueprint:
    bp = Blueprint("plugins", __name__)

    def _rows(catalog: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
        rows = []
        for org_name in sorted(catalog):
            for plugin in catalog[org_name]:
                state = activation_service.state(plugin.org, plugin.name)
                rows.append({
                    "ref": plugin.ref,
                    "org": plugin.org,
                    "name": plugin.name,
                    "state": state.value,
                    "description": plugin.description,
                    "has_tags": plugin.has_tags,
                })
        return rows

    @bp.get("/plugins")
    def list_plugins():
        org = request.args.get("org") or None
        cached = request.args.get("cached") == "1"
        include_all = request.args.get("all") == "1"
        if not cached:
            catalog_service.scan(org)
        return jsonify(
            _rows(catalog_service.cached(org, include_all=include_all)))

    @bp.post("/plugins/<org>/<name>/<action>")
    def plugin_action(org: str, name: str, action: str):
        if action not in _ACTIONS:
            return jsonify({"error": f"지원하지 않는 액션: {action}"}), 400
        if action == "install":
            matches = [p for p in catalog_service.find(f"{org}/{name}")]
            if not matches:
                return jsonify(
                    {"error": f"카탈로그에 없음: {org}/{name}"}), 404
            body = request.get_json(silent=True) or {}
            result = install_service.install(
                matches[0], enable=bool(body.get("enable", True)))
            return jsonify({
                "entry_name": result.entry_name,
                "enabled": result.enabled,
                "warnings": list(result.warnings),
                "note": _NEW_SESSION_NOTE,
            })
        if action == "uninstall":
            install_service.uninstall(org, name)
        elif action == "enable":
            activation_service.enable(org, name)
        elif action == "disable":
            activation_service.disable(org, name)
        else:  # update — 활성 상태 보존 (§6.2)
            head = install_service.update(org, name)
            return jsonify({"head": head, "note": _NEW_SESSION_NOTE})
        return jsonify({"ok": True, "note": _NEW_SESSION_NOTE})

    @bp.get("/inspect")
    def inspect():
        return jsonify([{
            "ref": f"{s.org}/{s.name}",
            "org": s.org,
            "name": s.name,
            "state": s.state.value,
            "entry_name": s.entry_name,
            "issues": list(s.issues),
        } for s in inspect_service.report()])

    @bp.post("/inspect/repair")
    def repair():
        return jsonify({"actions": inspect_service.repair()})

    return bp
