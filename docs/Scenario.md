# plugin_market — 사용자 시나리오

> [Architecture.md](Architecture.md)의 설계를 **사용자 입장**에서 단계별로 표현한 문서.
> 각 시나리오는 "사용자가 하는 행동 → 화면에 보이는 것" 기준으로 그렸다.

---

## 0. 등장 요소 — 사용자가 만나는 것들

```mermaid
flowchart LR
    U["👤 사용자"] -->|"브라우저로 본다"| SHELL["🌐 셸 페이지<br>(git 서버가 배포하는 웹)"]
    SHELL -->|"대시보드 영역 iframe"| ST["🖥️ 로컬 Streamlit<br>(내 PC에서 실행)"]
    ST -->|"스캔·설치"| GH["☁️ GitHub org"]
    ST -->|"플러그인 등록"| CL["🤖 local claude"]
    U -->|"최초 1회: run.sh 실행"| ST
```

사용자가 직접 만지는 것은 **두 가지뿐**이다:
1. 터미널에서 `run.sh` 실행 (최초 또는 서버가 꺼져 있을 때)
2. 브라우저 화면 (나머지 전부)

---

## 시나리오 1 — 처음 시작하기 (최초 실행)

```mermaid
sequenceDiagram
    actor U as 👤 사용자
    participant T as 터미널
    participant B as 브라우저
    participant ST as 로컬 Streamlit

    U->>T: ① git clone + ./run.sh
    Note over T: 자동 셋업 (멱등)<br>python 확인 → 라이브러리 확인<br>(이미 있으면 pip 생략)<br>pm 명령 PATH 등록
    T->>ST: ② Streamlit 백그라운드 기동
    T->>B: ③ 셸 페이지 자동 오픈
    Note over B: "서버 연결 대기 중…" 잠깐 표시<br>(2초마다 자동 재시도)
    ST-->>B: ④ 준비 완료 → 자동 연결
    B-->>U: ⑤ 로그인 창 표시 (시나리오 3)
```

**사용자가 하는 일:**

| 단계 | 행동 | 화면/결과 |
|---|---|---|
| ① | `git clone … && ./run.sh` | 터미널에 셋업 진행 로그 |
| ② | (없음 — 자동) | 브라우저가 저절로 열림 |
| ③ | (없음 — 자동) | 잠깐 "연결 대기 중" → 로그인 창 |

> 환경이 미비하면 로그인 창 대신 **체크리스트 화면**이 먼저 뜬다 → 시나리오 2.

---

## 시나리오 2 — 환경이 미비할 때 (체크리스트)

```
┌──────────────────────────────────────────────┐
│  환경 셋업 체크리스트                        │
├──────────────────────────────────────────────┤
│  ✅ python 3.12 발견                         │
│  ✅ 라이브러리 (streamlit·requests·keyring)  │
│  ❌ claude CLI 없음                          │
│      원인: claude 명령을 찾을 수 없습니다    │
│      👉 npm install -g @anthropic-ai/claude-code  [복사] │
│  ❌ pm PATH 미등록                           │
│      👉 ./env/setup_linux.sh                 [복사] │
│                                              │
│               [ 🔄 재검사 ]                  │
└──────────────────────────────────────────────┘
```

```mermaid
flowchart LR
    A["체크리스트 화면<br>✅/❌ 항목별 표시"] --> B["❌ 항목의<br>추천 명령어 복사 버튼 클릭"]
    B --> C["터미널에 붙여넣어 실행"]
    C --> D["🔄 재검사 버튼"]
    D -->|"아직 ❌ 남음"| A
    D -->|"모두 ✅"| E["로그인 창으로 자동 진행"]
```

**사용자가 하는 일:** ❌ 항목 옆의 명령을 복사 → 터미널에서 실행 → 재검사. 그게 전부다.
무엇이 왜 안 되는지, 어떻게 고치는지를 화면이 다 알려준다.

---

## 시나리오 3 — 로그인 (셸의 첫 화면)

```
┌──────────────────────────────────────────────┐
│        🧩 Plugin Market — 로그인             │
├──────────────────────────────────────────────┤
│  ID    [ ageokim                          ]  │
│  PWD   [ ●●●●●●●●●●●●  (PAT)             ]  │
│  URL   [ https://github.xxx.xxx/myorg     ]  │
│                                              │
│  ☑ 로그인 상태 유지 (자동 로그인)           │
│                                              │
│               [ 로그인 ]                     │
└──────────────────────────────────────────────┘
```

- **URL 한 칸**에 회사 GitHub 주소를 그대로 붙여넣으면 호스트(`github.xxx.xxx`)와
  organization(`myorg`)이 자동으로 분리·인식된다.
- PWD 칸에는 GitHub 비밀번호가 아니라 **PAT**(Personal Access Token)를 넣는다.

