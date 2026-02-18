"""redmine_discord_hook.py のテスト"""

import json
import pytest
from unittest.mock import patch, MagicMock

from src.domain.hooks.redmine_discord_hook import (
    RedmineDiscordHook,
    REDMINE_TOOL_PREFIX,
    MAX_SUMMARY_LENGTH,
    REDMINE_BASE_URL,
)


@pytest.fixture
def hook():
    """テスト用フックインスタンス"""
    h = RedmineDiscordHook(debug=False)
    return h


# === is_target_tool テスト ===

class TestIsTargetTool:
    """is_target_tool の判定テスト"""

    def test_redmine_tool_returns_true(self, hook):
        assert hook.is_target_tool("mcp__redmine_epic_grid__add_issue_comment_tool") is True

    def test_redmine_update_returns_true(self, hook):
        assert hook.is_target_tool("mcp__redmine_epic_grid__update_issue_status_tool") is True

    def test_redmine_create_returns_true(self, hook):
        assert hook.is_target_tool("mcp__redmine_epic_grid__create_task_tool") is True

    def test_other_tool_returns_false(self, hook):
        assert hook.is_target_tool("SendMessage") is False

    def test_empty_returns_false(self, hook):
        assert hook.is_target_tool("") is False

    def test_partial_prefix_returns_false(self, hook):
        assert hook.is_target_tool("mcp__redmine_epic_grid_") is False


# === should_process テスト ===

class TestShouldProcess:
    """should_process の判定テスト"""

    def test_redmine_tool_returns_true(self, hook):
        input_data = {"tool_name": "mcp__redmine_epic_grid__add_issue_comment_tool"}
        assert hook.should_process(input_data) is True

    def test_non_redmine_tool_returns_false(self, hook):
        input_data = {"tool_name": "Bash"}
        assert hook.should_process(input_data) is False

    def test_missing_tool_name_returns_false(self, hook):
        assert hook.should_process({}) is False

    def test_empty_tool_name_returns_false(self, hook):
        input_data = {"tool_name": ""}
        assert hook.should_process(input_data) is False


# === _truncate テスト ===

class TestTruncate:
    """_truncate のテスト"""

    def test_short_text_unchanged(self, hook):
        assert hook._truncate("短いテキスト") == "短いテキスト"

    def test_long_text_truncated(self, hook):
        text = "a" * 300
        result = hook._truncate(text)
        assert len(result) == MAX_SUMMARY_LENGTH + 3  # "..."分
        assert result.endswith("...")

    def test_exact_length_unchanged(self, hook):
        text = "a" * MAX_SUMMARY_LENGTH
        assert hook._truncate(text) == text

    def test_custom_max_len(self, hook):
        result = hook._truncate("abcdefgh", max_len=5)
        assert result == "abcde..."


# === _ticket_url テスト ===

class TestTicketUrl:
    """_ticket_url のテスト"""

    def test_valid_issue_id(self, hook):
        assert hook._ticket_url("123") == f"\n[詳細]({REDMINE_BASE_URL}123)"

    def test_unknown_issue_id(self, hook):
        assert hook._ticket_url("?") == ""

    def test_empty_issue_id(self, hook):
        assert hook._ticket_url("") == ""


# === _format_message テスト ===

