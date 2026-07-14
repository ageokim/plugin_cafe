# Implementation — 구현 계획·체크리스트

> **living document** — 구현이 진행되는 동안 이 문서의 체크박스를 채워 나간다.
> 설계의 근거·방법은 전부 [Architecture.md](Architecture.md)에 있다(§참조). 이 문서는 **무엇을, 어떤 순서로** 만들지와
> **완료 판정 기준**만 다룬다 — 설계 내용을 여기 중복 서술하지 않는다.

## 0. 문서 사용법

- 작업 하나를 끝내면 해당 항목을 `[x]`로 바꾼다. 마일스톤의 **DoD(완료 기준)** 를 확인한 뒤 §1 현황표를 갱신한다.
- 마일스톤 순서는 의존 방향(infrastructure → domain → services → presentation)이다 — **건너뛰지 않는다**.
- 각 마일스톤은 **테스트와 함께 커밋**한다 (fake 주입 단위 테스트, §13.3). 커밋은 `feat/pm-core` 브랜치.
- 구현 중 설계와 어긋나는 결정이 필요해지면: 코드가 아니라 **Architecture.md를 먼저 고치고** 그 §를 여기서 참조한다.

## 1. 진행 현황

| 마일스톤 | 내용 | 상태 |
|---|---|---|
| M0 | 개발 기반 (requirements·lint·pytest) | ⬜ |
| M1 | 기반 모듈 (paths·errors·models·config·store) | ⬜ |
| M2 | GitHub 연동 (urls·client·rest_client·scanner) | ⬜ |
| M3 | 설치·등록 코어 (gitops·registry·services·container) | ⬜ |
| M4 | CLI + envcheck — **첫 실사용 지점** | ⬜ |
| M5 | Flask API (REST·SSE 챗·WS 터미널·수명) | ⬜ |
| M6 | 프론트 web/ | ⬜ |
| M7 | launcher (run.sh/run.cmd·env/ 셋업) | ⬜ |
| M8 | 통합 검증 (시나리오 1~8 워크스루) | ⬜ |

상태: ⬜ 미착수 · 🔄 진행중 · ✅ 완료(DoD 통과)

## 2. 공통 규칙 리마인더 (구현 내내 적용)

- **no-venv** (§9): 실행은 항상 `"$PYTHON" -m …`, 의존성은 `pip install --user`. Python ≥ **3.8** —
  전 모듈 첫 임포트로 `from __future__ import annotations`, `claude-agent-sdk`는 3.10+ marker(§9.2).
- **SOLID** (§2): 조립(구현체 생성·주입)은 `container.py`에서만. 변경 가능값(host·port·태그 등)은 하드코딩 금지 — config 주입(§2.3).
- **상태는 저장하지 않는다** — 파일시스템에서 실측 도출(§6.4). preset 뱃지도 도출(§6.5).
- **보안** (§11): 토큰은 `data/credentials.json`(600, 비추적) 외 어디에도 쓰지 않는다. clone 인증은
  `GIT_CONFIG_COUNT/KEY/VALUE` env 방식(`-c http.extraHeader` 금지), `GIT_TERMINAL_PROMPT=0`, skip-permissions 금지.
- **스타일** (§13.1): Google Python Style — 절대 임포트, Google 독스트링, enum 상태값, bare except 금지, 80자.
- **테스트** (§13.3): services는 fake 주입(가짜 GitHubClient·tmp 경로 ProjectPaths·기록형 GitRunner),
  API는 `app.test_client()` + fake services. 실행은 `"$PYTHON" -m pytest`.

## 3. 마일스톤

### M0 — 개발 기반

목표: 테스트·린트가 도는 최소 바닥. 코드 없음.

- [ ] `env/requirements.txt` — `flask>=3.0`, `flask-sock`, `requests>=2.31`, `claude-agent-sdk ; python_version >= "3.10"`, `pywinpty ; platform_system=="Windows"` (§9.2 — 하한 핀만)
- [ ] `env/requirements-dev.txt` — pytest, pylint(+formatter) (§13.3)
- [ ] `pyproject.toml` — pylint(Google 설정)·formatter 설정 채움 (lint 전용 유지, 패키징 금지 §13.3)
- [ ] `tests/` 에 스모크 테스트 1개 → `"$PYTHON" -m pytest` 통과 확인 (scripts/ 를 import path에 넣는 conftest.py 포함)

