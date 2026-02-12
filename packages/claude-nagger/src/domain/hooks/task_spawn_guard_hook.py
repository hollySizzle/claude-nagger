"""Task spawn ガードフック

Task ツール使用時に subagent_type を検査し、
ticket-tasuki:* プレフィックスの直接起動をブロックする PreToolUse hook。
Agent Teams（TeamCreate + SendMessage）経由での起動を誘導する。
"""

import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional

sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.hooks.base_hook import BaseHook, ExitCode
from infrastructure.config.config_manager import ConfigManager

# デフォルト設定
DEFAULT_BLOCKED_PREFIX = "ticket-tasuki:"

# block reason テンプレート
DEFAULT_BLOCK_REASON_TEMPLATE = """\
Task spawn規約: ticket-tasuki プラグインの直接起動禁止
━━━━━━━━━━━━━━━━━
検出: subagent_type="{subagent_type}"
対処:
1. Agent Teams（TeamCreate + SendMessage）経由で起動してください
2. Task ツールでの ticket-tasuki:* subagent_type 直接指定は禁止です\
"""


class TaskSpawnGuardHook(BaseHook):
    """Task ツール使用時の subagent_type 検査フック

    セッションマーカーは使用しない（毎回のTaskを検査するため）。
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
        """task_spawn_guard 設定を読み込み

        config.yaml の task_spawn_guard セクションを取得。
        未定義の場合はデフォルト値を使用。

        Returns:
            ガード設定辞書
        """
        raw = self._config_manager.config.get("task_spawn_guard", {})
        config = {
            "enabled": raw.get("enabled", True),
            "blocked_prefix": raw.get("blocked_prefix", DEFAULT_BLOCKED_PREFIX),
        }
        # block_message: 設定されていればカスタムテンプレートを使用
        if "block_message" in raw:
            config["block_message"] = raw["block_message"]
        return config

    # --- 判定ロジック（テスト容易性のためメソッド切り出し） ---

    def is_target_tool(self, tool_name: str) -> bool:
        """Task ツールかどうかを判定

        Args:
            tool_name: ツール名

        Returns:
            Task ツールの場合 True
        """
        return tool_name == "Task"

    def is_blocked_subagent_type(self, subagent_type: str) -> bool:
        """ブロック対象の subagent_type かどうかを判定

        Args:
            subagent_type: サブエージェントタイプ

        Returns:
            ブロック対象の場合 True
        """
        prefix = self._guard_config["blocked_prefix"]
        return subagent_type.startswith(prefix)

    # --- BaseHook 抽象メソッドの実装 ---

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """処理対象かどうかを判定

        1. tool_name が Task でなければ False
        2. それ以外 True

        Args:
            input_data: 入力データ

        Returns:
            処理対象の場合 True
        """
        tool_name = input_data.get("tool_name", "")
        if not self.is_target_tool(tool_name):
            return False

        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """subagent_type を検査し、ticket-tasuki:* をブロック

        Args:
            input_data: 入力データ

        Returns:
            decision と reason を含む辞書
        """
        tool_input = input_data.get("tool_input", {})
        subagent_type = tool_input.get("subagent_type", "")

        if self.is_blocked_subagent_type(subagent_type):
            # block_message テンプレート: config指定があればそちらを使用
            template = self._guard_config.get(
                "block_message", DEFAULT_BLOCK_REASON_TEMPLATE
            )
            reason = template.format(subagent_type=subagent_type)
            self.log_info(f"BLOCK: subagent_type={subagent_type}")
            return {"decision": "block", "reason": reason}

        self.log_debug(f"APPROVE: subagent_type={subagent_type}")
        return {"decision": "approve", "reason": ""}

    # --- run() オーバーライド ---

    def run(self) -> int:
        """フックのメインエントリーポイント

        BaseHook.run() のセッションマーカー処理をスキップする簡略版。
        毎回の Task を検査するためマーカーは不要。

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
    """CLI エントリーポイント"""
    hook = TaskSpawnGuardHook()
    sys.exit(hook.run())


if __name__ == "__main__":
    main()
