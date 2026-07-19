#!/usr/bin/env sh
# 멱등 셋업 (Linux/macOS — Architecture.md §9.0~9.3)
# 모든 단계: "이미 충족됐는지 검사 → 충족 시 아무것도 안 함".
# venv를 만들지 않는다 — 검증은 체크리스트(§9.4)가 담당.
set -u
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd -P)"
ENV_JSON="$ROOT/data/env.json"

say() { printf '%s\n' "$*"; }

# ── ① 인터프리터 고정 (§9.1) ──────────────────────────────
pinned_python() {
    [ -f "$ENV_JSON" ] || return 1
    PY="$(sed -n 's/.*"python"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
        "$ENV_JSON")"
    [ -n "$PY" ] && [ -x "$PY" ] && "$PY" -c \
        'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
        2>/dev/null
}

if pinned_python; then
    say "[skip] 인터프리터 이미 고정: $PY"
else
    PY=""
    for cand in python3 python; do
        FOUND="$(command -v "$cand" 2>/dev/null)" || continue
        if "$FOUND" -c \
            'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' \
            2>/dev/null; then
            PY="$("$FOUND" -c 'import sys; print(sys.executable)')"
            break
        fi
    done
    if [ -z "$PY" ]; then
        say "[fail] python ≥ 3.8 을 찾지 못했습니다 — sudo apt install python3"
        exit 1
    fi
    mkdir -p "$ROOT/data"
    printf '{ "python": "%s" }\n' "$PY" > "$ENV_JSON"
    say "[ok]   인터프리터 고정: $PY → data/env.json"
fi

# ── ② 의존성 — 빠른 경로: import 성공 시 pip 자체를 생략 (§9.0·9.2) ──
if "$PY" - <<'PYEOF' 2>/dev/null
import sys
import flask, flask_sock, requests  # noqa
if sys.version_info >= (3, 10):
    import claude_agent_sdk  # noqa
PYEOF
then
    say "[skip] 필수 패키지 이미 충족 — pip 실행 안 함"
else
    say "[..]   pip install --user -r env/requirements.txt"
    if ! "$PY" -m pip install --user -r "$ROOT/env/requirements.txt"; then
        # PEP 668 (Debian 12+/Ubuntu 23.04+) 재시도 — --user 결합이라
        # 시스템 site-packages는 건드리지 않는다 (§9.2)
        say "[..]   PEP 668 감지 가능성 — --break-system-packages 재시도"
        "$PY" -m pip install --user --break-system-packages \
            -r "$ROOT/env/requirements.txt" || {
            say "[fail] 패키지 설치 실패"; exit 1; }
    fi
fi

# ── ③ pm PATH 등록 — ~/.local/bin 심볼릭 링크 (§9.3) ────────
BIN_LINK="$HOME/.local/bin/pm"
SHIM="$ROOT/scripts/bin/pm"
if [ "$(readlink "$BIN_LINK" 2>/dev/null)" = "$SHIM" ]; then
    say "[skip] pm PATH 이미 등록: $BIN_LINK"
else
    mkdir -p "$HOME/.local/bin"
    ln -sf "$SHIM" "$BIN_LINK"
    say "[ok]   pm 등록: $BIN_LINK → $SHIM (새 터미널부터 반영)"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) say "[주의] ~/.local/bin 이 PATH에 없습니다 — 셸 프로필에 추가하세요" ;;
    esac
fi

say "셋업 완료 (멱등 — 재실행 안전)"