**DoD**: 클린 체크아웃에서 `pip install --user -r env/requirements-dev.txt` 후 pytest·pylint가 돈다.

### M1 — 기반 모듈 (의존성 없음)

목표: 이후 전 모듈이 딛고 설 바닥. 순서대로.

- [ ] `pm/paths.py` — `ProjectPaths` dataclass, ROOT 탐색(모듈 위치 기준, cwd 무관 §9.3), data/·plugins/ 경로의 유일한 정의처 (§5)
- [ ] `pm/errors.py` — `PmError` → `GitHubError/GitOpsError/RegistryError/ConfigError/AuthError` (§5)
- [ ] `pm/models.py` — 불변 dataclass `Plugin/Org`, `PluginState` enum(미설치/꺼짐/사용중 도출용 §6.4), `CheckResult`, preset 모델(§8.5)
- [ ] `pm/config.py` — `ConfigProvider`: 기본값 → `data/config.json` → `PM_*` 환경변수 → CLI 플래그 계층 (§8.1). 변경 가능값 표(§2.3) 전 항목 커버
- [ ] `pm/store/json_store.py` — 원자적 쓰기(임시파일+rename), 손상 시 기본값+경고, credentials 파일은 권한 600 (§5·§8.4)

테스트: 각 모듈별 — tmp 경로 주입으로 실 파일시스템 오염 없이 (§13.3).

- [ ] paths: 임의 cwd에서도 ROOT 동일 / config: 계층 우선순위·기본값 / store: 원자성(부분 쓰기 없음)·손상 복구·600 권한

**DoD**: M1 전 모듈 단위 테스트 통과. 어떤 모듈도 network·전역 상태에 의존하지 않는다.

### M2 — GitHub 연동

> ⚠ 착수 전 §15 #1(플러그인 repo 규약 — 부록 A 확정) 해결 — §4 참고.

- [ ] `github/urls.py` — `parse_host`, `parse_target`(dot-heuristic — 계정명에 점 불가 §10), `ApiUrlBuilder`(github.com→`api.github.com`, GHES→`https://{host}/api/v3`)
- [ ] `github/client.py` — `GitHubClient` Protocol: `verify_token/resolve_target/fetch_repos/check_org_membership` (§5)
- [ ] `github/rest_client.py` — requests 구현체. 생성자 주입: `api_base_url/token_provider/ca_bundle`(§5). **3-way repo listing**(org=`type=all`, 타인=`type=owner`, 본인=`/user/repos?type=owner` §10), Link 헤더 페이지네이션 per_page=100, 멤버십 `state=active` 게이트(§10.2)
- [ ] `github/scanner.py` — description이 설정된 태그(`plugin_tags`)를 **모두** 포함하는 repo 필터 (§5, 부록 A.1)

테스트:

- [ ] urls: github.com/GHES/`org/repo` URL/점 포함 host 케이스 / rest_client: fake `requests` 응답으로 3-way 분기·페이지네이션·401/403 → `GitHubError` / scanner: 태그 부분 일치는 탈락
- [ ] 실 github.com 수동 스모크 1회 (PAT로 본인 계정 repo 목록 — private 포함 확인)

**DoD**: fake 테스트 전 통과 + 수동 스모크 성공.

### M3 — 설치·등록 코어

- [ ] `pm/gitops.py` — `GitRunner` Protocol + subprocess 구현: `clone/pull/head_commit`, 인증은 `GIT_CONFIG_*` env(§11), `GIT_TERMINAL_PROMPT=0`
- [ ] `claudeplug/registry.py` — 하이브리드 등록(§6): marketplace.json 생성·갱신(이름충돌 시 신규만 `{org}-{name}` §6.2), `enabledPlugins` 토글(§8.7), 규약 검사(부록 A)
- [ ] `services/auth_service.py` — 로그인 검증(ID/PAT), credentials.json 자동 저장/로드, 시작 시 org 일괄 재검증, 미검증 세션(§10.2)
- [ ] `services/org_service.py` — org 등록/삭제/재검증: URL 파싱 → 단일 host 정책 → 멤버십 게이트 → orgs.json (§10.2)
- [ ] `services/catalog_service.py` — 스캔 → 보이는 repo 전부 저장(`has_tags` 플래그) → 출력 시 태그 필터, `--cached/--all` 동일 캐시 (§5·§7)
- [ ] `services/install_service.py` — clone → 규약검사 → 등록 (실패 시 부분 clone 정리) / uninstall 역순 (§6.2)
- [ ] `services/activation_service.py` — enable/disable: registry 위임 + 캐시 복사(§6.3)
- [ ] `services/inspect_service.py` — 실측 대조 리포트, `--repair` (§7)
- [ ] `services/preset_service.py` — CRUD + 일괄(enable은 자동 설치, 부분 실패 무중단·멤버별 결과 수집) + apply(전환) (§6.5·§8.5)
- [ ] `pm/container.py` — 조립 루트: 설정 읽기 → 구현체 생성·주입 여기서만 (§2.2·§4)

