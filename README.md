# Plugin Cafe

여러 GitHub organization의 Claude Code plugin을 한 곳에서 검색·설치·활성화하고 혼합 사용하는 도구.

## 요구 사항

- Python ≥ 3.8 (가상환경 불필요 — `pip install --user` 방식)
- git, Claude Code CLI(`claude`)
- GitHub PAT (`repo` + `read:org` 스코프) — organization 접근 권한 필수

## 시작하기

```bash
git clone https://github.com/ageokim/plugin_cafe.git
cd plugin_cafe
./run.sh          # linux/macOS  (windows: run.cmd)
```

브라우저가 자동으로 열립니다. **끝낼 때는 브라우저 창을 닫으면** 서버도 함께 종료됩니다.

1. **로그인** — GitHub ID + PAT (한 번 로그인하면 자동 저장되어 다음부터 생략)
2. **org 추가** — 챗 입력줄 왼쪽 **☕ 아이콘** → organization URL 입력 (권한 있는 org만 등록됨)
3. **설치** — 사이드바 목록에서 [설치] 클릭 → **[➕ 새 대화]**를 열면 claude에 바로 적용

환경이 미비하면 체크리스트 화면이 항목별 수정 명령을 알려줍니다.

## 화면 구성

| 영역 | 내용 |
|---|---|
| 사이드바 (📌 고정/미고정) | 플러그인 검색·설치·켜기/끄기·삭제 (org별 카드, 폭 드래그 조절), **Preset**(묶음 일괄 전환), Inspect |
| Claude 탭 | claude 챗 — 설치한 플러그인의 skill·command 사용 (`pm` 명령도 입력 가능) |
| 터미널 탭 | 브라우저 내장 진짜 셸 — `claude`(완전 대화형)·`pm` 직접 실행 |
| Workflow 탭 | claude 작업 단계 타임라인 (플러그인 사용 표시) |

## CLI (`pm`)

PATH 등록 후 어디서든 사용 가능 — 웹과 동일한 동작.

```bash
pm org add <url>      # organization 등록 (+ 자동 스캔)
pm list               # 카탈로그 스캔·목록 (org별)
pm install org/name   # 설치 (+활성화)
pm enable|disable|uninstall|update <name>
pm preset apply <세트> # preset 전환 — 멤버만 켜고 나머지는 끔
pm inspect [--env]    # 상태 실측 / 환경 체크리스트
```

전체 명령·옵션: [docs/Architecture.md](docs/Architecture.md) §7

## 자주 쓰는 규칙

- **플러그인 반영 시점**: 설치·켜기/끄기는 **새 claude 세션부터** — 챗의 [➕ 새 대화] 클릭
- **"포트 사용 중"**: 이전 Plugin Cafe 서버가 남은 경우면 다음 시작이 **자동으로 종료 후 인계** — 다른 프로그램이 점유한 경우에만 안내대로 조치
- **org 삭제(✕)**: 그 org의 설치본과 preset 멤버까지 함께 정리 (확인 후)
- 토큰은 `data/credentials.json`(권한 600)에만 저장 — 로그아웃해도 유지, 다른 계정으로 로그인하면 덮어씀

## 문서

| 문서 | 내용 |
|---|---|
| [docs/Architecture.md](docs/Architecture.md) | 설계 전체 (구조·규칙·결정 근거) |
| [docs/Scenario.md](docs/Scenario.md) | 사용자 시나리오 (그림 단계별) |
| [docs/Implementation.md](docs/Implementation.md) | 구현 마일스톤·진행 현황 |
| [docs/mockup/](docs/mockup/) | 화면 목업 (실구현 스냅샷) |