class TestFormatMessage:
    """_format_message のツール種別別テスト"""

    def test_add_issue_comment(self, hook):
        """add_issue_comment_tool: issue_id + コメント概要 + URL"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__add_issue_comment_tool",
            {"issue_id": "100", "comment": "テストコメント"}
        )
        assert "[Redmine] #100 コメント追加" in msg
        assert "テストコメント" in msg
        assert f"{REDMINE_BASE_URL}100" in msg

    def test_add_issue_comment_long_not_truncated(self, hook):
        """add_issue_comment_tool: 長いコメントも全文送信"""
        long_comment = "x" * 500
        msg = hook._format_message(
            "mcp__redmine_epic_grid__add_issue_comment_tool",
            {"issue_id": "100", "comment": long_comment}
        )
        # 全文が含まれること
        assert long_comment in msg

    def test_update_issue_status(self, hook):
        """update_issue_status_tool: issue_id + ステータス名 + URL"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__update_issue_status_tool",
            {"issue_id": "200", "status_name": "着手中"}
        )
        assert "[Redmine] #200 ステータス変更 → 着手中" in msg
        assert f"{REDMINE_BASE_URL}200" in msg

    def test_create_task(self, hook):
        """create_task_tool: 作成種別 + description概要"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__create_task_tool",
            {"description": "タスク内容", "parent_user_story_id": "300"}
        )
        assert "[Redmine] task 作成:" in msg
        assert "タスク内容" in msg
        assert f"{REDMINE_BASE_URL}300" in msg

    def test_create_epic_with_subject(self, hook):
        """create_epic_tool: subject優先"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__create_epic_tool",
            {"subject": "エピック名", "description": "詳細"}
        )
        assert "エピック名" in msg

    def test_create_without_parent_id(self, hook):
        """create系でparent IDがない場合はURL省略"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__create_epic_tool",
            {"subject": "テスト"}
        )
        assert REDMINE_BASE_URL not in msg

    def test_update_issue_subject(self, hook):
        """update_issue_subject_tool: 更新種別 + 変更内容 + URL"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__update_issue_subject_tool",
            {"issue_id": "400", "subject": "新しいタイトル"}
        )
        assert "[Redmine] #400 issue_subject 更新:" in msg
        assert "subject=新しいタイトル" in msg
        assert f"{REDMINE_BASE_URL}400" in msg

    def test_update_no_details(self, hook):
        """update系で変更内容なしの場合"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__update_issue_progress_tool",
            {"issue_id": "500"}
        )
        assert "変更あり" in msg

    def test_other_tool(self, hook):
        """その他ツール: ツール名 + input概要"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__list_epics_tool",
            {"project_id": "test"}
        )
        assert "[Redmine] list_epics_tool:" in msg

    def test_other_tool_with_issue_id(self, hook):
        """その他ツールでissue_idがある場合はURL付与"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__get_issue_detail_tool",
            {"issue_id": "600"}
        )
        assert f"{REDMINE_BASE_URL}600" in msg

    def test_other_tool_without_issue_id(self, hook):
        """その他ツールでissue_idがない場合はURL省略"""
        msg = hook._format_message(
            "mcp__redmine_epic_grid__list_versions_tool",
            {"project_id": "test"}
        )
        assert REDMINE_BASE_URL not in msg


# === process テスト（DiscordNotifier + secrets モック） ===

# secrets.yamlモック用ヘルパー
MOCK_SECRETS = {"discord": {"webhook_url": "https://discord.com/api/webhooks/test", "thread_id": "12345"}}


def _mock_secrets_and_notifier(mock_send_result=None):
    """ConfigManager._load_secrets + DiscordNotifier を同時モックするコンテキスト"""
    if mock_send_result is None:
        mock_send_result = {"success": True}
    return (
        patch("infrastructure.config.config_manager.ConfigManager._load_secrets", return_value=MOCK_SECRETS),
        patch("infrastructure.notifiers.discord_notifier.DiscordNotifier"),
        mock_send_result,
    )


class TestProcess:
    """process のDiscord送信テスト"""

    def test_sends_discord_and_approves(self, hook):
        """Discord送信成功時にapprove返却"""
        mock_result = {"success": True, "agent_name": "test", "message": "ok"}
        with patch(
            "infrastructure.config.config_manager.ConfigManager._load_secrets",
            return_value=MOCK_SECRETS,
        ), patch(
            "infrastructure.notifiers.discord_notifier.DiscordNotifier"
        ) as mock_cls:
            mock_cls.return_value.send_sync.return_value = mock_result
            result = hook.process({
                "tool_name": "mcp__redmine_epic_grid__update_issue_status_tool",
                "tool_input": {"issue_id": "100", "status_name": "着手中"}
            })
        assert result["decision"] == "approve"
        mock_cls.return_value.send_sync.assert_called_once()
        # webhook_url/thread_idが明示渡しされていること
        call_kwargs = mock_cls.return_value.send_sync.call_args[1]
        assert call_kwargs["webhook_url"] == "https://discord.com/api/webhooks/test"
        assert call_kwargs["thread_id"] == "12345"

    def test_discord_failure_still_approves(self, hook):
        """Discord送信失敗時もapprove返却（ブロックしない）"""
        mock_result = {"success": False, "error": "webhook error"}
        with patch(
            "infrastructure.config.config_manager.ConfigManager._load_secrets",
            return_value=MOCK_SECRETS,
        ), patch(
            "infrastructure.notifiers.discord_notifier.DiscordNotifier"
        ) as mock_cls:
            mock_cls.return_value.send_sync.return_value = mock_result
            result = hook.process({
                "tool_name": "mcp__redmine_epic_grid__add_issue_comment_tool",
                "tool_input": {"issue_id": "100", "comment": "test"}
            })
        assert result["decision"] == "approve"

    def test_discord_exception_still_approves(self, hook):
        """Discord送信例外時もapprove返却"""
        with patch(
            "infrastructure.config.config_manager.ConfigManager._load_secrets",
            return_value=MOCK_SECRETS,
        ), patch(
            "infrastructure.notifiers.discord_notifier.DiscordNotifier"
        ) as mock_cls:
            mock_cls.return_value.send_sync.side_effect = Exception("connection error")
            result = hook.process({
                "tool_name": "mcp__redmine_epic_grid__create_task_tool",
                "tool_input": {"description": "task", "parent_user_story_id": "1"}
            })
        assert result["decision"] == "approve"

    def test_message_content_passed_to_notifier(self, hook):
        """生成メッセージがDiscordNotifierに渡される"""
        with patch(
            "infrastructure.config.config_manager.ConfigManager._load_secrets",
            return_value=MOCK_SECRETS,
        ), patch(
            "infrastructure.notifiers.discord_notifier.DiscordNotifier"
        ) as mock_cls:
            mock_cls.return_value.send_sync.return_value = {"success": True}
            hook.process({
                "tool_name": "mcp__redmine_epic_grid__update_issue_status_tool",
                "tool_input": {"issue_id": "999", "status_name": "クローズ"}
            })
            sent_msg = mock_cls.return_value.send_sync.call_args[0][0]
            assert "#999" in sent_msg
            assert "クローズ" in sent_msg

    def test_no_webhook_url_skips_send(self, hook):
        """webhook_url未設定時は送信スキップしてapprove"""
        empty_secrets = {"discord": {"webhook_url": "", "thread_id": ""}}
        with patch(
            "infrastructure.config.config_manager.ConfigManager._load_secrets",
            return_value=empty_secrets,
        ), patch(
            "infrastructure.notifiers.discord_notifier.DiscordNotifier"
        ) as mock_cls:
            result = hook.process({
                "tool_name": "mcp__redmine_epic_grid__update_issue_status_tool",
                "tool_input": {"issue_id": "100", "status_name": "着手中"}
            })
        assert result["decision"] == "approve"
        mock_cls.return_value.send_sync.assert_not_called()


# === install_hooks PostToolUse登録テスト ===

class TestInstallHooksPostToolUse:
    """install_hooks.py の PostToolUse 登録テスト"""

    def test_default_posttooluse_hooks_defined(self):
        """DEFAULT_POSTTOOLUSE_HOOKSが定義されている"""
        from src.application.install_hooks import InstallHooksCommand
        cmd = InstallHooksCommand()
        assert hasattr(cmd, "DEFAULT_POSTTOOLUSE_HOOKS")
        assert isinstance(cmd.DEFAULT_POSTTOOLUSE_HOOKS, list)
        assert len(cmd.DEFAULT_POSTTOOLUSE_HOOKS) > 0

    def test_posttooluse_matcher(self):
        """matcherがRedmine MCPパターン"""
        from src.application.install_hooks import InstallHooksCommand
        cmd = InstallHooksCommand()
        matchers = [h.get("matcher") for h in cmd.DEFAULT_POSTTOOLUSE_HOOKS]
        assert "mcp__redmine_epic_grid__.*" in matchers

    def test_posttooluse_command(self):
        """コマンドがredmine-discord hookを指す"""
        from src.application.install_hooks import InstallHooksCommand
        cmd = InstallHooksCommand()
        commands = [
            h["command"]
            for entry in cmd.DEFAULT_POSTTOOLUSE_HOOKS
            for h in entry.get("hooks", [])
        ]
        assert "claude-nagger hook redmine-discord" in commands

    def test_posttooluse_merge(self):
        """PostToolUseフックがsettingsにマージされる"""
        from src.application.install_hooks import InstallHooksCommand
        cmd = InstallHooksCommand()
        settings = {"hooks": {}}
        cmd._merge_hook_entries(settings, "PostToolUse", cmd.DEFAULT_POSTTOOLUSE_HOOKS)
        assert "PostToolUse" in settings["hooks"]
        assert len(settings["hooks"]["PostToolUse"]) > 0

    def test_posttooluse_no_duplicate(self):
        """同一hook重複追加されない"""
        from src.application.install_hooks import InstallHooksCommand
        cmd = InstallHooksCommand()
        settings = {"hooks": {}}
        cmd._merge_hook_entries(settings, "PostToolUse", cmd.DEFAULT_POSTTOOLUSE_HOOKS)
        updated = cmd._merge_hook_entries(settings, "PostToolUse", cmd.DEFAULT_POSTTOOLUSE_HOOKS)
        assert updated is False
