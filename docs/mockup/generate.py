"""목업 재생성기 — web/ 실구현의 스냅샷으로 docs/mockup/*.html 생성.

실행: python3 docs/mockup/generate.py  (repo 루트에서)
실제 web/index.html 마크업 + web/css/style.css를 인라인하고, JS가
채우는 동적 영역에만 샘플 데이터를 박아 넣는다 — 구현과 목업이 같은
클래스·스타일을 쓰므로 모습이 어긋나지 않는다 (§12 목업 원칙).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MOCK_CSS = """
/* ── 목업 전용 (카페 테마 §12.1) ── */
.mock-banner { background:rgba(217,164,65,.12); color:#9a7422; text-align:center;
               font-size:.74rem; padding:5px; border-bottom:1px solid rgba(217,164,65,.25); }
.term-mock { flex:1; overflow-y:auto; background:var(--term-bg); margin:14px 18px 18px;
             border:1px solid var(--line3); border-radius:14px; padding:14px;
             font-family:"SF Mono",Menlo,Consolas,monospace; font-size:.76rem;
             color:var(--term-fg); white-space:pre-wrap; }
.term-mock .p { color:var(--term-prompt); } .term-mock .g { color:var(--term-green); }
"""

HEAD = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Plugin Cafe — {title} (목업)</title>
<style>
{css}
{mock}
</style>
</head>
<body>
{sprite}
<div class="mock-banner">{banner}</div>
"""

