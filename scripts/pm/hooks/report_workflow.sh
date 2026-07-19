#!/bin/sh
# Workflow 관찰 리포터 (Architecture §12.7) — stdin의 hook JSON을 pm serve로
# 전달만 한다. 서버 부재·오류는 조용히 무시하고 **항상 0으로 종료**해
# claude 세션 진행을 절대 막지 않는다. 포트는 §2.3 규약대로 도출.
ROOT="${CLAUDE_PROJECT_DIR:-.}"
PORT="${PM_PORT:-$(sed -n 's/.*"flask_port"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p' \
    "$ROOT/data/config.json" 2>/dev/null)}"
PORT="${PORT:-8765}"
curl -s -o /dev/null --connect-timeout 1 --max-time 2 \
    -X POST -H "Content-Type: application/json" --data-binary @- \
    "http://127.0.0.1:$PORT/api/workflow/events" 2>/dev/null
exit 0