```mermaid
flowchart TD
    A["로그인 버튼 클릭"] --> B{"① URL에서<br>호스트·org 파싱"}
    B -->|실패| F1["❌ '주소를 확인하세요'"]
    B --> C{"② 토큰 유효?"}
    C -->|실패| F2["❌ 'PAT가 올바르지 않습니다'"]
    C --> D{"③ 토큰 주인 == ID?"}
    D -->|실패| F3["❌ 'ID와 토큰이 일치하지 않습니다'"]
    D --> E{"④ org 멤버십 있음?"}
    E -->|실패| F4["❌ '이 organization에 권한이 없습니다'"]
    E -->|통과| OK["✅ 로그인 성공 → 메인 화면<br>(체크했다면 다음부터 자동 로그인)"]
```

어느 단계에서 왜 막혔는지 화면에 그대로 표시되므로, 사용자는 그 항목만 고치면 된다.

---

## 시나리오 4 — 플러그인 검색과 설치

```
┌────────────────────────────────────────────────────────┐
│  🧩 Plugin Market      연결: github.xxx.xxx/myorg  [로그아웃] │
├────────────────────────────────────────────────────────┤
│  [ 🔄 GitHub 스캔 ]   ☑ 태그 필터 (#plugin #release)   │
├────────────────────────────────────────────────────────┤
│  plugin-a  코드 리뷰 자동화     🟢 Enabled   [Disable][Uninstall] │
│  plugin-b  API 클라이언트 생성  🟡 Installed [Enable ][Uninstall] │
│  plugin-c  문서 템플릿          ⚪ Available [Install]            │
├────────────────────────────────────────────────────────┤
│  🔍 Inspect — 상태 상세                                │
└────────────────────────────────────────────────────────┘
```

```mermaid
sequenceDiagram
    actor U as 👤 사용자
    participant UI as 메인 화면
    participant GH as ☁️ GitHub org
    participant PC as 내 PC (plugins/)
    participant CL as 🤖 local claude

    U->>UI: ① "🔄 GitHub 스캔" 클릭
    UI->>GH: org repo 목록 조회
    GH-->>UI: description에 #plugin #release 있는 repo
    UI-->>U: ② 플러그인 목록 표시
    U->>UI: ③ plugin-c [Install] 클릭
    UI->>GH: git clone (private면 로그인 토큰 사용)
    GH-->>PC: plugins/plugin-c 저장
    UI->>CL: marketplace 등록 + 활성화
    UI-->>U: ④ 배지가 ⚪ → 🟢 Enabled로 변경
```

**사용자가 하는 일:** 스캔 버튼 → 목록에서 Install 클릭. 끝.
clone·등록·활성화는 내부에서 자동 처리된다 (흐름 상세: Architecture.md §6.2).

---

## 시나리오 5 — claude에서 플러그인 사용

```mermaid
flowchart LR
    A["메인 화면의<br>claude 창 (챗/터미널)"] --> B["claude 세션 시작<br>(작업 위치 = plugin_market)"]
    B --> C["🤖 시작 시점에 켜져 있는(Enabled)<br>플러그인의 skill·command를 읽어들임"]
    C --> D["예: /aa 명령, 코드리뷰 skill 사용"]
```

- 챗 화면(기본): 브라우저 안에서 claude와 대화 — 원격(SSH) 환경에서도 동일하게 동작
- 터미널 모드(로컬 전용): 실제 터미널 창이 열리고 `claude`를 그대로 사용

### ⚠️ 적용 시점 규칙 — "새 세션부터"

플러그인은 claude가 **시작할 때** 읽어들인다. 그래서:

| 상황 | `/aa` 동작? |
|---|---|
| Install/Enable **후에 새로 시작한** claude 세션 | ✅ 바로 동작 |
| Install/Enable **전부터 열려 있던** claude 세션 | ❌ 재시작 필요 (아래 방법) |

### 🔄 claude 재시작 방법 (= 새 세션 시작)

**💬 챗 모드 — 버튼 하나:**

```mermaid
flowchart LR
    A["plugin-a Install 완료<br>(왼쪽 패널)"] --> B["오른쪽 claude 창의<br>[➕ 새 대화] 버튼 클릭"]
    B --> C["새 세션 시작<br>plugin-a 자동 로딩"]
    C --> D["/aa 입력 → ✅ 동작"]
```

- 기존 대화는 종료되고 새 대화가 열린다 (앱·웹페이지는 그대로 — 껐다 켤 필요 없음)
- Install 직후에는 화면에 "새 대화부터 적용됩니다" 안내가 함께 표시된다

**🖥️ 터미널 모드 — exit 후 다시 실행:**

```
> exit                    ← ① 지금 쓰던 claude 종료 (또는 Ctrl+C 두 번)
$                         ← 터미널(쉘)로 복귀. 창은 그대로 살아 있음
$ claude                  ← ② 다시 실행 = 새 세션
╭─────────────────────────────╮
│ ✻ Claude Code               │
│   plugins: plugin-a ✔       │   ← 방금 설치한 플러그인이 로딩됨
╰─────────────────────────────╯
> /aa                     ← ③ ✅ 동작
```