# JS가 채우는 동적 영역의 샘플 데이터 (실구현 클래스 그대로)
FILL = {
  '<span id="connHost"></span><b id="connId"></b>':
      '<span>github.xxx.xxx · </span><b>ageokim</b> <span style="color:var(--dim)">(자동 로그인)</span>',
  '<div class="chips" id="chips"></div>': '''<div class="chips" id="chips">
            <span class="chip on">전체 8</span>
            <span class="chip"><span class="d enabled"></span>추출중 3</span>
            <span class="chip"><span class="d installed"></span>보관중 1</span>
            <span class="chip"><span class="d available"></span>재료 없음 4</span>
          </div>''',
  '<div id="presetList"></div>': '''<div id="presetList"><div class="menu-board">
            <div class="preset"><span class="pd on"></span><span class="nm">코드리뷰 세트</span><span class="lead"></span><span class="n">3개 · 전부 켜짐</span><button class="btn sm primary">전환</button><button class="btn ghost sm">⋯</button></div>
            <div class="preset"><span class="pd off"></span><span class="nm">문서작업 세트</span><span class="lead"></span><span class="n">2개 · 꺼짐</span><button class="btn sm">전환</button><button class="btn ghost sm">⋯</button></div>
            <div class="preset"><span class="pd partial"></span><span class="nm">실험 세트</span><span class="lead"></span><span class="n">4개 · 일부 켜짐</span><button class="btn sm">전환</button><button class="btn ghost sm">⋯</button></div>
          </div></div>''',
  '<div id="pluginList"></div>': '''<div id="pluginList">
          <div class="org-card">
          <div class="org-h"><svg class="ic" style="width:14px;height:14px"><use href="#i-dripper"/></svg><span>org-a</span> <span class="n">재료 3가지 · 2가지 준비됨</span><span class="tag recipe">RECIPE</span>
            <span class="sp"><button class="btn ghost sm" title="재스캔"><svg class="ic" style="width:12px;height:12px"><use href="#i-refresh"/></svg></button><button class="btn ghost sm" title="org 제거 (설치본 포함 삭제)"><svg class="ic" style="width:12px;height:12px"><use href="#i-x"/></svg></button></span></div>
          <div class="plugin"><svg class="ic bean-on" style="width:13px;height:13px"><use href="#i-bean"/></svg><span class="nm">plugin-a</span><span class="lead"></span><span class="desc">코드 리뷰 자동화</span><button class="btn ghost sm addp" title="preset에 추가"><svg class="ic" style="width:11px;height:11px"><use href="#i-plus"/></svg></button><span class="st on"><span class="d"></span>추출중</span><span class="acts"><button class="btn ghost sm">끄기</button><button class="btn ghost sm danger" title="삭제"><svg class="ic" style="width:12px;height:12px"><use href="#i-trash"/></svg></button></span></div>
          <div class="plugin"><svg class="ic bean-off" style="width:13px;height:13px"><use href="#i-bean"/></svg><span class="nm">plugin-b</span><span class="lead"></span><span class="desc">API 클라이언트 생성</span><button class="btn ghost sm addp" title="preset에 추가"><svg class="ic" style="width:11px;height:11px"><use href="#i-plus"/></svg></button><span class="st off"><span class="d"></span>보관중</span><span class="acts"><button class="btn ghost sm">켜기</button><button class="btn ghost sm danger" title="삭제"><svg class="ic" style="width:12px;height:12px"><use href="#i-trash"/></svg></button></span></div>
          <div class="plugin"><svg class="ic bean-off" style="width:13px;height:13px"><use href="#i-bean"/></svg><span class="nm">plugin-c</span><span class="lead"></span><span class="desc">문서 템플릿</span><button class="btn ghost sm addp" title="preset에 추가"><svg class="ic" style="width:11px;height:11px"><use href="#i-plus"/></svg></button><span class="st no"><span class="d"></span>재료 없음</span><span class="acts"><button class="btn sm primary"><svg class="ic" style="width:11px;height:11px"><use href="#i-dl"/></svg>담기</button></span></div>
          </div>
          <div class="org-card tint-1">
          <div class="org-h"><svg class="ic" style="width:14px;height:14px"><use href="#i-dripper"/></svg><span>org-b</span> <span class="n">재료 5가지 · 1가지 준비됨</span><span class="tag recipe">RECIPE</span>
            <span class="sp"><button class="btn ghost sm" title="재스캔"><svg class="ic" style="width:12px;height:12px"><use href="#i-refresh"/></svg></button><button class="btn ghost sm" title="org 제거 (설치본 포함 삭제)"><svg class="ic" style="width:12px;height:12px"><use href="#i-x"/></svg></button></span></div>
          <div class="plugin"><svg class="ic bean-on" style="width:13px;height:13px"><use href="#i-bean"/></svg><span class="nm">plugin-x</span><span class="lead"></span><span class="desc">로그 분석 workflow</span><button class="btn ghost sm addp" title="preset에 추가"><svg class="ic" style="width:11px;height:11px"><use href="#i-plus"/></svg></button><span class="st on"><span class="d"></span>추출중</span><span class="acts"><button class="btn ghost sm" title="업데이트 (새 버전 있음)"><svg class="ic" style="width:12px;height:12px"><use href="#i-refresh"/></svg></button><button class="btn ghost sm">끄기</button><button class="btn ghost sm danger" title="삭제"><svg class="ic" style="width:12px;height:12px"><use href="#i-trash"/></svg></button></span></div>
          <div class="plugin"><svg class="ic bean-off" style="width:13px;height:13px"><use href="#i-bean"/></svg><span class="nm">plugin-y</span><span class="lead"></span><span class="desc">보안 점검 skill</span><button class="btn ghost sm addp" title="preset에 추가"><svg class="ic" style="width:11px;height:11px"><use href="#i-plus"/></svg></button><span class="st no"><span class="d"></span>재료 없음</span><span class="acts"><button class="btn sm primary"><svg class="ic" style="width:11px;height:11px"><use href="#i-dl"/></svg>담기</button></span></div>
          </div>
        </div>''',
  '<div id="inspectBody"></div>':
      '<div id="inspectBody" style="padding-top:8px">org-a/plugin-a: clone ✓ 등록 ✓ 활성 ✓ · org-b/plugin-x: 업데이트 있음</div>',
  '<div class="msgs" id="msgs"></div>': '''<div class="msgs" id="msgs">
          <div class="msg sys">☕ 새 대화 — 활성화된 플러그인이 이 세션부터 적용됩니다</div>
          <div class="msg user">방금 받은 repo 코드리뷰 해줘</div>
          <div class="msg claude"><span class="skill"><svg class="ic" style="width:10px;height:10px"><use href="#i-spark"/></svg>plugin-a : code-review skill</span><br>3개 파일에서 2건의 이슈를 찾았습니다:<br>1. <b>auth.py:42</b> — 토큰 만료 검사 누락 …</div>
          <div class="msg user">1번 고쳐줘</div>
          <div class="msg claude">auth.py:42에 만료 검사를 추가했습니다. 테스트 7건 통과 ✓</div>
        </div>''',
  '<div class="term-host" id="termHost"></div>':
      '''<pre class="term-mock"><span class="p">$</span> pm list
<span class="g">org-a/</span>  plugin-a enabled   plugin-b installed   plugin-c available
<span class="g">org-b/</span>  plugin-x enabled   plugin-y available
<span class="p">$</span> claude          ← 완전한 대화형 claude (플러그인 적용)
&gt; /plugin-a:review src/
  ⏺ 실행 중...
&gt; exit            ← claude 종료 → 셸 복귀
<span class="p">$</span> ▮</pre>''',
  '<div class="wf-list" id="wfList"></div>': '''<div class="wf-list" id="wfList">
          <div class="wf-card">
            <div class="wf-head"><span class="wf-state done"></span><span class="wf-title">코드리뷰 요청</span><span class="wf-statetxt">완료</span></div>
            <div class="wf-line">
              <div class="wf-step done"><span class="wf-dot done">✓</span><div class="wf-body"><span class="wf-name">org 스캔</span><span class="wf-sum">repo 8개 확인</span></div><span class="wf-time">10:02:11</span></div>
              <div class="wf-step done plugin"><span class="wf-dot done">✓</span><div class="wf-body"><span class="wf-name">code-review skill</span><span class="wf-plugin-badge">plugin-a</span><span class="wf-sum">이슈 2건 발견</span></div><span class="wf-time">10:02:34</span></div>
              <div class="wf-step failed"><span class="wf-dot failed">✗</span><div class="wf-body"><span class="wf-name">테스트 실행</span><span class="wf-sum">1건 실패 — 재시도</span></div><span class="wf-time">10:03:01</span></div>
              <div class="wf-step running"><span class="wf-dot running"></span><div class="wf-body"><span class="wf-name">auth.py 수정</span><span class="wf-sum">진행 중…</span></div><span class="wf-time">10:03:15</span></div>
            </div>
          </div>
        </div>''',
  '<span class="hint" id="hintTxt"></span>':
      '<span class="hint" id="hintTxt">plugin-a 담김(설치) — 새 대화부터 적용 · cwd=plugin_market</span>',
}

