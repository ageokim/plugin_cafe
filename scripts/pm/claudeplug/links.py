"""설치 링크 관리 — 링크 1급 모델의 핵심 (Architecture.md §6.2).

사내 규약의 링크 2개를 다룬다:
- ``.claude/plugin_roots/{링크명}`` → clone (POSIX는 상대경로) — plugin이
  자기 root를 해석하는 경로.
- ``.claude/plugins/{링크명}`` → clone **절대경로**.

POSIX는 symlink, Windows는 디렉토리 junction(관리자 불필요, 절대경로
전용 — 두 링크 모두 절대로 만든다). 제거는 **링크 자체만** 지운다 —
링크 경로에 rmtree 금지(원본 삭제 사고, §6.2 안전 규칙).
"""

from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

from pm.errors import RegistryError
from pm.paths import ProjectPaths


def _points_to(link: Path, target: Path) -> bool:
    """링크가 target을 가리키는지 — resolve 비교 (상대/절대/junction 불문)."""
    try:
        return link.resolve() == target.resolve()
    except OSError:
        return False


class PluginLinks:
    """링크 생성·제거·실측 (§6.2 — 상태 판정의 진실 §6.4).

    Args:
        paths: ProjectPaths.
        system: 테스트 주입용 platform.system 대체물.
    """

    def __init__(self, paths: ProjectPaths,
                 system: Callable[[], str] = platform.system) -> None:
        self._paths = paths
        self._windows = system() == "Windows"

    # ── 실측 ─────────────────────────────────────────────────
    def link_name_for(self, org: str, name: str) -> Optional[str]:
        """이 clone을 가리키는 링크명(name 또는 {org}-{name}) — 없으면 None."""
        clone = self._paths.plugin_clone_dir(org, name)
        for candidate in (name, f"{org}-{name}"):
            link = self._paths.plugin_roots_dir / candidate
            if _points_to(link, clone):
                return candidate
        return None

    def is_enabled(self, org: str, name: str) -> bool:
        return self.link_name_for(org, name) is not None

    def all_links(self) -> Dict[str, Path]:
        """plugin_roots의 전 링크 — {링크명: resolve된 타깃(소실 시 원경로)}."""
        roots = self._paths.plugin_roots_dir
        if not roots.is_dir():
            return {}
        result: Dict[str, Path] = {}
        for link in roots.iterdir():
            try:
                result[link.name] = link.resolve()
            except OSError:
                result[link.name] = link
        return result

    def dangling(self) -> List[str]:
        """타깃이 사라진 링크명 목록 (inspect --repair 대상)."""
        roots = self._paths.plugin_roots_dir
        if not roots.is_dir():
            return []
        return [link.name for link in roots.iterdir()
                if not link.resolve().exists()]

    # ── 생성·제거 ────────────────────────────────────────────
    def enable(self, org: str, name: str) -> str:
        """링크 2개 생성(멱등) → 링크명 반환 (§6.2 충돌 규칙).

        Raises:
            RegistryError: clone 없음, 또는 충돌 해소 불가.
        """
        clone = self._paths.plugin_clone_dir(org, name)
        if not clone.is_dir():
            raise RegistryError(
                f"clone 없음: {org}/{name} — pm install 먼저 (§6.4)")
        link_name = self.link_name_for(org, name)
        if link_name is None:
            link_name = self._pick_link_name(org, name, clone)
        for base, relative in ((self._paths.plugin_roots_dir, True),
                               (self._paths.plugin_links_dir, False)):
            self._make_link(base / link_name, clone, relative=relative)
        return link_name

    def disable(self, org: str, name: str) -> Optional[str]:
        """이 clone을 가리키는 링크 2개 제거 — 없었으면 None (멱등)."""
        link_name = self.link_name_for(org, name)
        if link_name is None:
            return None
        for base in (self._paths.plugin_roots_dir,
                     self._paths.plugin_links_dir):
            self._remove_link(base / link_name)
        return link_name

    def remove_dangling(self) -> List[str]:
        """깨진 링크 정리 — 제거한 링크명 목록 (repair §6.4)."""
        removed = []
        for link_name in self.dangling():
            for base in (self._paths.plugin_roots_dir,
                         self._paths.plugin_links_dir):
                self._remove_link(base / link_name)
            removed.append(link_name)
        return removed

    # ── 내부 ─────────────────────────────────────────────────
    def _pick_link_name(self, org: str, name: str, clone: Path) -> str:
        """기본 repo명 — 다른 clone이 소유 중이면 {org}-{name} (§6.2).
        먼저 설치된 쪽의 링크는 절대 리네임하지 않는다."""
        for candidate in (name, f"{org}-{name}"):
            link = self._paths.plugin_roots_dir / candidate
            if not link.exists() and not os.path.islink(str(link)):
                return candidate
            if _points_to(link, clone):
                return candidate
        raise RegistryError(f"링크명 충돌을 해소할 수 없습니다: {org}/{name}")

    def _make_link(self, link: Path, target: Path, relative: bool) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        if _points_to(link, target):
            return  # 멱등
        if link.exists() or os.path.islink(str(link)):
            raise RegistryError(f"링크 경로가 이미 사용 중: {link}")
        if self._windows:
            # junction — 관리자 불필요, 절대경로 전용 (§6.2)
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link),
                 str(target.resolve())],
                capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RegistryError(
                    f"junction 생성 실패: {link} — {result.stderr.strip()}")
            return
        source = (os.path.relpath(target, link.parent)
                  if relative else str(target.resolve()))
        os.symlink(source, str(link))

    def _remove_link(self, link: Path) -> None:
        """링크 자체만 제거 — 원본(clone)은 절대 건드리지 않는다 (§6.2)."""
        if os.path.islink(str(link)):
            os.unlink(str(link))
            return
        if not link.exists():
            return
        if self._windows and link.is_dir():
            os.rmdir(str(link))  # junction 제거 — 타깃 내용물 무손상
            return
        raise RegistryError(
            f"링크가 아닌 경로 — 수동 확인 필요 (rmtree 금지 §6.2): {link}")
