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
        """ticket-tasuki:で始まるsubagent_typeはブロック"""
        assert hook.is_blocked_subagent_type("ticket-tasuki:coder") is True
        assert hook.is_blocked_subagent_type("ticket-tasuki:scribe") is True
        assert hook.is_blocked_subagent_type("ticket-tasuki:tester") is True
        assert hook.is_blocked_subagent_type("ticket-tasuki:researcher") is True

    def test_non_prefixed_allowed(self, hook):
        """ticket-tasuki:以外のsubagent_typeは許可"""
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


# === process テスト ===

class TestProcess:
    """process メソッドのテスト"""

    def test_block_ticket_tasuki_coder(self, hook):
        """ticket-tasuki:coderをブロック"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"}
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "ticket-tasuki:coder" in result["reason"]

    def test_block_ticket_tasuki_scribe(self, hook):
        """ticket-tasuki:scribeをブロック"""
        input_data = {
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:scribe"}
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
        assert "TeamCreate" in result["reason"]


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
        assert "TeamCreate" in DEFAULT_BLOCK_REASON_TEMPLATE

    def test_template_format(self):
        """テンプレートのフォーマットが正しい"""
        formatted = DEFAULT_BLOCK_REASON_TEMPLATE.format(
            subagent_type="ticket-tasuki:coder"
        )
        assert "ticket-tasuki:coder" in formatted
