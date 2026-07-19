"""preset API (§6.5·§5) — CRUD·멤버 편집·일괄 액션."""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify, request

_NEW_SESSION_NOTE = "새 claude 세션부터 적용됩니다 (§12.3)"
_BATCH_ACTIONS = ("install", "enable", "disable", "uninstall", "apply")


def make_presets_bp(preset_service: Any) -> Blueprint:
    bp = Blueprint("presets", __name__)

    def _preset_dict(preset: Any) -> dict:
        return {
            "name": preset.name,
            "members": list(preset.members),
            "badge": preset_service.badge(preset.name).value,
        }

    @bp.get("/presets")
    def list_presets():
        return jsonify(
            [_preset_dict(p) for p in preset_service.list_presets()])

    @bp.post("/presets")
    def create_preset():
        body = request.get_json(silent=True) or {}
        name = str(body.get("name", "")).strip()
        if not name:
            return jsonify({"error": "name이 필요합니다"}), 400
        return jsonify(_preset_dict(preset_service.create(name))), 201

    @bp.delete("/presets/<name>")
    def delete_preset(name: str):
        preset_service.delete(name)  # 정의만 삭제 — 플러그인 무영향 (§6.5)
        return jsonify({"ok": True})

    @bp.post("/presets/<name>/members")
    def edit_members(name: str):
        body = request.get_json(silent=True) or {}
        ref = str(body.get("ref", "")).strip()
        op = body.get("op", "add")
        if not ref or op not in ("add", "remove"):
            return jsonify(
                {"error": "ref와 op(add|remove)가 필요합니다"}), 400
        if op == "add":
            preset = preset_service.add_member(name, ref)
        else:
            preset = preset_service.remove_member(name, ref)
        return jsonify(_preset_dict(preset))

    @bp.post("/presets/<name>/<action>")
    def batch(name: str, action: str):
        if action not in _BATCH_ACTIONS:
            return jsonify({"error": f"지원하지 않는 액션: {action}"}), 400
        results = getattr(preset_service, action)(name)
        return jsonify({
            "ok": all(r.ok for r in results),  # 일부 실패 감지 (§6.5)
            "results": [{
                "ref": r.ref,
                "action": r.action,
                "ok": r.ok,
                "detail": r.detail,
            } for r in results],
            "note": _NEW_SESSION_NOTE,
        })

    return bp
