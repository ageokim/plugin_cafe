# Plugin Cafe (repo: plugin_cafe)

Claude Code plugin을 여러 GitHub organization에서 검색·설치·활성화·관리하는 시스템.

## 규칙

- 설계 기준 문서: **docs/Architecture.md** — 구현 전 반드시 해당 섹션을 확인할 것
- 코드 규정: Google Python Style Guide, SOLID (조립은 `scripts/pm/container.py`에서만)
- **가상환경(venv) 금지** — 실행은 항상 `python -m`, 의존성은 `pip install --user` (§9)
- 변경 가능한 값(GitHub host 등)은 하드코딩 금지 — config 주입 (§2.3)
- 상태는 저장하지 않고 파일시스템에서 실측 도출 (§6.4)
- 토큰은 `data/credentials.json`(권한 600, 비추적) 외 어디에도 쓰지 않는다 (§11)
- 프론트(web/)는 빌드 도구 없는 바닐라 HTML/CSS/JS — 로직은 전부 services에 (§13.2)

## 구조

- `scripts/pm/` — core 패키지 (CLI·Flask API가 공유). 레이어: Presentation → services → domain → infrastructure
- `scripts/pm/api/` — Flask (REST + SSE 챗 + WS 터미널), 127.0.0.1 전용, heartbeat로 수명 관리
- `web/` — 정적 프론트 (사이드바=플러그인, 메인=claude 챗+내장 터미널)
- `plugins/{org}/{name}` — 설치 clone / `.claude-plugin/marketplace.json` — pm이 생성·관리
