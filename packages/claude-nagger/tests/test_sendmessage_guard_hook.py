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
    """validate_content の検証テスト（正規表現バリデーション）"""

    def test_valid_format(self, hook):
        """正常: デフォルト(^.+$)で任意の非空文字列が通過"""
        result = hook.validate_content("issue_6041 [完了]")
        assert result["valid"] is True
        assert result["violation"] is None

    def test_any_nonempty_passes_default(self, hook):
        """正常: デフォルトパターンでは非空文字列はすべて通過"""
        result = hook.validate_content("任意のテキスト")
        assert result["valid"] is True

    def test_empty_content(self, hook):
        """空文字列はデフォルトパターンでも拒否"""
        result = hook.validate_content("")
        assert result["valid"] is False
        assert "フォーマット不一致" in result["violation"]

    def test_custom_pattern(self, hook_with_config):
        """カスタムパターンが適用される"""
        h = hook_with_config({"pattern": r"^TICKET-\d+ \[.+\]$"})
        result = h.validate_content("TICKET-123 [完了]")
        assert result["valid"] is True

        result = h.validate_content("issue_6041 [完了]")
        assert result["valid"] is False

    def test_violation_includes_pattern(self, hook_with_config):
        """violation文に設定パターンが含まれる"""
        pattern = r"^issue_\d+ \[.+\]$"
        h = hook_with_config({"pattern": pattern})
        result = h.validate_content("不正な形式")
        assert result["valid"] is False
        assert pattern in result["violation"]

    def test_various_valid_statuses(self, hook_with_config):
        """正常: enum指定パターンで全enum値が許可される"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$"
        })
        valid_contents = [
            "issue_1 [完了]",
            "issue_99999 [指示]",
            "issue_7225 [相談]",
            "issue_100 [確認]",
            "issue_42 [要判断]",
            "issue_7777 [ブロッカー]",
        ]
        for content in valid_contents:
            result = h.validate_content(content)
            assert result["valid"] is True, f"Expected valid: {content}"

    def test_various_invalid_statuses(self, hook_with_config):
        """異常: enum指定パターンでenum外のステータスは拒否"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$"
        })
        invalid_contents = [
            "issue_1 [着手中]",
            "issue_2 [ブロック中]",
            "issue_3 [報告]",
            "issue_4 [完了しました]",
        ]
        for content in invalid_contents:
            result = h.validate_content(content)
            assert result["valid"] is False, f"Expected invalid: {content}"

    def test_missing_issue_id_with_pattern(self, hook_with_config):
        """異常: カスタムパターンでissue_idなし"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$"
        })
        result = h.validate_content("タスク完了しました")
        assert result["valid"] is False
        assert "フォーマット不一致" in result["violation"]

    def test_missing_brackets_with_pattern(self, hook_with_config):
        """異常: カスタムパターンでブラケットなし"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$"
        })
        result = h.validate_content("issue_6041")
        assert result["valid"] is False
        assert "フォーマット不一致" in result["violation"]


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
        """正常メッセージ → approve（デフォルトは非空で通過）"""
        input_data = {
            "tool_input": {"content": "issue_6041 [完了]"},
        }
        result = hook.process(input_data)
        assert result["decision"] == "approve"

    def test_block_missing_issue_id(self, hook_with_config):
        """issue_id なし → block（カスタムパターン使用時）"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$"
        })
        input_data = {
            "tool_input": {"content": "タスク完了しました"},
        }
        result = h.process(input_data)
        assert result["decision"] == "block"
        assert "フォーマット不一致" in result["reason"]
        assert "SendMessage規約違反" in result["reason"]

    def test_block_invalid_format(self, hook_with_config):
        """フォーマット不正（ブラケットなし） → block（カスタムパターン使用時）"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$"
        })
        input_data = {
            "tool_input": {"content": "issue_6041 完了しました"},
        }
        result = h.process(input_data)
        assert result["decision"] == "block"
        assert "フォーマット不一致" in result["reason"]

    def test_block_reason_contains_pattern(self, hook_with_config):
        """block reason に設定パターンと対処法が含まれる"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$"
        })
        input_data = {
            "tool_input": {"content": "完了しました"},
        }
        result = h.process(input_data)
        assert "SendMessage規約違反" in result["reason"]
        assert "対処" in result["reason"]

    def test_empty_content(self, hook):
        """content が空 → block（デフォルトパターンでも空は拒否）"""
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
        reason = DEFAULT_BLOCK_REASON_TEMPLATE.format(
            violation="テスト違反", pattern=DEFAULT_PATTERN
        )
        assert "テスト違反" in reason
        assert "SendMessage規約違反" in reason

    def test_template_contains_instructions(self):
        """テンプレートに対処法が含まれる"""
        reason = DEFAULT_BLOCK_REASON_TEMPLATE.format(
            violation="test", pattern=DEFAULT_PATTERN
        )
        assert "対処" in reason
        assert "再送" in reason


# === block_message カスタマイズテスト ===

class TestBlockMessageCustomization:
    """block_message カスタマイズ機能のテスト"""

    def test_custom_block_message(self, hook_with_config):
        """config.yaml に block_message 設定時、カスタムメッセージが使用される"""
        custom_msg = "カスタム違反通知: {violation}"
        h = hook_with_config({"block_message": custom_msg})
        input_data = {
            "tool_input": {"content": ""},
        }
        result = h.process(input_data)
        assert result["decision"] == "block"
        assert "カスタム違反通知:" in result["reason"]
        # デフォルトテンプレートの内容が含まれないことを確認
        assert "SendMessage規約違反" not in result["reason"]

    def test_default_block_message_fallback(self, hook):
        """block_message 未設定時にデフォルトテンプレートが使用される"""
        input_data = {
            "tool_input": {"content": ""},
        }
        result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "SendMessage規約違反" in result["reason"]

    def test_block_message_placeholders(self, hook_with_config):
        """{violation}, {pattern} が正しく展開される"""
        custom_msg = "違反={violation} パターン={pattern}"
        h = hook_with_config({
            "block_message": custom_msg,
            "pattern": r"^issue_\d+ \[.+\]$",
        })
        input_data = {
            "tool_input": {"content": "no issue id here"},
        }
        result = h.process(input_data)
        assert result["decision"] == "block"
        assert "違反=フォーマット不一致" in result["reason"]
        assert r"パターン=^issue_\d+ \[.+\]$" in result["reason"]
