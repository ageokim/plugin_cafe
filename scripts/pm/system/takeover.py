"""포트 자동 인계 (§12.5) — 이전 Plugin Cafe 서버가 남긴 포트 점유를 회수.

watchdog이 종료를 못 하고 남은 자기 서버 때문에 다음 시작이
"포트 사용 중" FAIL로 막히는 문제의 해법. **무조건 강제 종료는 하지
않는다** — 점유자가 ``GET /api/health`` 마커(app == "plugin-cafe")로
자기 서버임이 확인될 때만 그 pid를 종료하고 포트를 회수한다. 무관한
프로세스·권한 없는 프로세스(EPERM)는 손대지 않고 False를 돌려 기존
안내("점유 프로세스 종료 또는 flask_port 변경")로 흐르게 한다.

pid는 점유 서버 자신이 HTTP로 보고한 값이므로 probe 시점의 포트
주인이 맞다 — probe와 kill 사이 pid 재사용 경합은 초 단위 창에서
무시할 수준으로 본다.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import time
import urllib.request
from typing import Callable, Optional

logger = logging.getLogger(__name__)

APP_MARKER = "plugin-cafe"  # /api/health 응답의 app 필드 (api/lifecycle)
_HOST = "127.0.0.1"  # §11 — serve와 동일하게 루프백 전용
_TERM_SHARE = 0.6  # deadline 중 SIGTERM 대기 비율 — 나머지는 SIGKILL 몫
_POLL = 0.1

# 루프백 probe가 http_proxy 환경변수를 타고 외부 프록시로 새면 판별이
# 깨지고(§11 신뢰 경계 이탈) 프록시가 위조 응답으로 kill을 유도할 수
# 있다 — 프록시를 완전히 우회하는 전용 opener를 쓴다.
_DIRECT_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def port_busy(port: int) -> bool:
    """127.0.0.1:port에 이미 리스너가 있는가 — bind 실측 (§6.4 원칙).

    POSIX에서는 SO_REUSEADDR을 켠다 — werkzeug(app.run)의 실제 bind와
    같은 의미론으로 재야, probe·직전 종료가 남긴 TIME_WAIT 소켓(2MSL)을
    "점유 중"으로 오판하지 않는다. Windows의 SO_REUSEADDR은 살아있는
    리스너 위로도 bind가 성공해 거짓 'free'가 되므로 켜지 않는다
    (Windows는 TIME_WAIT plain bind가 원래 허용).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "posix":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((_HOST, port))
    except OSError:
        return True
    finally:
        sock.close()
    return False


def probe_cafe_server(
    port: int,
    opener: Callable[..., object] = _DIRECT_OPENER.open,
    timeout: float = 1.5,
) -> Optional[int]:
    """포트 점유자가 Plugin Cafe 서버면 그 pid — 아니면 None.

    연결 거부·타임아웃·비JSON·마커 불일치 전부 None ("우리 서버 아님").
    """
    url = f"http://{_HOST}:{port}/api/health"
    try:
        with opener(url, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
    except Exception:  # pylint: disable=broad-except
        return None
    if not isinstance(data, dict) or data.get("app") != APP_MARKER:
        return None
    pid = data.get("pid")
    return pid if isinstance(pid, int) and pid > 0 else None


def can_signal(pid: int, kill: Callable[[int, int], None] = os.kill) -> bool:
    """이 pid를 종료시킬 권한이 있는가 — POSIX 한정 실측.

    envcheck이 "자동 인계됨"을 안내하기 전에 확인해, 다른 사용자 소유
    서버(EPERM)로 serve가 실패할 상황을 체크 단계에서 걸러낸다.
    Windows는 신호 0도 TerminateProcess로 실행돼 검사가 불가능하므로
    낙관 반환(True) — 실패해도 serve가 안내와 함께 멈춘다.
    """
    if os.name != "posix":
        return True
    try:
        kill(pid, 0)
    except PermissionError:
        return False
    except OSError:
        pass  # 이미 죽음(ESRCH) 등 — 포트만 풀리면 되므로 낙관
    return True


def _wait_port_free(
    port: int,
    until: float,
    busy: Callable[[int], bool],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> bool:
    while clock() < until:
        if not busy(port):
            return True
        sleep(_POLL)
    return not busy(port)


def takeover_port(
    port: int,
    prober: Callable[[int], Optional[int]] = probe_cafe_server,
    kill: Callable[[int, int], None] = os.kill,
    busy: Callable[[int], bool] = port_busy,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    deadline: float = 5.0,
) -> bool:
    """포트가 비어 있거나 자기 서버 회수에 성공하면 True.

    자기 서버 pid가 확인된 경우에만 SIGTERM → (deadline 내 미해제 시)
    SIGKILL(POSIX 한정 — Windows os.kill(SIGTERM)은 이미 강제 종료)로
    끝내고 포트 해제를 기다린다.

    Args:
        port: 회수할 포트.
        prober/kill/busy/sleep/clock: 테스트 주입 seam.
        deadline: 종료 대기 총 한도 (초).
    """
    if not busy(port):
        return True
    pid = prober(port)
    if pid is None:
        return not busy(port)  # probe 사이 해제됐을 수 있음 — 재실측
    if pid == os.getpid():
        return False  # 자기 자신은 죽이지 않는다 (구성 오류 방어)
    logger.warning("포트 %d를 이전 Plugin Cafe 서버(pid %d)가 점유 — "
                   "종료 후 인계합니다 (§12.5)", port, pid)
    start = clock()
    try:
        kill(pid, signal.SIGTERM)
    except PermissionError:
        logger.warning("pid %d 종료 권한 없음 — 인계 포기", pid)
        return False
    except OSError:
        # 이미 죽음 — POSIX는 ProcessLookupError(ESRCH), Windows는
        # WinError 87(EINVAL)의 일반 OSError로 온다. 포트 해제만 대기.
        pass
    if _wait_port_free(port, start + deadline * _TERM_SHARE,
                       busy, sleep, clock):
        return True
    if hasattr(signal, "SIGKILL"):
        try:
            kill(pid, signal.SIGKILL)
        except OSError:  # 권한·이미 죽음 — 아래 재실측이 결론
            pass
    return _wait_port_free(port, start + deadline, busy, sleep, clock)
