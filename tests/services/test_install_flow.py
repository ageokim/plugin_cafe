"""설치→활성→비활성→삭제 전 흐름 + 충돌·되감기·보존 (§6.2·§6.4)."""

from __future__ import annotations

import pytest

from pm.errors import GitOpsError, PmError, RegistryError
from pm.models import PluginState


def test_full_lifecycle(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")

    def state():
        return env.activation_service.state("org-a", "plugin-a")

    assert state() is PluginState.AVAILABLE

    result = env.install_service.install(plugin)
    assert result.entry_name == "plugin-a"
    assert env.paths.plugin_clone_dir("org-a", "plugin-a").is_dir()
    assert state() is PluginState.ENABLED  # install = clone+등록+활성 (§6.2)

    env.activation_service.disable("org-a", "plugin-a")
    assert state() is PluginState.INSTALLED

    env.activation_service.enable("org-a", "plugin-a")
    assert state() is PluginState.ENABLED

    env.install_service.uninstall("org-a", "plugin-a")
    assert state() is PluginState.AVAILABLE
    assert not env.paths.plugin_clone_dir("org-a", "plugin-a").exists()
    assert env.registry.registered() == {}
    assert env.settings_store.read().get("enabledPlugins", {}) == {}


def test_install_no_enable(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    result = env.install_service.install(plugin, enable=False)
    assert result.enabled is False
    assert (env.activation_service.state("org-a", "plugin-a")
            is PluginState.INSTALLED)


def test_install_native_violation_rolls_back(env):
    """native형(plugin.json 보유)인데 name이 없으면 설치 차단·되감기 (부록 A.3)."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "bad-plugin")
    env.git.broken_native = True  # plugin.json은 있으나 name 없음
    with pytest.raises(RegistryError):
        env.install_service.install(plugin)
    assert not env.paths.plugin_clone_dir("org-a", "bad-plugin").exists()
    assert env.registry.registered() == {}  # 부분 산출물 없음 (§6.2)
    assert not env.links.is_enabled("org-a", "bad-plugin")


def test_install_standalone_without_manifest(env):
    """plugin.json 없는 사내형 repo도 설치된다 — 링크 2개 생성 (부록 A.2)."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "inhouse")
    env.git.valid_plugin = False  # 맨 repo (standalone)
    result = env.install_service.install(plugin)
    assert result.profile == "standalone"
    assert env.registry.registered() == {}  # native 등록 없음
    clone = env.paths.plugin_clone_dir("org-a", "inhouse")
    root_link = env.paths.plugin_roots_dir / "inhouse"
    abs_link = env.paths.plugin_links_dir / "inhouse"
    assert root_link.resolve() == clone.resolve()  # 사내 관례 1번 (§6.2)
    assert abs_link.resolve() == clone.resolve()  # 2번 — 절대경로판
    import os
    assert not os.path.isabs(os.readlink(str(root_link)))  # 1번은 상대
    assert os.path.isabs(os.readlink(str(abs_link)))


def test_install_clone_failure_propagates(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.git.fail_urls.add(plugin.clone_url)
    with pytest.raises(GitOpsError):
        env.install_service.install(plugin)
    assert env.registry.registered() == {}


def test_install_twice_raises(env):
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    with pytest.raises(PmError):
        env.install_service.install(plugin)


def test_name_collision_keeps_first_entry(env):
    env.login_and_register_org("org-a")
    env.register_extra_org("org-b")
    first = env.catalog_plugin("org-a", "plugin-a")
    second = env.catalog_plugin("org-b", "plugin-a")

    first_result = env.install_service.install(first)
    second_result = env.install_service.install(second)
    assert first_result.entry_name == "plugin-a"
    assert second_result.entry_name == "org-b-plugin-a"  # 신규만 접두 (§6.2)
    enabled = env.settings_store.read()["enabledPlugins"]
    assert enabled == {
        "plugin-a@plugin-market": True,
        "org-b-plugin-a@plugin-market": True,
    }
    # 첫 항목 삭제해도 둘째는 무관
    env.install_service.uninstall("org-a", "plugin-a")
    assert (env.activation_service.state("org-b", "plugin-a")
            is PluginState.ENABLED)


def test_uninstall_not_installed_raises(env):
    with pytest.raises(PmError):
        env.install_service.uninstall("org-a", "ghost")


def test_update_preserves_disabled_state(env):
    """§6.2 — 꺼진 플러그인은 꺼진 채 새 버전이 된다."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "plugin-a")
    env.install_service.install(plugin)
    env.activation_service.disable("org-a", "plugin-a")

    head = env.install_service.update("org-a", "plugin-a")
    assert head == "abc1234"
    assert ("pull", str(env.paths.plugin_clone_dir("org-a", "plugin-a"))) in (
        env.git.calls)
    assert (env.activation_service.state("org-a", "plugin-a")
            is PluginState.INSTALLED)  # 활성 상태 보존


def test_update_not_installed_raises(env):
    with pytest.raises(PmError):
        env.install_service.update("org-a", "ghost")


def test_enable_not_installed_raises(env):
    with pytest.raises(RegistryError):
        env.activation_service.enable("org-a", "ghost")


def test_install_inhouse_standard_structure(env):
    """사내 표준 구조(plugin/ 폴더) repo — 무경고 설치, 링크명=매니페스트 name."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "inhouse-std")
    env.git.valid_plugin = False
    env.git.inhouse_plugin = True
    result = env.install_service.install(plugin)
    assert result.profile == "standalone"
    assert result.warnings == ()  # 표준 준수 — 권장 경고 없음
    assert (env.paths.plugin_roots_dir / "inhouse-std").resolve() == \
        env.paths.plugin_clone_dir("org-a", "inhouse-std").resolve()


def test_install_inhouse_manifest_name_becomes_link_name(env):
    """plugin/plugin.json의 name ≠ repo명이면 링크명은 매니페스트를 따른다 (§6.2)."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "repo-x")
    env.git.valid_plugin = False
    env.git.inhouse_plugin = True
    env.git.inhouse_name = "실제도구명"
    result = env.install_service.install(plugin)
    assert result.entry_name == "실제도구명"
    assert (env.paths.plugin_roots_dir / "실제도구명").resolve() == \
        env.paths.plugin_clone_dir("org-a", "repo-x").resolve()
    assert any("≠ repo명" in w for w in result.warnings)  # 불일치 권장 경고
    # 상태 실측도 매니페스트 링크명으로 동작 (타깃 스캔 §6.4)
    from pm.models import PluginState
    assert env.activation_service.state("org-a", "repo-x") \
        is PluginState.ENABLED
    env.activation_service.disable("org-a", "repo-x")
    assert not (env.paths.plugin_roots_dir / "실제도구명").exists()


def test_install_bare_repo_warns_structure(env):
    """맨 repo(사내 구조도 없음)는 설치되되 권장 경고 (부록 A.2)."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "bare")
    env.git.valid_plugin = False
    result = env.install_service.install(plugin)
    assert result.profile == "standalone"
    assert any("사내 표준 구조 미보유" in w for w in result.warnings)


def test_install_inhouse_links_components(env):
    """§6.2 4단계 — commands·skills·workflows가 .claude/ 아래로 링크된다."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "toolkit")
    env.git.valid_plugin = False
    env.git.inhouse_plugin = True
    env.install_service.install(plugin)
    clone = env.paths.plugin_clone_dir("org-a", "toolkit")
    cmd = env.paths.claude_commands_dir / "hello.md"
    skill = env.paths.claude_skills_dir / "greet"
    wf = env.paths.claude_workflows_dir / "flow.js"
    assert cmd.resolve() == (clone / "plugin/commands/hello.md").resolve()
    assert (skill / "SKILL.md").is_file()  # 디렉토리 링크 경유 접근
    assert wf.resolve() == (clone / "plugin/workflows/flow.js").resolve()


def test_disable_removes_component_links_only_own(env):
    """끄기는 자기 컴포넌트 링크만 제거 — 남의 것·원본은 불변."""
    env.login_and_register_org("org-a")
    p1 = env.catalog_plugin("org-a", "tool-1")
    env.git.valid_plugin = False
    env.git.inhouse_plugin = True
    env.install_service.install(p1)
    # 두 번째 plugin — 같은 hello.md 이름 → 접두 폴백
    p2 = env.catalog_plugin("org-a", "tool-2")
    env.install_service.install(p2)
    prefixed = env.paths.claude_commands_dir / "tool-2-hello.md"
    assert prefixed.exists()  # 충돌 → {링크명}-{이름} (§6.2)

    env.activation_service.disable("org-a", "tool-1")
    assert not (env.paths.claude_commands_dir / "hello.md").exists()
    assert prefixed.exists()  # tool-2 것은 그대로
    assert (env.paths.plugin_clone_dir("org-a", "tool-1") /
            "plugin/commands/hello.md").is_file()  # 원본 무손상

    # 다시 켜면 컴포넌트도 복원
    env.activation_service.enable("org-a", "tool-1")
    assert (env.paths.claude_commands_dir / "hello.md").exists()


def test_update_resyncs_components(env):
    """update가 컴포넌트 링크를 재동기화 — 새 파일 반영·삭제 파일 정리."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "toolkit")
    env.git.valid_plugin = False
    env.git.inhouse_plugin = True
    env.install_service.install(plugin)
    clone = env.paths.plugin_clone_dir("org-a", "toolkit")
    (clone / "plugin/commands/hello.md").unlink()  # pull이 지웠다고 가정
    (clone / "plugin/commands/new-cmd.md").write_text("새 명령",
                                                      encoding="utf-8")
    env.install_service.update("org-a", "toolkit")
    assert not (env.paths.claude_commands_dir / "hello.md").exists()
    assert (env.paths.claude_commands_dir / "new-cmd.md").exists()


def test_native_profile_gets_no_component_links(env):
    """native는 marketplace가 로딩 — 컴포넌트 링크 없음(중복 방지 §6.2)."""
    env.login_and_register_org("org-a")
    plugin = env.catalog_plugin("org-a", "native-p")
    env.install_service.install(plugin)  # valid_plugin=True → native
    assert not env.paths.claude_commands_dir.exists() or \
        not any(env.paths.claude_commands_dir.iterdir())
