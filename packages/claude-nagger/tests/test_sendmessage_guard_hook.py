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
    DEFAULT_P2P_BROADCAST_BLOCK_MESSAGE,
    DEFAULT_P2P_MESSAGE_BLOCK_MESSAGE,
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

    def test_bracket_content_80chars_passes(self, hook_with_config):
        """正常: ブラケット内80文字ちょうどで通過"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[.{1,80}\]$"
        })
        content_80 = "a" * 80
        result = h.validate_content(f"issue_1234 [{content_80}]")
        assert result["valid"] is True

    def test_bracket_content_81chars_rejected(self, hook_with_config):
        """異常: ブラケット内81文字で拒否"""
        h = hook_with_config({
            "pattern": r"^issue_\d+ \[.{1,80}\]$"
        })
        content_81 = "a" * 81
        result = h.validate_content(f"issue_1234 [{content_81}]")
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


# === _validate_p2p テスト ===

class TestValidateP2P:
    """_validate_p2p のP2P通信許可検証テスト"""

    def _make_hook(self, guard_config):
        """P2P設定付きフックインスタンスを生成"""
        with patch(
            "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
        ) as mock_cm:
            mock_cm.return_value.config = {"sendmessage_guard": guard_config}
            h = SendMessageGuardHook(debug=False)
        return h

    def _base_p2p_config(self, matrix=None, default_policy="deny"):
        """P2Pテスト用の基本設定を返す"""
        return {
            "exempt_types": ["shutdown_request", "shutdown_response"],
            "p2p_rules": {
                "enabled": True,
                "broadcast_allowed_roles": ["leader"],
                "matrix": {"coder": ["team-lead"], "tester": ["team-lead", "coder"]} if matrix is None else matrix,
                "default_policy": default_policy,
            },
        }

    # --- recipient正規化テスト ---

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_recipient_raw_normalized_to_match_matrix(
        self, mock_known, mock_normalize, mock_roles
    ):
        """raw recipient（例: team-lead-123）が正規化されmatrixと照合される"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder", "tester"}
        mock_normalize.return_value = "team-lead"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "team-lead-123"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_recipient_suffix_removed(self, mock_known, mock_normalize, mock_roles):
        """数値サフィックス付きrecipientが正規化される"""
        mock_roles.return_value = {"tester"}
        mock_known.return_value = {"team-lead", "coder", "tester"}
        mock_normalize.return_value = "coder"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "coder-7097"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_recipient_prefix_removed(self, mock_known, mock_normalize, mock_roles):
        """プレフィックス付きrecipient（例: claude-coder）が正規化される"""
        mock_roles.return_value = {"tester"}
        mock_known.return_value = {"team-lead", "coder", "tester"}
        mock_normalize.return_value = "coder"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "claude-coder"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_unknown_recipient_denied(self, mock_known, mock_normalize, mock_roles):
        """未知ロールのrecipientは正規化後もmatrixに一致せずdeny"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder", "tester"}
        mock_normalize.return_value = "unknown-agent"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "unknown-agent-999"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False
        assert "P2P制御" in result["violation"]

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_empty_recipient_not_matched(self, mock_known, mock_normalize, mock_roles):
        """空文字列recipientはmatrixに一致しない"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder"}
        mock_normalize.return_value = ""

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": ""}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_exact_match_recipient_passes(self, mock_known, mock_normalize, mock_roles):
        """完全一致recipientはそのままmatrix照合される"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder"}
        mock_normalize.return_value = "team-lead"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "team-lead"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    # --- caller/recipient両方正規化テスト ---

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_both_caller_and_recipient_normalized(
        self, mock_known, mock_normalize, mock_roles
    ):
        """caller（get_caller_rolesで正規化済み）とrecipient両方が正規化される"""
        # callerはget_caller_rolesが正規化済みsetを返す
        mock_roles.return_value = {"tester"}
        mock_known.return_value = {"team-lead", "coder", "tester"}
        mock_normalize.return_value = "team-lead"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "team-lead-456"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_caller_coder_recipient_tester_denied(
        self, mock_known, mock_normalize, mock_roles
    ):
        """coder→tester はmatrixに未定義なのでdeny"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder", "tester"}
        mock_normalize.return_value = "tester"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "tester-100"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_tester_to_coder_allowed(self, mock_known, mock_normalize, mock_roles):
        """tester→coder はmatrixで許可"""
        mock_roles.return_value = {"tester"}
        mock_known.return_value = {"team-lead", "coder", "tester"}
        mock_normalize.return_value = "coder"

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "coder-7097"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    # --- エッジケーステスト ---

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_matrix_undefined_deny(self, mock_known, mock_normalize, mock_roles):
        """matrixが空の場合、default_policy=denyでブロック"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder"}
        mock_normalize.return_value = "team-lead"

        config = self._base_p2p_config(matrix={}, default_policy="deny")
        h = self._make_hook(config)
        input_data = {"tool_input": {"type": "message", "recipient": "team-lead"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_matrix_undefined_allow(self, mock_known, mock_normalize, mock_roles):
        """matrixが空でもdefault_policy=allowなら許可"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder"}
        mock_normalize.return_value = "team-lead"

        config = self._base_p2p_config(matrix={}, default_policy="allow")
        h = self._make_hook(config)
        input_data = {"tool_input": {"type": "message", "recipient": "team-lead"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    def test_p2p_disabled_skips(self, mock_roles):
        """P2P無効時はvalidation自体をスキップ"""
        mock_roles.return_value = {"coder"}
        config = {
            "exempt_types": [],
            "p2p_rules": {"enabled": False},
        }
        h = self._make_hook(config)
        input_data = {"tool_input": {"type": "message", "recipient": "anyone"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_known_roles_empty_uses_raw(self, mock_known, mock_roles):
        """known_rolesが空の場合、recipientはraw値のまま照合"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = set()

        # matrixにraw値そのものが入っていれば一致する
        config = self._base_p2p_config(matrix={"coder": ["team-lead-123"]})
        h = self._make_hook(config)
        input_data = {"tool_input": {"type": "message", "recipient": "team-lead-123"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is True

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    def test_recipient_none_treated_as_empty(self, mock_known, mock_normalize, mock_roles):
        """recipientがNoneの場合、空文字列として扱われる"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder"}
        mock_normalize.return_value = ""

        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": None}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        # Noneは空文字列化されmatrixに一致しないためdeny
        assert result["valid"] is False
        assert "P2P制御" in result["violation"]


# === P2P E2Eテスト ===

class TestP2PE2E:
    """P2P通信制御のE2Eテスト

    モック最小限（get_caller_roles, _get_known_roles_from_config のみ）で
    実際の_normalize_roleロジックとhookチェーンを通すテスト。
    """

    # 共通matrix: coder→team-lead, tester→team-lead/coder
    _MATRIX = {
        "coder": ["team-lead"],
        "tester": ["team-lead", "coder"],
    }
    _KNOWN_ROLES = {"team-lead", "coder", "tester", "leader", "pmo"}

    def _make_p2p_hook(self, matrix=None, default_policy="deny"):
        """P2P有効のhookインスタンスを生成"""
        config = {
            "exempt_types": ["shutdown_request", "shutdown_response"],
            "p2p_rules": {
                "enabled": True,
                "broadcast_allowed_roles": ["leader"],
                "matrix": matrix if matrix is not None else self._MATRIX,
                "default_policy": default_policy,
            },
        }
        with patch(
            "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
        ) as mock_cm:
            mock_cm.return_value.config = {"sendmessage_guard": config}
            h = SendMessageGuardHook(debug=False)
        return h

    def _run_p2p(self, hook, caller_role, recipient):
        """P2P検証を実行して結果を返す"""
        input_data = {"tool_input": {"type": "message", "recipient": recipient}}
        with patch(
            "src.domain.hooks.sendmessage_guard_hook.get_caller_roles"
        ) as mock_roles, patch(
            "infrastructure.db.subagent_repository._get_known_roles_from_config"
        ) as mock_known:
            mock_roles.return_value = {caller_role}
            mock_known.return_value = self._KNOWN_ROLES
            return hook._validate_p2p(input_data, input_data["tool_input"])

    # --- 正常系: 通信許可（7件） ---

    def test_coder_to_team_lead_raw_suffix_allowed(self):
        """coder→team-lead-456: サフィックス除去で正規化→許可"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "team-lead-456")
        assert result["valid"] is True

    def test_coder_to_team_lead_exact_allowed(self):
        """coder→team-lead: 完全一致→許可"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "team-lead")
        assert result["valid"] is True

    def test_tester_to_coder_raw_suffix_allowed(self):
        """tester→coder-7097: サフィックス除去で正規化→許可"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "tester", "coder-7097")
        assert result["valid"] is True

    def test_tester_to_team_lead_allowed(self):
        """tester→team-lead: matrix定義通り許可"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "tester", "team-lead")
        assert result["valid"] is True

    def test_tester_to_coder_prefix_allowed(self):
        """tester→claude-coder: プレフィックス除去で正規化→許可"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "tester", "claude-coder")
        assert result["valid"] is True

    def test_leader_to_anyone_allowed(self):
        """leader→任意recipient: leaderは全許可"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "leader", "anyone-999")
        assert result["valid"] is True

    def test_coder_to_team_lead_with_long_suffix_allowed(self):
        """coder→team-lead-12345: 長い数値サフィックスでも正規化→許可"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "team-lead-12345")
        assert result["valid"] is True

    # --- 異常系: 通信拒否（7件） ---

    def test_coder_to_pmo_denied(self):
        """coder→pmo-001: matrixにcoder→pmo未定義→拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "pmo-001")
        assert result["valid"] is False
        assert "P2P制御" in result["violation"]

    def test_coder_to_tester_denied(self):
        """coder→tester-200: matrixにcoder→tester未定義→拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "tester-200")
        assert result["valid"] is False

    def test_coder_to_coder_denied(self):
        """coder→coder-999: 自分自身のロールへの通信→matrixに未定義→拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "coder-999")
        assert result["valid"] is False

    def test_tester_to_pmo_denied(self):
        """tester→pmo: matrixにtester→pmo未定義→拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "tester", "pmo")
        assert result["valid"] is False

    def test_coder_to_unknown_agent_denied(self):
        """coder→unknown-agent-777: 未知ロール→拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "unknown-agent-777")
        assert result["valid"] is False

    def test_pmo_to_coder_denied(self):
        """pmo→coder: matrixにpmo未定義→拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "pmo", "coder")
        assert result["valid"] is False

    def test_coder_to_leader_denied(self):
        """coder→leader: matrixにcoder→leader未定義→拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "leader")
        assert result["valid"] is False

    # --- エッジケース（2件） ---

    def test_recipient_none_denied(self):
        """recipient=None→空文字列化→matrixに一致せず拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", None)
        assert result["valid"] is False

    def test_recipient_empty_string_denied(self):
        """recipient=""→matrixに一致せず拒否"""
        h = self._make_p2p_hook()
        result = self._run_p2p(h, "coder", "")
        assert result["valid"] is False


class TestP2PMessageCustomization:
    """P2P違反メッセージのconfig.yaml管理化テスト"""

    def _make_hook(self, guard_config):
        """P2P設定付きフックインスタンスを生成"""
        with patch(
            "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
        ) as mock_cm:
            mock_cm.return_value.config = {"sendmessage_guard": guard_config}
            h = SendMessageGuardHook(debug=False)
        return h

    def _base_p2p_config(self, **overrides):
        """P2P設定ベース（overridesでp2p_rulesキーを上書き可能）"""
        p2p_rules = {
            "enabled": True,
            "default_policy": "deny",
            "broadcast_allowed_roles": ["leader"],
            "matrix": {"coder": ["team-lead"]},
        }
        p2p_rules.update(overrides)
        return {"p2p_rules": p2p_rules}

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    def test_custom_broadcast_block_message(self, mock_roles):
        """config.yamlのbroadcast_block_message設定時、カスタムメッセージが使用される"""
        mock_roles.return_value = {"coder"}
        custom_msg = "【カスタム】broadcast禁止: role={roles}"
        h = self._make_hook(self._base_p2p_config(
            broadcast_block_message=custom_msg,
        ))
        input_data = {"tool_input": {"type": "broadcast"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False
        assert "【カスタム】broadcast禁止:" in result["violation"]
        # デフォルトメッセージが含まれないことを確認
        assert "team-leadへ個別送信してください" not in result["violation"]

    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    def test_default_broadcast_block_message_fallback(self, mock_roles):
        """broadcast_block_message未設定時にデフォルトメッセージが使用される"""
        mock_roles.return_value = {"coder"}
        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "broadcast"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False
        assert "P2P制御:" in result["violation"]
        assert "team-leadへ個別送信してください" in result["violation"]

    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    def test_custom_message_block_message(self, mock_roles, mock_normalize, mock_known):
        """config.yamlのmessage_block_message設定時、カスタムメッセージが使用される"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder", "pmo"}
        mock_normalize.return_value = "pmo"
        custom_msg = "【カスタム】直接通信禁止: {roles}→{recipient}"
        h = self._make_hook(self._base_p2p_config(
            message_block_message=custom_msg,
        ))
        input_data = {"tool_input": {"type": "message", "recipient": "pmo"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False
        assert "【カスタム】直接通信禁止:" in result["violation"]
        assert "pmo" in result["violation"]
        # デフォルトメッセージが含まれないことを確認
        assert "team-leadを経由してください" not in result["violation"]

    @patch("infrastructure.db.subagent_repository._get_known_roles_from_config")
    @patch("infrastructure.db.subagent_repository._normalize_role")
    @patch("src.domain.hooks.sendmessage_guard_hook.get_caller_roles")
    def test_default_message_block_message_fallback(self, mock_roles, mock_normalize, mock_known):
        """message_block_message未設定時にデフォルトメッセージが使用される"""
        mock_roles.return_value = {"coder"}
        mock_known.return_value = {"team-lead", "coder", "pmo"}
        mock_normalize.return_value = "pmo"
        h = self._make_hook(self._base_p2p_config())
        input_data = {"tool_input": {"type": "message", "recipient": "pmo"}}
        result = h._validate_p2p(input_data, input_data["tool_input"])
        assert result["valid"] is False
        assert "P2P制御:" in result["violation"]
        assert "team-leadを経由してください" in result["violation"]
