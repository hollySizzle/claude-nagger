"""Redmine MCP操作のDiscord通知フック（PostToolUse）

Redmine MCPツール（mcp__redmine_epic_grid__*）の実行後に
操作内容をDiscordへ通知する。
"""

import json
import logging
import sys
import time
from typing import Any, Dict, Optional

from domain.hooks.base_hook import BaseHook, ExitCode

logger = logging.getLogger(__name__)

# ツール名プレフィックス
REDMINE_TOOL_PREFIX = "mcp__redmine_epic_grid__"

# メッセージフォーマット上限
MAX_SUMMARY_LENGTH = 200

# RedmineチケットURL
REDMINE_BASE_URL = "https://redmine.giken.or.jp/issues/"


class RedmineDiscordHook(BaseHook):
    """Redmine MCP操作のDiscord通知フック

    PostToolUseイベントで発火し、Redmine MCPツール操作内容を
    DiscordNotifier経由で通知する。
    セッションマーカーは使用しない（毎回のRedmine操作を通知するため）。
    """

    def __init__(self, debug: Optional[bool] = None):
        """初期化

        Args:
            debug: デバッグモードフラグ
        """
        super().__init__(debug=debug)

    # --- 判定ロジック ---

    def is_target_tool(self, tool_name: str) -> bool:
        """Redmine MCPツールかどうかを判定

        Args:
            tool_name: ツール名

        Returns:
            mcp__redmine_epic_grid__ で始まる場合 True
        """
        return tool_name.startswith(REDMINE_TOOL_PREFIX)

    def _truncate(self, text: str, max_len: int = MAX_SUMMARY_LENGTH) -> str:
        """テキストを指定長に切り詰め"""
        if len(text) <= max_len:
            return text
        return text[:max_len] + "..."

    def _ticket_url(self, issue_id: str) -> str:
        """チケットURLを生成（issue_idが有効な場合のみ）"""
        if issue_id and issue_id != "?":
            return f"\n[詳細]({REDMINE_BASE_URL}{issue_id})"
        return ""

    def _format_message(self, tool_name: str, tool_input: Dict[str, Any]) -> str:
        """ツール種別に応じた通知メッセージを生成

        Args:
            tool_name: ツール名（フルネーム）
            tool_input: ツール入力パラメータ

        Returns:
            フォーマット済み通知メッセージ（本文200文字上限 + チケットURL）
        """
        # プレフィックスを除去して短縮名を取得
        short_name = tool_name.replace(REDMINE_TOOL_PREFIX, "")

        # add_issue_comment_tool → issue_id + コメント概要
        if short_name == "add_issue_comment_tool":
            issue_id = tool_input.get("issue_id", "?")
            comment = tool_input.get("comment", "")
            body = f"[Redmine] #{issue_id} コメント追加\n{self._truncate(comment)}"
            return body + self._ticket_url(issue_id)

        # update_issue_status_tool → issue_id + ステータス名
        if short_name == "update_issue_status_tool":
            issue_id = tool_input.get("issue_id", "?")
            status = tool_input.get("status_name", "?")
            body = f"[Redmine] #{issue_id} ステータス変更 → {status}"
            return body + self._ticket_url(issue_id)

        # create_*_tool → 作成種別 + subject/description概要
        if short_name.startswith("create_"):
            kind = short_name.replace("create_", "").replace("_tool", "")
            subject = tool_input.get("subject", "")
            description = tool_input.get("description", "")
            summary = subject or self._truncate(description)
            body = f"[Redmine] {kind} 作成: {self._truncate(summary)}"
            # create系はissue_idがないため、parent系IDから推測
            parent_id = (tool_input.get("parent_user_story_id")
                         or tool_input.get("parent_feature_id")
                         or tool_input.get("parent_epic_id"))
            return body + self._ticket_url(parent_id or "")

        # update_*_tool → 更新種別 + 変更内容概要
        if short_name.startswith("update_"):
            kind = short_name.replace("update_", "").replace("_tool", "")
            issue_id = tool_input.get("issue_id", "?")
            # 主要な変更内容を抽出
            detail_keys = ["subject", "description", "status_name", "assigned_to_id", "progress"]
            details = {k: v for k, v in tool_input.items() if k in detail_keys and v}
            detail_str = ", ".join(f"{k}={v}" for k, v in details.items()) if details else "変更あり"
            body = f"[Redmine] #{issue_id} {kind} 更新: {self._truncate(detail_str)}"
            return body + self._ticket_url(issue_id)

        # その他 → ツール名 + input概要
        issue_id = tool_input.get("issue_id", "")
        input_summary = self._truncate(json.dumps(tool_input, ensure_ascii=False))
        body = f"[Redmine] {short_name}: {input_summary}"
        return body + self._ticket_url(issue_id)

    # --- BaseHook 抽象メソッドの実装 ---

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """処理対象かどうかを判定

        Args:
            input_data: 入力データ

        Returns:
            Redmine MCPツールの場合 True
        """
        tool_name = input_data.get("tool_name", "")
        return self.is_target_tool(tool_name)

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """Redmine操作内容をDiscordへ通知

        Args:
            input_data: 入力データ

        Returns:
            decision と reason を含む辞書
        """
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})

        # 通知メッセージ生成
        message = self._format_message(tool_name, tool_input)
        self.log_debug(f"Discord通知メッセージ: {message}")

        # secrets.yamlからwebhook_url/thread_idを直接取得
        try:
            from infrastructure.config.config_manager import ConfigManager
            cm = ConfigManager()
            secrets = cm._load_secrets()
            discord_secrets = secrets.get("discord", {})
            webhook_url = discord_secrets.get("webhook_url", "")
            thread_id = discord_secrets.get("thread_id", "")
        except Exception as e:
            self.log_warning(f"secrets読み込み失敗: {e}")
            webhook_url = ""
            thread_id = ""

        if not webhook_url:
            self.log_warning("Discord webhook_url未設定、通知スキップ")
            return {"decision": "approve", "reason": ""}

        # Discord送信（失敗してもブロックしない）
        try:
            from infrastructure.notifiers.discord_notifier import DiscordNotifier
            notifier = DiscordNotifier()
            result = notifier.send_sync(
                message,
                webhook_url=webhook_url,
                thread_id=thread_id if thread_id else None,
            )
            if result.get("success"):
                self.log_info(f"Discord通知送信成功: {tool_name}")
            else:
                self.log_warning(f"Discord通知送信失敗: {result.get('error', '不明')}")
        except Exception as e:
            self.log_warning(f"Discord通知送信例外: {e}")

        return {"decision": "approve", "reason": ""}

    # --- run() オーバーライド ---

    def run(self) -> int:
        """フックのメインエントリーポイント

        BaseHook.run() のセッションマーカー処理をスキップする簡略版。
        毎回のRedmine操作を通知するためマーカーは不要。

        Returns:
            ExitCode
        """
        self._start_time = time.time()

        # 設定ファイル存在保証
        from application.install_hooks import ensure_config_exists
        ensure_config_exists()

        self._structured_logger.log_hook_event(
            event_type="start",
            hook_name=self.__class__.__name__,
            debug_mode=self.debug,
        )

        try:
            input_data = self.read_input()
            if not input_data:
                self.log_debug("No input data, exiting")
                return ExitCode.SUCCESS

            # 処理対象チェック（セッションマーカーチェックなし）
            if not self.should_process(input_data):
                self.log_debug("Not a target for processing, skipping")
                return ExitCode.SUCCESS

            # 処理実行
            result = self.process(input_data)

            # PostToolUseはhookSpecificOutput不要、exit 0のみ
            self._log_hook_end(decision=result["decision"])
            return ExitCode.SUCCESS

        except Exception as e:
            self.log_error(f"Unexpected error in run", error=str(e))
            self._log_hook_end(decision="error")
            return ExitCode.ERROR


def main():
    """エントリーポイント"""
    hook = RedmineDiscordHook()
    sys.exit(hook.run())


if __name__ == "__main__":
    main()
