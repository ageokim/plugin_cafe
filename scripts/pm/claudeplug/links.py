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


def _inside(path: Path, ancestor: Path) -> bool:
    """path(resolve)가 ancestor 아래인지 — 컴포넌트 링크 소유 판정 (§6.2)."""
    try:
        resolved = path.resolve()
        root = ancestor.resolve()
    except OSError:
        return False
    return root == resolved or root in resolved.parents


def component_root(clone_dir: Path) -> Path:
    """컴포넌트 탐색 기준 — 사내 표준 ``plugin/`` 폴더, 없으면 repo 루트
    (부록 A.2)."""
    nested = clone_dir / "plugin"
    return nested if nested.is_dir() else clone_dir


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
        """이 clone을 가리키는 링크명 — 없으면 None.

        링크명은 매니페스트 name일 수 있으므로(§6.2) 후보를 추측하지 않고
        plugin_roots 전체를 타깃 기준으로 스캔한다 (실측 원칙 §6.4).
        """
        roots = self._paths.plugin_roots_dir
        if not roots.is_dir():
            return None
        clone = self._paths.plugin_clone_dir(org, name)
        for link in roots.iterdir():
            if _points_to(link, clone):
                return link.name
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
    def enable(self, org: str, name: str,
               preferred: Optional[str] = None) -> str:
        """링크 2개 생성(멱등) → 링크명 반환 (§6.2 충돌 규칙).

        Args:
            preferred: 매니페스트 name (§6.2 — 없으면 repo명 사용).

        Raises:
            RegistryError: clone 없음, 또는 충돌 해소 불가.
        """
        clone = self._paths.plugin_clone_dir(org, name)
        if not clone.is_dir():
            raise RegistryError(
                f"clone 없음: {org}/{name} — pm install 먼저 (§6.4)")
        link_name = self.link_name_for(org, name)
        if link_name is None:
            link_name = self._pick_link_name(org, preferred or name, clone)
        for base, relative in ((self._paths.plugin_roots_dir, True),
                               (self._paths.plugin_links_dir, False)):
            self._make_link(base / link_name, clone, relative=relative)
        return link_name

    def disable(self, org: str, name: str) -> Optional[str]:
        """이 clone을 가리키는 링크 전부 제거 — root 2개 + 컴포넌트 (§6.2).
        링크가 없었으면 None (멱등)."""
        self.disable_components(org, name)
        link_name = self.link_name_for(org, name)
        if link_name is None:
            return None
        for base in (self._paths.plugin_roots_dir,
                     self._paths.plugin_links_dir):
            self._remove_link(base / link_name)
        return link_name

    def remove_dangling(self) -> List[str]:
        """깨진 링크 정리 — 제거한 링크명 목록 (repair §6.4).
        root 링크 2종 + 컴포넌트 링크 디렉토리 전부를 훑는다."""
        removed = []
        for link_name in self.dangling():
            for base in (self._paths.plugin_roots_dir,
                         self._paths.plugin_links_dir):
                self._remove_link(base / link_name)
            removed.append(link_name)
        for base in self._component_bases():
            if not base.is_dir():
                continue
            for link in list(base.iterdir()):
                if not os.path.islink(str(link)):
                    continue
                try:
                    broken = not link.resolve().exists()
                except OSError:
                    broken = True
                if broken:
                    self._remove_link(link)
                    removed.append(f"{base.name}/{link.name}")
        return removed

    # ── 컴포넌트 링크 (§6.2 4단계 — standalone 전용) ─────────
    def enable_components(self, org: str, name: str,
                          link_name: str) -> List[str]:
        """plugin이 가진 컴포넌트만 골라 `.claude/` 아래로 링크한다.

        commands·workflows = 파일 단위 flat 링크(재귀 미보장 대응),
        skills = SKILL.md 보유 디렉토리 링크(공식 지원). 이름 충돌 시
        신규만 ``{링크명}-{이름}`` — 기존은 불변 (§6.2).

        Returns:
            생성한 링크의 표시 목록 (예: ``commands/hello.md``).
        """
        clone = self._paths.plugin_clone_dir(org, name)
        comp = component_root(clone)
        created: List[str] = []
        cmd_dir = comp / "commands"
        if cmd_dir.is_dir():
            for src in sorted(cmd_dir.glob("*.md")):
                created += self._link_component(
                    self._paths.claude_commands_dir, src, src.name,
                    link_name, is_dir=False)
        skills_dir = comp / "skills"
        if skills_dir.is_dir():
            for src in sorted(skills_dir.iterdir()):
                if src.is_dir() and (src / "SKILL.md").is_file():
                    created += self._link_component(
                        self._paths.claude_skills_dir, src, src.name,
                        link_name, is_dir=True)
        wf_dir = comp / "workflows"
        if wf_dir.is_dir():
            for src in sorted(wf_dir.iterdir()):
                if src.is_file():
                    created += self._link_component(
                        self._paths.claude_workflows_dir, src, src.name,
                        link_name, is_dir=False)
        return created

    def disable_components(self, org: str, name: str) -> List[str]:
        """이 clone 안을 가리키는 컴포넌트 링크 전부 제거 — 실측 스캔.

        Windows 파일 컴포넌트는 하드링크라 islink로 안 잡힌다 —
        clone 쪽 파일과 inode 대조(samefile 의미론)로 소유를 판정한다.
        """
        clone = self._paths.plugin_clone_dir(org, name)
        clone_inodes = self._file_inodes(component_root(clone)) \
            if self._windows else set()
        removed: List[str] = []
        for base in self._component_bases():
            if not base.is_dir():
                continue
            for link in list(base.iterdir()):
                owned = os.path.islink(str(link)) and _inside(link, clone)
                if not owned and self._windows and link.is_file():
                    try:
                        stat = link.stat()
                        owned = (stat.st_dev, stat.st_ino) in clone_inodes
                    except OSError:
                        owned = False
                if owned:
                    self._remove_link(link)
                    removed.append(f"{base.name}/{link.name}")
        return removed

    @staticmethod
    def _file_inodes(comp: Path) -> set:
        inodes = set()
        for sub in ("commands", "workflows"):
            directory = comp / sub
            if not directory.is_dir():
                continue
            for src in directory.iterdir():
                if src.is_file():
                    try:
                        stat = src.stat()
                        inodes.add((stat.st_dev, stat.st_ino))
                    except OSError:
                        pass
        return inodes

    def resync_components(self, org: str, name: str,
                          link_name: str) -> List[str]:
        """update 후 재동기화 — 파일 추가·삭제 반영 (§6.2)."""
        self.disable_components(org, name)
        return self.enable_components(org, name, link_name)

    def _component_bases(self) -> List[Path]:
        return [self._paths.claude_commands_dir,
                self._paths.claude_skills_dir,
                self._paths.claude_workflows_dir]

    def _link_component(self, base: Path, src: Path, item_name: str,
                        link_name: str, is_dir: bool) -> List[str]:
        """항목 하나 링크 — 이미 나를 가리키면 멱등, 남이 쓰면 접두 폴백."""
        for candidate in (item_name, f"{link_name}-{item_name}"):
            link = base / candidate
            if _points_to(link, src):
                return [f"{base.name}/{candidate}"]  # 멱등
            if link.exists() or os.path.islink(str(link)):
                continue  # 남이 소유 — 접두 후보로
            base.mkdir(parents=True, exist_ok=True)
            if self._windows and not is_dir:
                # 파일은 junction 불가 → 하드링크 (같은 볼륨 전제,
                # pull 후 stale — update의 resync가 해소 §6.2)
                os.link(str(src), str(link))
            else:
                self._make_link(link, src, relative=True)
            return [f"{base.name}/{candidate}"]
        logger_name = f"{base.name}/{item_name}"
        raise RegistryError(f"컴포넌트 링크명 충돌 해소 불가: {logger_name}")

    # ── 내부 ─────────────────────────────────────────────────
    def _pick_link_name(self, org: str, name: str, clone: Path) -> str:
        """기본은 매니페스트 name(→repo명) — 소유 중이면 {org}-{name} (§6.2).
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
        if self._windows and link.is_file():
            os.unlink(str(link))  # 하드링크 제거 — 원본 inode 유지
            return
        raise RegistryError(
            f"링크가 아닌 경로 — 수동 확인 필요 (rmtree 금지 §6.2): {link}")