DEMO_JS = """
<script>
  // ── 목업 데모 JS: 탭·사이드바 고정/호버·org 팝오버·화면 이동만 ──
  const views = { tabChat: "view-chat", tabTerm: "view-term", tabFlow: "view-flow" };
  const actions = { tabChat: "새 대화", tabTerm: "새 터미널", tabFlow: null };
  for (const tabId of Object.keys(views)) {
    document.getElementById(tabId).addEventListener("click", () => {
      for (const [t, v] of Object.entries(views)) {
        document.getElementById(t).classList.toggle("on", t === tabId);
        document.getElementById(v).classList.toggle("on", t === tabId);
      }
      const label = actions[tabId];
      document.getElementById("actionBtn").style.display = label ? "" : "none";
      if (label) document.getElementById("actionTxt").textContent = label;
    });
  }
  document.getElementById("logoutBtn").addEventListener("click",
    () => location.href = "login.html");

  const app = document.getElementById("app"), sb = document.getElementById("sb");
  const rail = document.getElementById("rail"), pinBtn = document.getElementById("pinBtn");
  let pinned = true, hideTimer = null;
  pinBtn.addEventListener("click", () => {
    pinned = !pinned;
    document.getElementById("pinTxt").textContent = pinned ? "고정" : "미고정";
    app.classList.toggle("unpinned", !pinned);
    sb.classList.remove("open");
  });
  rail.addEventListener("mouseenter", () => { clearTimeout(hideTimer); sb.classList.add("open"); });
  sb.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  sb.addEventListener("mouseleave", () => {
    if (!pinned) hideTimer = setTimeout(() => sb.classList.remove("open"), 300);
  });

  // 사이드바 폭 조절 — 실구현(sidebar.js initResize)과 동일 데모 (§12.2)
  const sbResize = document.getElementById("sbResize");
  let sbw = 360;
  sbResize.addEventListener("mousedown", (e) => {
    e.preventDefault();
    document.body.classList.add("sb-resizing");
    const left = sb.getBoundingClientRect().left;
    const move = (ev) => {
      sbw = Math.min(Math.max(ev.clientX - left, 280),
                     Math.min(640, window.innerWidth * 0.6));
      document.documentElement.style.setProperty("--sbw", sbw + "px");
    };
    const up = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      document.body.classList.remove("sb-resizing");
    };
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  });
  sbResize.addEventListener("dblclick", () => {
    sbw = 360;
    document.documentElement.style.setProperty("--sbw", "360px");
  });

  // org 추가 팝오버 (§12.2) — 실구현과 동일한 열림/닫힘 데모
  const orgPop = document.getElementById("orgPop");
  const orgFab = document.getElementById("orgFab");
  const orgWrap = document.getElementById("orgFabWrap");
  orgFab.addEventListener("click", () => {
    orgPop.hidden = !orgPop.hidden;
    orgFab.classList.toggle("open", !orgPop.hidden);
    if (!orgPop.hidden) document.getElementById("orgUrl").focus();
  });
  document.addEventListener("click", (e) => {
    if (!orgPop.hidden && !orgWrap.contains(e.target)) {
      orgPop.hidden = true;
      orgFab.classList.remove("open");
    }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { orgPop.hidden = true; orgFab.classList.remove("open"); }
  });

  // preset [+] 이름 입력 행 — 열기 + 바깥 클릭/Esc로 접힘 (§12.2)
  const pRow = document.getElementById("presetNewRow");
  const pBtn = document.getElementById("presetNewBtn");
  pBtn.addEventListener("click", () => {
    pRow.hidden = !pRow.hidden;
    if (!pRow.hidden) document.getElementById("presetNewName").focus();
  });
  document.addEventListener("click", (e) => {
    if (!pRow.hidden && !pRow.contains(e.target) && !pBtn.contains(e.target))
      pRow.hidden = true;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") pRow.hidden = true;
  });
</script>
"""