- 터미널 창 자체를 닫고(창의 ✕ 또는 `exit` 한 번 더) UI에서 터미널 버튼으로 새로 열어도 같다

**재시작이 필요 없는 것들 (혼동 주의):**

| 대상 | 재시작 필요? |
|---|---|
| claude 세션 | ✅ 이것만 새로 시작하면 됨 |
| Streamlit(웹 화면) | ❌ 그대로 둠 |
| 셸 페이지(브라우저) | ❌ 그대로 둠 |
| run.sh 재실행 | ❌ 불필요 |

---

## 시나리오 6 — 다음날 다시 실행 (두 번째부터)

```mermaid
sequenceDiagram
    actor U as 👤 사용자
    participant T as 터미널
    participant B as 브라우저

    U->>T: ./run.sh
    Note over T: 셋업 전부 "이미 충족 → 건너뜀"<br>(pip 안 돌음, 몇 초 내 기동)
    T->>B: 셸 자동 오픈
    Note over B: 저장된 로그인(keyring)으로<br>권한 자동 재확인
    B-->>U: 로그인 창 없이 바로 메인 화면 ✅
```

- **셋업은 멱등** — 패키지·PATH·설정이 이미 있으므로 아무것도 재설치하지 않는다 (§9.0)
- **자동 로그인** — "로그인 상태 유지"를 체크해 뒀다면 로그인 창을 건너뛴다.
  단, org 권한 확인은 매번 다시 수행되므로 권한이 회수된 계정은 자동으로 로그인 창으로 돌아간다
- 토큰이 만료된 경우: 로그인 창이 다시 뜨고 "PAT가 올바르지 않습니다" 안내

### 고급 — 로그인 파일로 처음부터 완전 자동 시작

로그인 창을 한 번도 거치기 싫다면, `data/login.json`을 **미리 작성**해 두면 된다:

```json
{
  "id": "ageokim",
  "url": "https://github.xxx.xxx/myorg",
  "token_env": "PM_GITHUB_TOKEN",
  "remember": true
}
```

```mermaid
flowchart LR
    A["./run.sh"] --> B{"data/login.json<br>있음?"}
    B -->|"예"| C["파일의 ID·URL·토큰으로<br>권한 자동 확인"]
    C -->|"통과"| D["✅ 로그인 창 없이<br>바로 메인 화면"]
    C -->|"실패"| E["로그인 창<br>(값은 채워져 있음)"]
    B -->|"아니오"| F{"keyring에<br>저장된 로그인?"}
    F -->|"예"| C
    F -->|"아니오"| E
```

- 토큰은 `token_env`(환경변수 이름)로 지정하는 것을 권장 — 파일에 직접 쓰는 `token` 필드도
  되지만 평문 저장이라 비권장(시작 시 경고 표시)
- 이 파일이 있어도 **org 권한 확인은 매번 수행**된다 — 권한 없는 계정이 우회할 수는 없다

---

## 시나리오 7 — 플러그인 관리 (사용자 버튼 기준 상태 변화)

```mermaid
stateDiagram-v2
    Available: ⚪ Available (org에 존재)
    Installed: 🟡 Installed (내 PC에 있음, 꺼짐)
    Enabled: 🟢 Enabled (claude가 사용 중)

    Available --> Enabled : Install 클릭
    Enabled --> Installed : Disable 클릭
    Installed --> Enabled : Enable 클릭
    Installed --> Available : Uninstall 클릭
    Enabled --> Available : Uninstall 클릭
```

| 버튼 | 일어나는 일 | 이후 claude에서 |
|---|---|---|
| Install | 다운로드 + 등록 + 켜기 | 바로 사용 가능 |
| Disable | 끄기만 (파일은 유지) | 안 보임 |
| Enable | 다시 켜기 | 다시 사용 가능 |
| Uninstall | 끄기 + 등록 해제 + 파일 삭제 | 안 보임 |
| Update | 새 버전 받아 재등록 | 새 버전 사용 |

- **Inspect** 화면을 열면 각 플러그인의 실제 상태(파일 존재·등록·켜짐 여부, 버전 차이)를
  표로 확인할 수 있다 — 뭔가 이상할 때 여기부터 본다.

---

## 한눈에 — 전체 여정 요약

```mermaid
journey
    title 사용자 여정 (처음 → 일상 사용)
    section 최초 1회
      git clone + run.sh: 3: 사용자
      체크리스트 조치 (필요시): 3: 사용자
      로그인 (ID/PWD/URL): 4: 사용자
    section 매일
      run.sh (자동 로그인): 5: 사용자
      스캔·설치 클릭: 5: 사용자
      claude로 작업: 5: 사용자
```

| | 최초 1회 | 두 번째부터 |
|---|---|---|
| 터미널 | `git clone` + `./run.sh` (+ 체크리스트 조치) | `./run.sh` |
| 브라우저 | 로그인 → 스캔 → Install | 바로 메인 → claude 사용 |
| 소요 | 수 분 | 수 초 |
