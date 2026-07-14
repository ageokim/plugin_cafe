# plugin_market

Claude Code에서 사용할 plugin을 여러 GitHub organization에서 검색·설치·활성화·관리하는 도구.

> **현재 상태: 설계 완료, 뼈대(폴더 트리) 구성 단계.**
> 전체 설계는 [docs/Architecture.md](docs/Architecture.md), 사용자 흐름은 [docs/Scenario.md](docs/Scenario.md),
> 화면 목업은 [docs/mockup/](docs/mockup/) 참고.

## 구조

```
plugin_market/
├─ run.sh / run.cmd     # launcher: 셋업 → Flask 서버 + 브라우저 동시 기동 (§9·§12.5)
│                       #   브라우저 창을 닫으면 서버도 자동 종료
├─ env/                 # OS별 셋업 스크립트 + requirements
├─ scripts/
│  ├─ bin/              #   pm shim (PATH 등록 대상)
│  └─ pm/               #   core 파이썬 패키지 (§5)
│      ├─ github/  store/  claudeplug/  services/  envcheck/  system/  api/
├─ web/                 # 정적 프론트 (HTML/CSS/JS + xterm.js) — Flask가 서빙
├─ plugins/             # 설치된 plugin clone — plugins/{org}/{name} (git 비추적)
├─ .claude/             # local claude 설정
├─ .claude-plugin/      # marketplace.json — pm이 생성·관리 (git 비추적)
├─ data/                # config·orgs·plugins·credentials·presets·env .json (git 비추적)
├─ tests/               # fake 주입 단위 테스트
└─ docs/                # Architecture.md · Scenario.md · mockup/
```

## 요구 사항

- **Python ≥ 3.8** — venv 없이 `python -m`으로 실행 (§9)
- 챗 탭의 `claude-agent-sdk`만 3.10+ 필요 — 3.8·3.9에서는 `claude` CLI subprocess 폴백으로 동작 (§12.3)

## 사용법 (구현 후)

```bash
./run.sh          # linux — 셋업부터 브라우저까지 한 번에 (끝낼 땐 브라우저 창 닫기)
run.cmd           # windows
pm list           # CLI (PATH 등록 후 어디서든)
pm org add <url>  # organization 등록 (권한 있어야 등록됨)
```
