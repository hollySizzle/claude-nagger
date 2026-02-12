"""task_spawn_guard_hook.py のテスト"""

import json
import os
import pytest
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.hooks.task_spawn_guard_hook import (
    TaskSpawnGuardHook,
    DEFAULT_BLOCKED_PREFIX,
    DEFAULT_BLOCK_REASON_TEMPLATE,
)


@pytest.fixture
def hook():
    """テスト用フックインスタンス（デフォルト設定）"""
    with patch(
        "src.domain.hooks.task_spawn_guard_hook.ConfigManager"
    ) as mock_cm:
        mock_cm.return_value.config = {}
        h = TaskSpawnGuardHook(debug=False)
    return h


@pytest.fixture
def hook_disabled():
    """無効化設定のフックインスタンス"""
    with patch(
        "src.domain.hooks.task_spawn_guard_hook.ConfigManager"
    ) as mock_cm:
        mock_cm.return_value.config = {
            "task_spawn_guard": {"enabled": False}
        }
        h = TaskSpawnGuardHook(debug=False)
    return h


@pytest.fixture
def hook_with_config():
    """カスタム設定付きフックインスタンスを生成するファクトリ"""
    def _factory(guard_config: dict):
        with patch(
            "src.domain.hooks.task_spawn_guard_hook.ConfigManager"
        ) as mock_cm:
            mock_cm.return_value.config = {"task_spawn_guard": guard_config}
            h = TaskSpawnGuardHook(debug=False)
        return h
    return _factory


# === is_target_tool テスト ===

class TestIsTargetTool:
    """is_target_tool メソッドのテスト"""

    def test_task_returns_true(self, hook):
        """Taskツールの場合True"""
        assert hook.is_target_tool("Task") is True

    def test_other_tool_returns_false(self, hook):
        """他ツールの場合False"""
        assert hook.is_target_tool("SendMessage") is False
        assert hook.is_target_tool("Read") is False
        assert hook.is_target_tool("Edit") is False

    def test_case_sensitive(self, hook):
        """大文字小文字を区別する"""
        assert hook.is_target_tool("task") is False
        assert hook.is_target_tool("TASK") is False


# === is_blocked_subagent_type テスト ===

class TestIsBlockedSubagentType:
    """is_blocked_subagent_type メソッドのテスト"""

    def test_ticket_tasuki_prefix_blocked(self, hook):
        """ticket-tasuki:で始まるsubagent_typeはブロック対象"""
        assert hook.is_blocked_subagent_type("ticket-tasuki:coder") is True
        assert hook.is_blocked_subagent_type("ticket-tasuki:scribe") is True
        assert hook.is_blocked_subagent_type("ticket-tasuki:tester") is True
        assert hook.is_blocked_subagent_type("ticket-tasuki:researcher") is True

    def test_non_prefixed_allowed(self, hook):
        """ticket-tasuki:以外のsubagent_typeはブロック対象外"""
        assert hook.is_blocked_subagent_type("coder") is False
        assert hook.is_blocked_subagent_type("Explore") is False
        assert hook.is_blocked_subagent_type("Plan") is False
        assert hook.is_blocked_subagent_type("") is False

    def test_partial_prefix_not_blocked(self, hook):
        """部分一致はブロックしない"""
        assert hook.is_blocked_subagent_type("ticket-tasuki") is False
        assert hook.is_blocked_subagent_type("ticket") is False

    def test_custom_prefix(self, hook_with_config):
        """カスタムプレフィックス設定"""
        h = hook_with_config({"blocked_prefix": "custom-plugin:"})
        assert h.is_blocked_subagent_type("custom-plugin:coder") is True
        assert h.is_blocked_subagent_type("ticket-tasuki:coder") is False


# === has_team_name テスト ===

class TestHasTeamName:
    """has_team_name メソッドのテスト"""

    def test_team_name_present(self, hook):
        """team_nameが指定されている場合True"""
        assert hook.has_team_name({"team_name": "my-team"}) is True
        assert hook.has_team_name({"team_name": "issue-6093"}) is True

    def test_team_name_empty(self, hook):
        """team_nameが空の場合False"""
        assert hook.has_team_name({"team_name": ""}) is False

    def test_team_name_whitespace(self, hook):
        """team_nameが空白のみの場合False"""
        assert hook.has_team_name({"team_name": "  "}) is False

    def test_team_name_absent(self, hook):
        """team_nameが未指定の場合False"""
        assert hook.has_team_name({}) is False
        assert hook.has_team_name({"subagent_type": "coder"}) is False


# === should_process テスト ===