테스트:

- [ ] 기록형 GitRunner + tmp 경로로: 설치→활성→비활성→삭제 전 흐름 / 이름충돌 rename / uninstall 시 enabledPlugins 정리 / update의 활성 상태 보존(§6.2) / preset 일괄의 부분 실패 계속 진행·apply의 "멤버 외 전부 끄기"
- [ ] registry: marketplace.json이 Claude Code 스키마와 일치(§6.2 예시 대조)

**DoD**: 임시 디렉토리 전 흐름 테스트 통과. 실 GitHub 없이 전부 fake로 검증됨.

### M4 — CLI + envcheck  ← 첫 실사용 지점

- [ ] `pm/cli.py` + `pm/__main__.py` — §7 전 명령(org add/list/remove·list·install·uninstall·enable·disable·inspect·update·preset 6종·serve), 식별자 규칙(`org/name`, bare name은 유일할 때만), 종료코드 0/1/2, `--json`
- [ ] `system/process.py` — cwd=ROOT subprocess, 외부 터미널 실행(보조) (§5)
- [ ] `envcheck/checker.py` + `checks.py` — `Check` Protocol + §9.4 13항목, A(부트스트랩 게이트 1~5·13)/B(웹 6~12) 분리, 3.8·3.9 시 챗 폴백 정보성 안내
- [ ] `scripts/bin/pm`·`pm.cmd` — shim: 자기 위치 ROOT → `exec "$PYTHON" -m pm "$@"` (§9.3)

테스트:

- [ ] cli: fake services로 인자 파싱·종료코드·bare name 모호 시 후보 목록 / envcheck: fake 환경으로 각 Check 통과·실패 경로
- [ ] **E2E 수동**: 실 GitHub org 대상 `pm org add → list → install → enable → inspect` (테스트용 plugin repo 필요 — §4) 후 **새 claude 세션에서 플러그인 동작 확인**

**DoD**: E2E 수동 검증 성공 — 이 시점부터 CLI만으로 실사용 가능.

### M5 — Flask API

- [ ] `api/app.py` — app factory, blueprint 등록, `web/` 정적 서빙, **127.0.0.1 바인딩 강제** (§5)
- [ ] `api/auth.py` — login/logout/session (§12.6) / `api/orgs.py` — org CRUD(권한 게이트) / `api/plugins.py` — 카탈로그·플러그인 액션·inspect / `api/presets.py` — preset CRUD·액션 (§5)
- [ ] `api/lifecycle.py` — heartbeat(2s)·tab-close, watchdog 단독 종료 판정 (§12.5)
- [ ] `api/chat.py` — SSE 스트리밍, Agent SDK(3.10+) / subprocess 폴백(3.8·3.9) 자동 전환, `pm` 가로채기(`^pm\s`+allowlist) (§12.3)
- [ ] `system/terminal.py` + `api/terminal.py` — pty 세션 관리(POSIX pty/pywinpty) ↔ `WS /api/term`(flask-sock), 토큰 발급 `POST /api/term/token`(단기·1회용 §11) (§12.4)

테스트:

- [ ] `app.test_client()` + fake services: 전 REST 엔드포인트 계약(정상·오류 코드) / lifecycle: heartbeat 끊김 → watchdog 종료 판정 로직
- [ ] curl 스모크: serve 기동 후 login→orgs→plugins 왕복, SSE 챗 1문답

**DoD**: 계약 테스트 전 통과 + curl 스모크 성공. 외부 인터페이스에서 127.0.0.1 외 접근 불가 확인.

### M6 — 프론트 web/

