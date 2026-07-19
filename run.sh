#!/usr/bin/env sh
# launcher (Linux/macOS — Architecture.md §9·§12.5)
# ① 멱등 셋업 → ② 부트스트랩 게이트(§9.4 A) → ③ pm serve 백그라운드
# → ④ 브라우저 오픈. 종료는 브라우저 창 닫기 — 서버가 스스로 감지한다.
set -u
ROOT="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"

# ── ① 셋업 (이미 충족된 단계는 전부 건너뜀 §9.0) ──────────
sh "$ROOT/env/setup_linux.sh" || exit 1

PYTHON="$(sed -n 's/.*"python"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    "$ROOT/data/env.json")"
[ -x "$PYTHON" ] || { echo "인터프리터 고정 실패 — env/setup_linux.sh 확인"; exit 1; }
PYTHONPATH="$ROOT/scripts${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

# ── ② 부트스트랩 게이트 — 실패 항목·수정 명령을 터미널에 출력 ──
if ! "$PYTHON" -m pm inspect --env --bootstrap; then
    echo ""
    echo "위 [FAIL] 항목을 조치한 뒤 ./run.sh 를 다시 실행하세요 (§9.4 A)"
    exit 1
fi

# ── ③ Flask 백그라운드 (127.0.0.1 전용 §11) ────────────────
PORT="${PM_PORT:-$(sed -n 's/.*"flask_port"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' \
    "$ROOT/data/config.json" 2>/dev/null)}"
PORT="${PORT:-8765}"
URL="http://localhost:$PORT"
"$PYTHON" -m pm serve --port "$PORT" &

# 기동 대기 (최대 ~10초)
i=0
while [ $i -lt 50 ]; do
    if curl -fsS "$URL/api/session" >/dev/null 2>&1; then break; fi
    i=$((i + 1)); sleep 0.2
done

# ── ④ 브라우저 오픈 — 이후 수명은 서버 watchdog 몫 (§12.5) ──
case "$(uname)" in
    Darwin) open "$URL" ;;
    *) xdg-open "$URL" 2>/dev/null || echo "브라우저에서 열기: $URL" ;;
esac
echo "실행 중: $URL — 끝낼 때는 브라우저 창을 닫으면 서버도 자동 종료됩니다"
