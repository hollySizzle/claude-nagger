# 方式E統合テスト実施記録 (issue_6050/issue_6051)
# Agent Teams + sendmessage_guard 動作確認
"""sendmessage_guard_hook.py のテスト"""

import json
import os
import pytest
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.hooks.sendmessage_guard_hook import (
    SendMessageGuardHook,
    DEFAULT_PATTERN,
    DEFAULT_MAX_CONTENT_LENGTH,
    DEFAULT_EXEMPT_TYPES,
    DEFAULT_BLOCK_REASON_TEMPLATE,
)


@pytest.fixture
def hook():
    """テスト用フックインスタンス（デフォルト設定）"""
    with patch(
        "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
    ) as mock_cm:
        mock_cm.return_value.config = {}
        h = SendMessageGuardHook(debug=False)
    return h


@pytest.fixture
def hook_with_config():
    """カスタム設定付きフックインスタンスを生成するファクトリ"""
    def _factory(guard_config: dict):
        with patch(
            "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
        ) as mock_cm:
            mock_cm.return_value.config = {"sendmessage_guard": guard_config}
            h = SendMessageGuardHook(debug=False)
        return h
    return _factory


# === is_target_tool テスト ===

class TestIsTargetTool:
    """is_target_tool の判定テスト"""

    def test_sendmessage_returns_true(self, hook):
        assert hook.is_target_tool("SendMessage") is True

    def test_other_tool_returns_false(self, hook):
        assert hook.is_target_tool("Bash") is False
        assert hook.is_target_tool("Edit") is False
        assert hook.is_target_tool("") is False

    def test_case_sensitive(self, hook):
        """大文字小文字を区別する"""
        assert hook.is_target_tool("sendmessage") is False
        assert hook.is_target_tool("SENDMESSAGE") is False


# === is_exempt_type テスト ===

class TestIsExemptType:
    """is_exempt_type の判定テスト"""

    def test_exempt_types(self, hook):
        for t in DEFAULT_EXEMPT_TYPES:
            assert hook.is_exempt_type(t) is True

    def test_non_exempt_type(self, hook):
        assert hook.is_exempt_type("normal_message") is False
        assert hook.is_exempt_type("") is False

    def test_custom_exempt_types(self, hook_with_config):
        h = hook_with_config({"exempt_types": ["custom_type"]})
        assert h.is_exempt_type("custom_type") is True
        assert h.is_exempt_type("shutdown_request") is False


# === validate_content テスト ===

class TestValidateContent:
    """validate_content の検証テスト"""

    def test_valid_content(self, hook):
        """正常: issue_id あり + 短文"""
        result = hook.validate_content("issue_6041 [完了]")
        assert result["valid"] is True
        assert result["violation"] is None

    def test_missing_issue_id(self, hook):
        """異常: issue_id なし"""
        result = hook.validate_content("タスク完了しました")
        assert result["valid"] is False
        assert "issue_idが含まれていない" in result["violation"]

    def test_content_too_long(self, hook):
        """異常: 文字数超過"""
        long_content = "issue_6041 " + "a" * 200
        result = hook.validate_content(long_content)
        assert result["valid"] is False
        assert "文字数超過" in result["violation"]
        assert "Redmine" in result["violation"]

    def test_exact_max_length(self, hook):
        """境界: ちょうど max_content_length"""
        # DEFAULT_MAX_CONTENT_LENGTH=30, issue_6041は10文字、残り20文字で合計30文字
        content = "issue_6041" + "x" * (DEFAULT_MAX_CONTENT_LENGTH - 10)
        assert len(content) == DEFAULT_MAX_CONTENT_LENGTH
        result = hook.validate_content(content)
        assert result["valid"] is True

    def test_one_over_max_length(self, hook):
        """境界: max_content_length + 1"""
        content = "issue_6041" + "x" * 91
        assert len(content) == 101
        result = hook.validate_content(content)
        assert result["valid"] is False

    def test_custom_pattern(self, hook_with_config):
        """カスタムパターンが適用される"""
        h = hook_with_config({"pattern": r"TICKET-\d+"})
        result = h.validate_content("TICKET-123 [完了]")
        assert result["valid"] is True

        result = h.validate_content("issue_6041 [完了]")
        assert result["valid"] is False

    def test_custom_max_length(self, hook_with_config):
        """カスタム最大文字数が適用される"""
        h = hook_with_config({"max_content_length": 20})
        result = h.validate_content("issue_6041 [完了]")  # 14文字
        assert result["valid"] is True

        result = h.validate_content("issue_6041 これは長すぎるメッセージです")
        assert result["valid"] is False

    def test_pattern_match_priority_over_length(self, hook):
        """パターン不一致が文字数超過より優先される"""
        # パターンなし + 長すぎる → パターン不一致が先に判定される
        long_content = "a" * 200
        result = hook.validate_content(long_content)
        assert result["valid"] is False
        assert "issue_idが含まれていない" in result["violation"]

    def test_empty_content(self, hook):
        """空文字列"""
        result = hook.validate_content("")
        assert result["valid"] is False
        assert "issue_idが含まれていない" in result["violation"]


# === should_process テスト ===

