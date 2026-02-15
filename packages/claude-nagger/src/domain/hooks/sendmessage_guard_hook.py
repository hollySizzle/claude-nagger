"""SendMessage ガードフック

SendMessage ツール使用時にメッセージ内容を検査し、
Redmine基盤通信規約（issue_id + 短文のみ）を強制する PreToolUse hook。
"""

import re
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.hooks.base_hook import BaseHook, ExitCode
from infrastructure.config.config_manager import ConfigManager

# デフォルト設定
DEFAULT_PATTERN = r"issue_\d+"
DEFAULT_MAX_CONTENT_LENGTH = 30
DEFAULT_EXEMPT_TYPES = [
    "shutdown_request",
    "shutdown_response",
    "plan_approval_response",
]

# block reason テンプレート
DEFAULT_BLOCK_REASON_TEMPLATE = """\
SendMessage規約: Redmine基盤通信
━━━━━━━━━━━━━━━━━
違反: {violation}
対処:
1. 詳細を Redmine チケットコメントに記載 (add_issue_comment_tool)
2. SendMessage は "issue_{{id}} [ステータス]" 形式で再送
許可フォーマット例: "issue_6041 [完了]", "issue_6041 [要判断] スコープ外"\
"""


class SendMessageGuardHook(BaseHook):
    """SendMessage ツール使用時のメッセージ内容検査フック

    セッションマーカーは使用しない（毎回のSendMessageを検査するため）。
    """

    def __init__(self, debug: Optional[bool] = None):
        """初期化

        Args:
            debug: デバッグモードフラグ
        """
        super().__init__(debug=debug)
        self._config_manager = ConfigManager()
        self._guard_config = self._load_guard_config()

    def _load_guard_config(self) -> Dict[str, Any]:
        """sendmessage_guard 設定を読み込み

        config.yaml の sendmessage_guard セクションを取得。
        未定義の場合はデフォルト値を使用。

        Returns:
            ガード設定辞書
        """
        raw = self._config_manager.config.get("sendmessage_guard", {})
        config = {
            "enabled": raw.get("enabled", True),
            "pattern": raw.get("pattern", DEFAULT_PATTERN),
            "max_content_length": raw.get("max_content_length", DEFAULT_MAX_CONTENT_LENGTH),
            "exempt_types": raw.get("exempt_types", DEFAULT_EXEMPT_TYPES),
        }
        # block_message: 設定されていればカスタムテンプレートを使用
        if "block_message" in raw:
            config["block_message"] = raw["block_message"]
        return config

    # --- 判定ロジック（テスト容易性のためメソッド切り出し） ---

    def is_target_tool(self, tool_name: str) -> bool:
        """SendMessage ツールかどうかを判定

        Args:
            tool_name: ツール名

        Returns:
            SendMessage ツールの場合 True
        """
        return tool_name == "SendMessage"

    def is_exempt_type(self, message_type: str) -> bool:
        """免除対象メッセージタイプかどうかを判定

        Args:
            message_type: メッセージタイプ

        Returns:
            免除対象の場合 True
        """
        return message_type in self._guard_config["exempt_types"]

    def validate_content(self, content: str) -> Dict[str, Any]:
        """メッセージ内容を検証

        Args:
            content: メッセージ内容

        Returns:
            {"valid": bool, "violation": str or None}
        """
        pattern = self._guard_config["pattern"]
        max_length = self._guard_config["max_content_length"]

        # パターン不一致チェック
        if not re.search(pattern, content):
            return {
                "valid": False,
                "violation": "issue_idが含まれていない",
            }

        # 文字数超過チェック
        if len(content) > max_length:
            return {
                "valid": False,
                "violation": f"文字数超過（{len(content)}/{max_length}文字）。詳細はRedmineに記載してください",
            }

        return {"valid": True, "violation": None}

    # --- BaseHook 抽象メソッドの実装 ---

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """処理対象かどうかを判定

        1. tool_name が SendMessage でなければ False
        2. tool_input.type が exempt_types に含まれれば False
        3. それ以外 True

        Args:
            input_data: 入力データ

        Returns:
            処理対象の場合 True
        """
        tool_name = input_data.get("tool_name", "")
        if not self.is_target_tool(tool_name):
            return False

        tool_input = input_data.get("tool_input", {})
        message_type = tool_input.get("type", "")
        if self.is_exempt_type(message_type):
            self.log_debug(f"Exempt type: {message_type}")
            return False

        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """メッセージ内容を検査し、規約違反をブロック

        Args:
            input_data: 入力データ

        Returns:
            decision と reason を含む辞書
        """
        tool_input = input_data.get("tool_input", {})
        content = tool_input.get("content", "")

        result = self.validate_content(content)

        if not result["valid"]:
            # block_message テンプレート: config指定があればそちらを使用
            template = self._guard_config.get(
                "block_message", DEFAULT_BLOCK_REASON_TEMPLATE
            )
            reason = template.format(
                violation=result["violation"],
                pattern=self._guard_config["pattern"],
                max_length=self._guard_config["max_content_length"],
            )
            self.log_info(f"BLOCK: {result['violation']}")
            return {"decision": "block", "reason": reason}

        self.log_debug(f"APPROVE: content validated")
        return {"decision": "approve", "reason": ""}

    # --- run() オーバーライド ---

    def run(self) -> int:
        """フックのメインエントリーポイント

        BaseHook.run() のセッションマーカー処理をスキップする簡略版。
        毎回の SendMessage を検査するためマーカーは不要。

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

        from shared.permission_mode import PermissionModeBehavior
        self._current_permission_mode_behavior: Optional[PermissionModeBehavior] = None

        try:
            input_data = self.read_input()
            if not input_data:
                self.log_debug("No input data, exiting")
                return ExitCode.SUCCESS

            # permission_mode によるスキップ判定
            should_skip, behavior = self.should_skip_by_permission_mode(input_data)
            self._current_permission_mode_behavior = behavior
            if should_skip:
                self.log_info(f"Skipping due to permission_mode behavior: {behavior}")
                return ExitCode.SUCCESS

            # 処理対象チェック（セッションマーカーチェックなし）
            if not self.should_process(input_data):
                self.log_debug("Not a target for processing, skipping")
                return ExitCode.SUCCESS

            # 処理実行
            result = self.process(input_data)

            # WARN_ONLY モード: block を allow に変換
            decision = result["decision"]
            if behavior == PermissionModeBehavior.WARN_ONLY and decision == "block":
                self.log_info("Converting block to allow due to WARN_ONLY mode")
                decision = "approve"
                original_reason = result.get("reason", "")
                result["reason"] = f"[WARN_ONLY] {original_reason}" if original_reason else "[WARN_ONLY]"

            if self.output_response(decision, result.get("reason", "")):
                self._log_hook_end(decision=decision, reason=result.get("reason", ""))
                return ExitCode.SUCCESS
            else:
                self._log_hook_end(decision="output_error")
                return ExitCode.ERROR

        except Exception as e:
            self.log_error(f"Unexpected error in run", error=str(e))
            self._log_hook_end(decision="error")
            return ExitCode.ERROR


def main():
    """メインエントリーポイント"""
    hook = SendMessageGuardHook(debug=False)
    sys.exit(hook.run())


if __name__ == "__main__":
    main()
