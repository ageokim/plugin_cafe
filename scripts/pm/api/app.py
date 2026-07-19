"""Flask app factory + serve (§5·§11·§12.5).

- **127.0.0.1 바인딩 강제** — 외부 인터페이스 옵션 자체를 두지 않는다(§11).
- 오류 매핑: AuthError→401(로그인 창 복귀), GitHubError→502,
  그 외 PmError→400(인라인 표시) — §10.2 실패 라우팅의 HTTP 구현.
- 수명: watchdog이 유일한 종료 판정자(§12.5) — 종료 시 pty·챗 정리.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from flask import Flask, jsonify

from pm.api.auth import make_auth_bp
from pm.api.chat import build_chat_backend, make_chat_bp
from pm.api.lifecycle import LifecycleManager, Watchdog, make_lifecycle_bp
from pm.api.orgs import make_orgs_bp
from pm.api.plugins import make_plugins_bp
from pm.api.presets import make_presets_bp
from pm.api.terminal import TokenStore, make_terminal_bp, \
    register_terminal_ws
from pm.api.workflow import WorkflowStore, make_workflow_bp
from pm.errors import AuthError, GitHubError, PmError

_HOST = "127.0.0.1"  # §11 — 변경 옵션 없음 (의도된 하드코딩)


def create_app(
    container: Any,
    lifecycle: Optional[LifecycleManager] = None,
    chat_backend: Any = None,
    terminal_manager: Any = None,
    token_store: Optional[TokenStore] = None,
    workflow_store: Optional[WorkflowStore] = None,
) -> Flask:
    """blueprint 조립 — 각 bp는 필요한 서비스만 받는다(ISP §2.2).

    Args:
        container: services 조립체 (pm.container.Container 또는 fake).
        lifecycle/chat_backend/terminal_manager/token_store:
            테스트 주입 seam — None이면 실물 생성.
    """
    web_dir = container.paths.root / "web"
    app = Flask("pm.api", static_folder=str(web_dir), static_url_path="")

    @app.errorhandler(PmError)
    def handle_pm_error(exc: PmError):
        status = 400
        if isinstance(exc, AuthError):
            status = 401  # 토큰 무효 → 로그인 창 복귀 (§10.2)
        elif isinstance(exc, GitHubError):
            status = 502
        return jsonify({"error": str(exc),
                        "kind": type(exc).__name__}), status

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    lifecycle = lifecycle if lifecycle is not None else LifecycleManager()
    token_store = token_store if token_store is not None else TokenStore()
    workflow_store = workflow_store if workflow_store is not None \
        else WorkflowStore()
    if chat_backend is None:
        from pm.system.claudebin import ensure_claude_on_path
        claude_bin = ensure_claude_on_path(container.config)  # §12.3 해석기
        chat_backend = build_chat_backend(str(container.paths.root),
                                          claude_bin=claude_bin)
    if terminal_manager is None:
        from pm.system.terminal import TerminalManager
        terminal_manager = TerminalManager(container.paths)

    prefix = {"url_prefix": "/api"}
    app.register_blueprint(
        make_auth_bp(container.auth, container.config), **prefix)
    app.register_blueprint(
        make_orgs_bp(container.org_service, container.catalog_service),
        **prefix)
    app.register_blueprint(
        make_plugins_bp(container.catalog_service,
                        container.activation_service,
                        container.install_service,
                        container.inspect_service), **prefix)
    app.register_blueprint(make_presets_bp(container.preset_service),
                           **prefix)
    app.register_blueprint(make_chat_bp(container, chat_backend), **prefix)
    app.register_blueprint(
        make_terminal_bp(container.auth, token_store), **prefix)
    app.register_blueprint(make_lifecycle_bp(lifecycle), **prefix)
    app.register_blueprint(make_workflow_bp(workflow_store), **prefix)

    try:
        from flask_sock import Sock
        sock = Sock(app)
        register_terminal_ws(sock, terminal_manager, token_store)
    except ImportError:
        # flask-sock 부재 시 REST는 동작하되 터미널 WS만 비활성 —
        # 체크리스트 항목 5가 감지·안내한다(§9.4)
        pass

    app.extensions["pm"] = {
        "lifecycle": lifecycle,
        "terminal_manager": terminal_manager,
        "token_store": token_store,
        "workflow_store": workflow_store,
    }
    return app


def _skip_loopback_reverse_dns() -> None:
    """werkzeug가 bind 시 getfqdn을 호출하는데, 일부 macOS/DNS 환경에서
    루프백 역방향 조회가 ~35초 스톨한다(실측). 루프백은 조회가 무의미하므로
    즉답으로 대체한다 — 서버 프로세스 전용 패치."""
    import socket
    real_getfqdn = socket.getfqdn

    def patched(name: str = "") -> str:
        if name in ("", "127.0.0.1", "::1", "localhost"):
            return "localhost"
        return real_getfqdn(name)

    socket.getfqdn = patched


def serve(container: Any, port: Optional[int] = None) -> None:
    """`pm serve` 진입점 (§12.5) — launcher가 백그라운드로 띄운다."""
    _skip_loopback_reverse_dns()
    lifecycle = LifecycleManager()
    app = create_app(container, lifecycle=lifecycle)
    terminal_manager = app.extensions["pm"]["terminal_manager"]

    def _shutdown() -> None:
        # §12.5 종료 시 정리: pty → (챗 세션은 요청 단위라 정리 불요) → exit
        try:
            terminal_manager.close_all()
        finally:
            os._exit(0)  # pylint: disable=protected-access

    Watchdog(lifecycle, _shutdown).start()
    resolved_port = port if port is not None else container.config.flask_port
    # 이전 Plugin Cafe 서버가 포트를 물고 남았으면 종료 후 인계 —
    # 무관한 프로세스면 손대지 않고 기존 안내로 실패 (§12.5)
    from pm.errors import ConfigError
    from pm.system.takeover import takeover_port
    if not takeover_port(resolved_port):
        raise ConfigError(  # cli.py의 PmError 경로로 종료코드 1 (§13.1)
            f"포트 {resolved_port}가 다른 프로세스에 점유되어 있습니다 — "
            "점유 프로세스 종료 또는 config.json의 flask_port 변경 (§12.5)")
    app.run(host=_HOST, port=resolved_port, threaded=True)