class TestShouldProcess:
    """should_process の判定テスト"""

    def test_sendmessage_normal(self, hook):
        """SendMessage 通常メッセージ → True"""
        input_data = {
            "tool_name": "SendMessage",
            "tool_input": {"type": "normal", "content": "test"},
        }
        assert hook.should_process(input_data) is True

    def test_non_sendmessage(self, hook):
        """SendMessage 以外 → False"""
        input_data = {"tool_name": "Bash", "tool_input": {}}
        assert hook.should_process(input_data) is False

    def test_exempt_type_shutdown_request(self, hook):
        """shutdown_request → False"""
        input_data = {
            "tool_name": "SendMessage",
            "tool_input": {"type": "shutdown_request"},
        }
        assert hook.should_process(input_data) is False

    def test_exempt_type_shutdown_response(self, hook):
        """shutdown_response → False"""
        input_data = {
            "tool_name": "SendMessage",
            "tool_input": {"type": "shutdown_response"},
        }
        assert hook.should_process(input_data) is False

    def test_exempt_type_plan_approval(self, hook):
        """plan_approval_response → False"""
        input_data = {
            "tool_name": "SendMessage",
            "tool_input": {"type": "plan_approval_response"},
        }
        assert hook.should_process(input_data) is False

    def test_no_type_field(self, hook):
        """type フィールドなし → True（免除対象外）"""
        input_data = {
            "tool_name": "SendMessage",
            "tool_input": {"content": "test"},
        }
        assert hook.should_process(input_data) is True

    def test_empty_tool_input(self, hook):
        """tool_input が空 → True"""
        input_data = {
            "tool_name": "SendMessage",
            "tool_input": {},
        }
        assert hook.should_process(input_data) is True


# === process テスト ===

class TestProcess:
    """process の処理テスト"""

    def test_approve_valid_message(self, hook):
        """正常メッセージ → approve"""
        input_data = {
            "tool_input": {"content": "issue_6041 [完了]"},
        }
        result = hook.process(input_data)
        assert result["decision"] == "approve"

    def test_block_missing_issue_id(self, hook):
        """issue_id なし → block"""
        input_data = {
            "tool_input": {"content": "タスク完了しました"},
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "issue_idが含まれていない" in result["reason"]
        assert "SendMessage規約" in result["reason"]

    def test_block_too_long(self, hook):
        """文字数超過 → block"""
        input_data = {
            "tool_input": {"content": "issue_6041 " + "a" * 200},
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "文字数超過" in result["reason"]

    def test_block_reason_contains_instructions(self, hook):
        """block reason にフォーマット例が含まれる"""
        input_data = {
            "tool_input": {"content": "完了しました"},
        }
        result = hook.process(input_data)
        assert "add_issue_comment_tool" in result["reason"]
        assert "issue_6041 [完了]" in result["reason"]

    def test_empty_content(self, hook):
        """content が空 → block（issue_id なし）"""
        input_data = {
            "tool_input": {"content": ""},
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"

    def test_no_content_field(self, hook):
        """content フィールドなし → block"""
        input_data = {
            "tool_input": {},
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"


# === BLOCK_REASON_TEMPLATE テスト ===

class TestBlockReasonTemplate:
    """block reason テンプレートのテスト"""

    def test_template_format(self):
        """テンプレートが正しくフォーマットされる"""
        reason = DEFAULT_BLOCK_REASON_TEMPLATE.format(violation="テスト違反")
        assert "テスト違反" in reason
        assert "SendMessage規約" in reason
        assert "Redmine基盤通信" in reason

    def test_template_contains_instructions(self):
        """テンプレートに対処法が含まれる"""
        reason = DEFAULT_BLOCK_REASON_TEMPLATE.format(violation="test")
        assert "add_issue_comment_tool" in reason
        assert 'issue_{id}' in reason or "issue_6041" in reason


# === block_message カスタマイズテスト ===

class TestBlockMessageCustomization:
    """block_message カスタマイズ機能のテスト"""

    def test_custom_block_message(self, hook_with_config):
        """config.yaml に block_message 設定時、カスタムメッセージが使用される"""
        custom_msg = "カスタム違反通知: {violation}"
        h = hook_with_config({"block_message": custom_msg})
        input_data = {
            "tool_input": {"content": "issue_idなし"},
        }
        result = h.process(input_data)
        assert result["decision"] == "block"
        assert "カスタム違反通知:" in result["reason"]
        # デフォルトテンプレートの内容が含まれないことを確認
        assert "SendMessage規約" not in result["reason"]

    def test_default_block_message_fallback(self, hook):
        """block_message 未設定時にデフォルトテンプレートが使用される"""
        input_data = {
            "tool_input": {"content": "issue_idなし"},
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "SendMessage規約" in result["reason"]
        assert "Redmine基盤通信" in result["reason"]

    def test_block_message_placeholders(self, hook_with_config):
        """{violation}, {pattern}, {max_length} が正しく展開される"""
        custom_msg = "違反={violation} パターン={pattern} 上限={max_length}"
        h = hook_with_config({
            "block_message": custom_msg,
            "pattern": "issue_\\d+",
            "max_content_length": 200,
        })
        input_data = {
            "tool_input": {"content": "no issue id here"},
        }
        result = h.process(input_data)
        assert result["decision"] == "block"
        assert "違反=issue_idが含まれていない" in result["reason"]
        assert "パターン=issue_\\d+" in result["reason"]
        assert "上限=200" in result["reason"]