class TestShouldProcess:
    """should_process メソッドのテスト"""

    def test_task_tool(self, hook):
        """Taskツールの場合True"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"}
        }
        assert hook.should_process(input_data) is True

    def test_non_task_tool(self, hook):
        """Task以外のツールの場合False"""
        input_data = {
            "tool_name": "SendMessage",
            "tool_input": {}
        }
        assert hook.should_process(input_data) is False

    def test_empty_tool_name(self, hook):
        """tool_name未指定の場合False"""
        input_data = {"tool_input": {}}
        assert hook.should_process(input_data) is False

    def test_task_with_normal_subagent(self, hook):
        """Taskツール+通常subagent_typeの場合もTrueを返す（processで判定）"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "coder"}
        }
        assert hook.should_process(input_data) is True

    def test_disabled_returns_false(self, hook_disabled):
        """enabled=falseの場合はFalse"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"}
        }
        assert hook_disabled.should_process(input_data) is False


# === process テスト ===

class TestProcess:
    """process メソッドのテスト"""

    def test_block_ticket_tasuki_without_team_name(self, hook):
        """ticket-tasuki:coder + team_nameなし → ブロック"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"}
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "ticket-tasuki:coder" in result["reason"]

    def test_block_ticket_tasuki_scribe_without_team_name(self, hook):
        """ticket-tasuki:scribe + team_nameなし → ブロック"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:scribe"}
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"

    def test_approve_ticket_tasuki_with_team_name(self, hook):
        """ticket-tasuki:coder + team_nameあり → 許可（Agent Teams経由）"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "ticket-tasuki:coder",
                "team_name": "issue-6093"
            }
        }
        result = hook.process(input_data)
        assert result["decision"] == "approve"
        assert result["reason"] == ""

    def test_approve_ticket_tasuki_scribe_with_team_name(self, hook):
        """ticket-tasuki:scribe + team_nameあり → 許可"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "ticket-tasuki:scribe",
                "team_name": "my-team"
            }
        }
        result = hook.process(input_data)
        assert result["decision"] == "approve"

    def test_block_ticket_tasuki_with_empty_team_name(self, hook):
        """ticket-tasuki:coder + team_name空 → ブロック"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "ticket-tasuki:coder",
                "team_name": ""
            }
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"

    def test_block_ticket_tasuki_with_whitespace_team_name(self, hook):
        """ticket-tasuki:coder + team_name空白のみ → ブロック"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "ticket-tasuki:coder",
                "team_name": "   "
            }
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"

    def test_approve_normal_subagent(self, hook):
        """通常のsubagent_typeは許可"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "coder"}
        }
        result = hook.process(input_data)
        assert result["decision"] == "approve"
        assert result["reason"] == ""

    def test_approve_explore(self, hook):
        """Exploreは許可"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "Explore"}
        }
        result = hook.process(input_data)
        assert result["decision"] == "approve"

    def test_approve_empty_subagent_type(self, hook):
        """subagent_type未指定は許可"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {}
        }
        result = hook.process(input_data)
        assert result["decision"] == "approve"

    def test_block_reason_contains_instructions(self, hook):
        """ブロック理由にAgent Teams誘導メッセージを含む"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"}
        }
        result = hook.process(input_data)
        assert "Agent Teams" in result["reason"]
        assert "team_name" in result["reason"]


# === ブロックメッセージカスタマイズテスト ===

class TestBlockMessageCustomization:
    """block_message カスタマイズのテスト"""

    def test_custom_block_message(self, hook_with_config):
        """カスタムblock_messageテンプレート"""
        h = hook_with_config({
            "block_message": "禁止: {subagent_type} は使用できません"
        })
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"}
        }
        result = h.process(input_data)
        assert result["decision"] == "block"
        assert result["reason"] == "禁止: ticket-tasuki:coder は使用できません"

    def test_default_block_message_fallback(self, hook):
        """デフォルトblock_messageテンプレートへのフォールバック"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"}
        }
        result = hook.process(input_data)
        assert "Task spawn規約" in result["reason"]


# === デフォルト定数テスト ===

class TestDefaults:
    """デフォルト定数のテスト"""

    def test_default_blocked_prefix(self):
        """デフォルトのブロックプレフィックス"""
        assert DEFAULT_BLOCKED_PREFIX == "ticket-tasuki:"

    def test_default_template_contains_agent_teams(self):
        """デフォルトテンプレートにAgent Teams誘導を含む"""
        assert "Agent Teams" in DEFAULT_BLOCK_REASON_TEMPLATE
        assert "team_name" in DEFAULT_BLOCK_REASON_TEMPLATE

    def test_template_format(self):
        """テンプレートのフォーマットが正しい"""
        formatted = DEFAULT_BLOCK_REASON_TEMPLATE.format(
            subagent_type="ticket-tasuki:coder"
        )
        assert "ticket-tasuki:coder" in formatted
