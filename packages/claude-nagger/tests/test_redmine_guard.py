"""redmine_guard.py のテスト

ticket-tasuki プラグインの PreToolUse hook スクリプトを
subprocess経由で呼び出し、Redmine操作の許可・ブロックを検証する。
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


def _make_redmine_input(tool_name: str) -> dict:
    """PreToolUse Redmineツール入力データを生成"""
    return {
        "session_id": "test-session-001",
        "transcript_path": "/tmp/test_transcript.jsonl",
        "cwd": "/workspace",
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {},
        "tool_use_id": "toolu_test_001",
    }


class TestAllowedTools:
    """許可リストのRedmineツールが通過すること"""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "mcp__redmine_epic_grid__get_issue_detail_tool",
            "mcp__redmine_epic_grid__list_epics_tool",
            "mcp__redmine_epic_grid__list_versions_tool",
            "mcp__redmine_epic_grid__list_user_stories_tool",
            "mcp__redmine_epic_grid__list_statuses_tool",
            "mcp__redmine_epic_grid__list_project_members_tool",
            "mcp__redmine_epic_grid__get_project_structure_tool",
            "mcp__redmine_epic_grid__add_issue_comment_tool",
            "mcp__redmine_epic_grid__update_issue_subject_tool",
            "mcp__redmine_epic_grid__update_issue_description_tool",
        ],
    )
    def test_allowed_tool_passes(self, tool_name):
        """許可リスト内のツールは出力なし（許可）"""
        data = _make_redmine_input(tool_name)
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None


class TestBlockedTools:
    """ブロック対象のRedmineツールがブロックされること"""

    @pytest.mark.parametrize(
        "tool_name",
        [
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
        ],
    )
    def test_blocked_tool_denied(self, tool_name):
        """ブロック対象ツールはdenyされる"""
        data = _make_redmine_input(tool_name)
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        decision = out["hookSpecificOutput"]["permissionDecision"]
        assert decision == "deny"

    def test_block_message_contains_tool_name(self):
        """ブロックメッセージに検出されたツール名が含まれる"""
        tool = "mcp__redmine_epic_grid__create_task_tool"
        data = _make_redmine_input(tool)
        rc, out = _run_guard(data)

        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert tool in reason

    def test_block_message_contains_scribe_guidance(self):
        """ブロックメッセージにscribe委譲の案内が含まれる"""
        data = _make_redmine_input("mcp__redmine_epic_grid__create_epic_tool")
        rc, out = _run_guard(data)

        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "scribe" in reason

    def test_block_message_has_nagger_prefix(self):
        """ブロックメッセージに[claude-nagger]プレフィックスがある (#6100準拠)"""
        data = _make_redmine_input("mcp__redmine_epic_grid__create_epic_tool")
        rc, out = _run_guard(data)

        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason.startswith("[claude-nagger]")


class TestNonRedmineTools:
    """Redmine以外のツールがスルーされること"""

    @pytest.mark.parametrize(
        "tool_name",
        [
            "Read",
            "Edit",
            "Bash",
            "Task",
            "Write",
            "Glob",
            "Grep",
            "mcp__serena__find_symbol",
            "mcp__ide__getDiagnostics",
        ],
    )
    def test_non_redmine_tool_passes(self, tool_name):
        """Redmine以外のツールは無条件で許可"""
        data = _make_redmine_input(tool_name)
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None


class TestEdgeCases:
    """不正入力時にエラーにならずスルーすること"""

    def test_invalid_json_input(self):
        """不正なJSON入力は許可（exit 0）"""
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
        """空入力は許可"""
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
        """tool_nameが存在しない場合は許可"""
        data = {
            "session_id": "test-session",
            "hook_event_name": "PreToolUse",
            "tool_input": {},
        }
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_empty_tool_name(self):
        """tool_nameが空文字の場合は許可"""
        data = _make_redmine_input("")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None
