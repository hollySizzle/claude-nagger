"""leader_constraint_guard.py チーム残骸削除除外パターンのテスト

ticket-tasuki プラグインの PreToolUse hook スクリプトを
subprocess経由で呼び出し、Bash rm コマンドの許可/拒否を検証する。
"""

import json
import os
import subprocess
import sys

import pytest

# テスト対象スクリプトのパス
GUARD_SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "..",
    ".claude",
    "plugins",
    "ticket-tasuki",
    "hooks",
    "leader_constraint_guard.py",
)
GUARD_SCRIPT = os.path.normpath(GUARD_SCRIPT)


def _run_guard(input_data: dict) -> tuple[int, dict | None]:
    """ガードスクリプトを実行し、(終了コード, stdout JSONまたはNone) を返す"""
    proc = subprocess.run(
        [sys.executable, GUARD_SCRIPT],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
    )
    stdout_json = None
    if proc.stdout.strip():
        try:
            stdout_json = json.loads(proc.stdout)
        except json.JSONDecodeError:
            pass
    return proc.returncode, stdout_json


def _make_bash_input(command: str, agent_context: str = "") -> dict:
    """PreToolUse Bash入力データを生成"""
    data = {
        "session_id": "test-session-001",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    if agent_context:
        data["agent_context"] = agent_context
    return data


class TestCleanupExclusionPattern:
    """A案: チーム残骸削除コマンドの除外パターン"""

    def test_allow_rm_teams_dir(self):
        """teams削除許可: rm -rf ~/.claude/teams/ は許可される"""
        data = _make_bash_input("rm -rf ~/.claude/teams/")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # 許可 = stdout出力なし

    def test_allow_rm_tasks_dir(self):
        """tasks削除許可: rm -rf ~/.claude/tasks/ は許可される"""
        data = _make_bash_input("rm -rf ~/.claude/tasks/")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_allow_rm_both_dirs(self):
        """両方削除許可: teams/とtasks/の同時削除は許可される"""
        data = _make_bash_input("rm -rf ~/.claude/teams/ ~/.claude/tasks/")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_allow_git_command(self):
        """gitコマンド許可: git statusは許可される（既存動作）"""
        data = _make_bash_input("git status")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_deny_rm_other_path(self):
        """他rmコマンド拒否: .claude/teams/tasks以外のrmは拒否される"""
        data = _make_bash_input("rm -rf /tmp/something")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_deny_other_bash_command(self):
        """他Bashコマンド拒否: ls -la は拒否される"""
        data = _make_bash_input("ls -la")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_subagent_allows_any_command(self):
        """subagentはスキップ: agent_context=subagentなら任意コマンドが許可される"""
        data = _make_bash_input("ls -la", agent_context="subagent")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None