def main() -> None:
    css = (ROOT / "web/css/style.css").read_text(encoding="utf-8")
    # 폰트 @import는 web/css/ 기준 상대경로 — 목업(docs/mockup/) 기준으로 재작성
    css = css.replace('url("../vendor/fonts/fonts.css")',
                      'url("../../web/vendor/fonts/fonts.css")')
    index = (ROOT / "web/index.html").read_text(encoding="utf-8")
    sprite = re.search(r'<svg style="display:none".*?</svg>', index,
                       re.S).group(0)
    out = ROOT / "docs/mockup"

    # ── login.html ──
    view = re.search(r'<section id="view-login" hidden>(.*?)</section>',
                     index, re.S).group(1)
    view = view.replace('<input id="loginId" autocomplete="username">',
                        '<input id="loginId" value="ageokim">')
    view = view.replace(
        '<input id="loginPwd" type="password" autocomplete="current-password">',
        '<input id="loginPwd" type="password" value="ghp_xxxxxxxxxxxx">')
    view = view.replace(
        '<form class="login-card" id="loginForm">',
        '<form class="login-card" '
        'onsubmit="location.href=\'main.html\';return false">')
    login = HEAD.format(
        title="로그인 전", css=css, mock=MOCK_CSS, sprite=sprite,
        banner="목업 — 실구현(web/) 스냅샷 · [입장하기] 버튼 → "
               "\"입장 후\" 화면으로 이동",
    ) + f'<section id="view-login">{view}</section>\n</body>\n</html>\n'
    (out / "login.html").write_text(login, encoding="utf-8")

    # ── main.html ──
    view = re.search(
        r'<section id="view-main" hidden>(.*?)</section>\s*<div class="toasts"',
        index, re.S).group(1)
    for old, new in FILL.items():
        assert old in view, f"실구현에서 못 찾음(구조 변경?): {old[:60]}"
        view = view.replace(old, new)
    main_html = HEAD.format(
        title="로그인 후", css=css, mock=MOCK_CSS, sprite=sprite,
        banner="목업 — 실구현(web/) 스냅샷 · 탭(Claude/터미널/Workflow) · "
               "전송 버튼 왼쪽 ☕(커피가루) = org 추가 팝오버 · 고정 버튼/왼쪽 호버 · "
               "로그아웃 → 입장 화면",
    ) + f'<section id="view-main">{view}</section>\n{DEMO_JS}\n</body>\n</html>\n'
    (out / "main.html").write_text(main_html, encoding="utf-8")
    print("docs/mockup/login.html · main.html 재생성 완료")


if __name__ == "__main__":
    main()
