"""redmine_guard.py のテスト

ticket-tasuki プラグインの PreToolUse hook スクリプトを
subprocess経由で呼び出し、Redmine操作のブロック・許可を検証する。
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
    "redmine_guard.py",
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


def _make_input(tool_name: str) -> dict:
    """PreToolUse入力データを生成"""
    return {
        "session_id": "test-session-001",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {},
    }


class TestAllowedTools:
    """許可リストのツールが通過すること"""

    @pytest.mark.parametrize("tool_name", [
        "mcp__redmine_epic_grid__get_issue_detail_tool",
        "mcp__redmine_epic_grid__list_epics_tool",
        "mcp__redmine_epic_grid__list_versions_tool",
        "mcp__redmine_epic_grid__list_user_stories_tool",
        "mcp__redmine_epic_grid__list_statuses_tool",
        "mcp__redmine_epic_grid__list_project_members_tool",
        "mcp__redmine_epic_grid__get_project_structure_tool",
    ])
    def test_allow_read_tools(self, tool_name):
        """Read系ツールは許可"""
        rc, out = _run_guard(_make_input(tool_name))
        assert rc == 0
        assert out is None

    @pytest.mark.parametrize("tool_name", [
        "mcp__redmine_epic_grid__add_issue_comment_tool",
        "mcp__redmine_epic_grid__update_issue_subject_tool",
        "mcp__redmine_epic_grid__update_issue_description_tool",
    ])
    def test_allow_lightweight_write_tools(self, tool_name):
        """軽量Write系ツール（コメント・subject・description編集）は許可"""
        rc, out = _run_guard(_make_input(tool_name))
        assert rc == 0
        assert out is None


class TestBlockedTools:
    """ブロック対象のツールがブロックされること"""

    @pytest.mark.parametrize("tool_name", [
        "mcp__redmine_epic_grid__create_epic_tool",
        "mcp__redmine_epic_grid__create_feature_tool",
        "mcp__redmine_epic_grid__create_user_story_tool",
        "mcp__redmine_epic_grid__create_task_tool",
        "mcp__redmine_epic_grid__create_bug_tool",
        "mcp__redmine_epic_grid__create_test_tool",
        "mcp__redmine_epic_grid__create_version_tool",
        "mcp__redmine_epic_grid__update_issue_status_tool",
        "mcp__redmine_epic_grid__update_issue_parent_tool",
        "mcp__redmine_epic_grid__update_issue_assignee_tool",
        "mcp__redmine_epic_grid__update_custom_fields_tool",
        "mcp__redmine_epic_grid__update_issue_progress_tool",
        "mcp__redmine_epic_grid__assign_to_version_tool",
        "mcp__redmine_epic_grid__move_to_next_version_tool",
    ])
    def test_block_dangerous_tools(self, tool_name):
        """作成・ステータス変更等の操作はブロック"""
        rc, out = _run_guard(_make_input(tool_name))
        assert rc == 0
        assert out is not None
        hook_output = out["hookSpecificOutput"]
        assert hook_output["hookEventName"] == "PreToolUse"
        assert hook_output["permissionDecision"] == "deny"
        assert "[claude-nagger]" in hook_output["permissionDecisionReason"]
        assert "scribe" in hook_output["permissionDecisionReason"]

    def test_block_message_contains_tool_name(self):
        """ブロックメッセージに検出ツール名が含まれる"""
        tool = "mcp__redmine_epic_grid__create_task_tool"
        rc, out = _run_guard(_make_input(tool))
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert tool in reason


class TestNonRedmineTools:
    """Redmine以外のツールがスルーされること"""

    @pytest.mark.parametrize("tool_name", [
        "Read",
        "Edit",
        "Write",
        "Bash",
        "Task",
        "SendMessage",
        "mcp__serena__find_symbol",
        "mcp__ide__getDiagnostics",
    ])
    def test_non_redmine_tools_pass_through(self, tool_name):
        """Redmine以外のツールは何もせず通過"""
        rc, out = _run_guard(_make_input(tool_name))
        assert rc == 0
        assert out is None


class TestEdgeCases:
    """不正入力時のテスト"""

    def test_invalid_json_input(self):
        """不正なJSON入力はエラーにならず許可"""
        proc = subprocess.run(
            [sys.executable, GUARD_SCRIPT],
            input="invalid json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_empty_input(self):
        """空入力はエラーにならず許可"""
        proc = subprocess.run(
            [sys.executable, GUARD_SCRIPT],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_missing_tool_name(self):
        """tool_nameがない場合は許可"""
        rc, out = _run_guard({"session_id": "test", "tool_input": {}})
        assert rc == 0
        assert out is None

    def test_empty_tool_name(self):
        """tool_nameが空文字の場合は許可"""
        rc, out = _run_guard(_make_input(""))
        assert rc == 0
        assert out is None
