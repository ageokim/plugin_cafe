"""pm.gitops 테스트 — env 구성 단위 + 로컬 git 통합(네트워크 없음)."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess

import pytest

from pm.errors import GitOpsError
from pm.gitops import SubprocessGitRunner, build_git_env, remove_repo_dir

_GIT = shutil.which("git")


def test_build_git_env_with_token():
    env = build_git_env("ghp_secret", base_env={})
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.extraheader"
    assert env["GIT_CONFIG_VALUE_0"].startswith("Authorization: basic ")
    assert "ghp_secret" not in env["GIT_CONFIG_VALUE_0"]  # b64 인코딩됨


def test_build_git_env_without_token():
    env = build_git_env(None, base_env={})
    assert env["GIT_CONFIG_COUNT"] == "0"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_build_git_env_with_ca_bundle():
    env = build_git_env("t", ca_bundle="/etc/ca.pem", base_env={})
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert env["GIT_CONFIG_KEY_1"] == "http.sslCAInfo"
    assert env["GIT_CONFIG_VALUE_1"] == "/etc/ca.pem"


def test_remove_repo_dir_handles_readonly(tmp_path):
    repo = tmp_path / "clone"
    (repo / ".git").mkdir(parents=True)
    locked = repo / ".git" / "object"
    locked.write_text("x", encoding="utf-8")
    locked.chmod(stat.S_IREAD)
    remove_repo_dir(repo)
    assert not repo.exists()


def test_remove_repo_dir_missing_is_noop(tmp_path):
    remove_repo_dir(tmp_path / "nope")


@pytest.mark.skipif(_GIT is None, reason="git 미설치")
class TestSubprocessGitRunnerIntegration:
    """로컬 file:// repo 상대 통합 — 네트워크·토큰 불필요."""

    @pytest.fixture
    def source_repo(self, tmp_path):
        """커밋 1개가 있는 로컬 원본 repo."""
        source = tmp_path / "source"
        source.mkdir()
        env = dict(os.environ,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")

        def _run(*args):
            subprocess.run(["git", "-C", str(source)] + list(args),
                           check=True, capture_output=True, env=env)

        subprocess.run(["git", "init", "-q", str(source)], check=True,
                       capture_output=True)
        (source / "README.md").write_text("v1", encoding="utf-8")
        _run("add", ".")
        _run("commit", "-q", "-m", "c1")
        return source

    @pytest.fixture
    def runner(self):
        return SubprocessGitRunner(token_provider=lambda: None)

    def test_clone_and_head(self, runner, source_repo, tmp_path):
        dest = tmp_path / "plugins" / "org-a" / "repo"
        runner.clone(f"file://{source_repo}", dest)
        assert (dest / "README.md").read_text(encoding="utf-8") == "v1"
        head = runner.head_commit(dest)
        assert len(head) == 40

    def test_pull_updates(self, runner, source_repo, tmp_path):
        dest = tmp_path / "clone"
        runner.clone(f"file://{source_repo}", dest)
        (source_repo / "README.md").write_text("v2", encoding="utf-8")
        env = dict(os.environ,
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        subprocess.run(["git", "-C", str(source_repo), "commit", "-aqm", "c2"],
                       check=True, capture_output=True, env=env)
        old_head = runner.head_commit(dest)
        runner.pull(dest)
        assert runner.head_commit(dest) != old_head
        assert (dest / "README.md").read_text(encoding="utf-8") == "v2"

    def test_clone_failure_raises(self, runner, tmp_path):
        with pytest.raises(GitOpsError):
            runner.clone(f"file://{tmp_path}/no-such-repo",
                         tmp_path / "dest")

    def test_head_on_non_repo_raises(self, runner, tmp_path):
        with pytest.raises(GitOpsError):
            runner.head_commit(tmp_path)