- [ ] `web/vendor/xterm/` — xterm.js 로컬 동봉 (CDN 금지 §13.2)
- [ ] `web/index.html` — 단일 페이지: 로그인 뷰 ↔ 메인 뷰(사이드바+챗+터미널). 디자인·동작은 [mockup/main.html](mockup/main.html)·[mockup/login.html](mockup/login.html) 이식 (§12.1·12.2)
- [ ] `web/css/style.css` — 사이드바 고정/미고정, 탭 전환, 한국어 상태 라벨(사용중/꺼짐/미설치), preset 섹션 (§12.2)
- [ ] `web/js/app.js` — 세션 확인→뷰 라우팅, heartbeat 시작, `sendBeacon` tab-close (§12.5)
- [ ] `web/js/sidebar.js` — org 추가/삭제, 검색+칩, 플러그인 액션(삭제는 인라인 확인), preset 렌더·일괄 액션 (§12.2)
- [ ] `web/js/chat.js` — SSE 수신 렌더, [새 대화], "새 대화부터 적용" 안내 (§12.3)
- [ ] `web/js/term.js` — xterm 초기화, WS 연결(토큰), 리사이즈, 세션 종료 시 [새 터미널] (§12.4)

테스트: 로직은 services/API에 있으므로(§13.2) 프론트는 브라우저 수동 스모크.

- [ ] 시나리오 3(로그인)·4(설치)·5(claude 탭 전환·새 대화) 브라우저 워크스루

**DoD**: 브라우저에서 시나리오 3·4·5 동작. JS에 도메인 로직 없음(전부 API 호출).

### M7 — launcher

- [ ] `env/` 셋업 스크립트(OS별) — 인터프리터 탐색·`data/env.json` 고정(§9.1), pip 멱등 설치(§9.0·9.2), PATH 등록(Linux 심볼릭 링크 / Windows `SetEnvironmentVariable` — setx 금지 §9.3)
- [ ] `run.sh` — 셋업 → 부트스트랩 게이트(§9.4 A) → `"$PYTHON" -m pm serve &` → 브라우저 오픈 (§12.5)
- [ ] `run.cmd` — 동일 흐름, `powershell -NoProfile -ExecutionPolicy Bypass` 진입(§9.3)

테스트 (수동):

- [ ] 클린 환경(패키지 미설치)에서 `./run.sh` 원샷: 셋업→체크→브라우저까지 / 재실행 시 pip 생략(멱등 §9.0)
- [ ] 브라우저 창 닫기 → grace 후 서버 종료 실측 / 탭 새로고침·일시 백그라운드에서는 **종료되지 않음** (§12.5)

**DoD**: 클린 환경 원샷 기동 + 창 닫기=종료 실측 확인.

### M8 — 통합 검증

- [ ] [Scenario.md](Scenario.md) 시나리오 1 — 최초 실행 (원샷 셋업)
- [ ] 시나리오 2 — 체크리스트 (항목 고의 실패 시 수정 명령 표시)
- [ ] 시나리오 3·3.5 — 로그인·미검증 세션·org 추가(권한 게이트·타 host 거부)
- [ ] 시나리오 4 — 검색→설치→상태 갱신
- [ ] 시나리오 5 — claude 챗에서 플러그인 사용(새 세션 반영 규칙)
- [ ] 시나리오 6 — 재실행 자동 로그인·창 닫기 종료
- [ ] 시나리오 7 — 상태 관리(켜기/끄기/삭제 인라인 확인/업데이트)
- [ ] 시나리오 8 — preset 생성→일괄→전환(멤버 외 끄기)
- [ ] §9.4 체크리스트 13항목 실기 확인 (일부러 하나씩 깨뜨려 안내 확인)
- [ ] README 사용법 최신화 ("구현 후" 문구 제거)

**DoD**: 시나리오 1~8 전부 통과. main 머지 후보.

## 4. 미결정·차단 요소

| # | 항목 | 언제까지 | 비고 |
|---|---|---|---|
| 1 | **플러그인 repo 규약 확정** (§15 #1, 부록 A 초안 → org 표준) | **M2 scanner 착수 전** | description 태그·`.claude-plugin/plugin.json` 요건이 scanner/규약검사의 입력 |
| 2 | 테스트용 실 plugin repo 1개 준비 (부록 A 규약 준수) | M4 E2E 전 | 본인 계정/org에 생성 — `#plugin #release` + plugin.json |
| 3 | enable/disable 구현 경로 (settings 직접 편집 vs claude CLI 위임, §15 #6) | M3 registry 구현 중 | registry 인터페이스 뒤라 늦게 정해도 무방 |
