"""leader行動制約フック

subagentアクティブ時にleaderのソースコード直接操作をブロックし、
subagentへの委譲を強制するPreToolUseフック。
"""

import fnmatch
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.hooks.base_hook import BaseHook, ExitCode
from infrastructure.config.config_manager import ConfigManager
from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.subagent_repository import SubagentRepository
from shared.permission_mode import PermissionModeBehavior

# デフォルト設定
DEFAULT_BLOCKED_TOOLS: List[str] = ["Read", "Edit", "Write", "Grep", "Glob"]
DEFAULT_SOURCE_PATHS: List[str] = ["src/", "tests/"]
DEFAULT_EXEMPT_PATTERNS: List[str] = [
    "*.md",
    "config.yaml",
    ".claude/",
    "docs/",
    "settings.json",
]
DEFAULT_BLOCK_MESSAGE = (
    "ソースコード操作はsubagentに委譲してください。\n"
    "調査→researcher、実装→coder、テスト→tester"
)


class LeaderConstraintHook(BaseHook):
    """subagentアクティブ時のleader直接作業ブロックフック

    セッションマーカーは使用しない（毎回のツール呼び出しを検査するため）。
    """

    def __init__(self, debug: Optional[bool] = None):
        """初期化

        Args:
            debug: デバッグモードフラグ
        """
        super().__init__(debug=debug)
        self._config_manager = ConfigManager()
        self._constraint_config = self._load_constraint_config()

    def _load_constraint_config(self) -> Dict[str, Any]:
        """leader_constraint 設定を読み込み

        config.yaml の leader_constraint セクションを取得。
        未定義の場合はデフォルト値を使用。

        Returns:
            制約設定辞書
        """
        raw = self._config_manager.config.get("leader_constraint", {})
        return {
            "enabled": raw.get("enabled", True),
            "blocked_tools": raw.get("blocked_tools", DEFAULT_BLOCKED_TOOLS),
            "source_paths": raw.get("source_paths", DEFAULT_SOURCE_PATHS),
            "exempt_patterns": raw.get("exempt_patterns", DEFAULT_EXEMPT_PATTERNS),
            "block_message": raw.get("block_message", DEFAULT_BLOCK_MESSAGE),
        }

    # --- 判定ロジック ---

    def is_target_tool(self, tool_name: str) -> bool:
        """ブロック対象ツールかどうかを判定

        Args:
            tool_name: ツール名

        Returns:
            ブロック対象ツールの場合 True
        """
        return tool_name in self._constraint_config["blocked_tools"]

    def _extract_path(self, tool_name: str, tool_input: Dict[str, Any]) -> Optional[str]:
        """ツール入力からファイルパスを抽出

        Args:
            tool_name: ツール名
            tool_input: ツール入力データ

        Returns:
            抽出されたパス（取得できない場合None）
        """
        # Read/Edit/Write: file_path
        path = tool_input.get("file_path", "")
        if path:
            return path
        # Grep/Glob: path
        path = tool_input.get("path", "")
        if path:
            return path
        # Grep/Globのpatternのみ（pathなし）の場合はNone
        return None

    def is_source_path(self, file_path: str, cwd: str = "") -> bool:
        """ソースコードパスかどうかを判定

        相対パス・絶対パスの両方に対応。

        Args:
            file_path: 対象ファイルパス
            cwd: カレントワーキングディレクトリ

        Returns:
            ソースコードパスの場合 True
        """
        source_paths = self._constraint_config["source_paths"]

        # 絶対パスの場合、cwdからの相対パスに変換して判定
        if file_path.startswith("/") and cwd:
            try:
                rel_path = str(Path(file_path).relative_to(cwd))
            except ValueError:
                # cwdの外のパスは対象外
                return False
        else:
            rel_path = file_path

        for sp in source_paths:
            if rel_path.startswith(sp):
                return True

        return False

    def is_exempt_path(self, file_path: str, cwd: str = "") -> bool:
        """免除パスかどうかを判定

        Args:
            file_path: 対象ファイルパス
            cwd: カレントワーキングディレクトリ

        Returns:
            免除対象の場合 True
        """
        exempt_patterns = self._constraint_config["exempt_patterns"]

        # 絶対パスの場合、cwdからの相対パスに変換
        if file_path.startswith("/") and cwd:
            try:
                rel_path = str(Path(file_path).relative_to(cwd))
            except ValueError:
                rel_path = file_path
        else:
            rel_path = file_path

        # ファイル名部分も取得
        basename = Path(file_path).name

        for pattern in exempt_patterns:
            # ディレクトリパターン（末尾/）: パスの先頭一致
            if pattern.endswith("/"):
                if rel_path.startswith(pattern) or file_path.startswith(pattern):
                    return True
            # グロブパターン: ファイル名マッチ
            elif fnmatch.fnmatch(basename, pattern):
                return True
            # 完全一致
            elif basename == pattern or rel_path == pattern:
                return True

        return False

    def has_active_subagents(self, session_id: str) -> bool:
        """アクティブなsubagentが存在するかを判定

        Args:
            session_id: セッションID

        Returns:
            アクティブsubagentが存在する場合 True
        """
        try:
            db = NaggerStateDB(NaggerStateDB.resolve_db_path())
            repo = SubagentRepository(db)
            result = repo.is_any_active(session_id)
            db.close()
            return result
        except Exception as e:
            self.log_error(f"SubagentRepository確認失敗: {e}")
            return False

    # --- BaseHook 抽象メソッドの実装 ---

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """処理対象かどうかを判定

        1. leader_constraint.enabled が false なら False
        2. tool_name がブロック対象でなければ False
        3. subagentがアクティブでなければ False
        4. パスが免除対象なら False
        5. パスがソースコード内なら True

        Args:
            input_data: 入力データ

        Returns:
            処理対象の場合 True
        """
        # 設定で無効化
        if not self._constraint_config["enabled"]:
            self.log_debug("leader_constraint は無効化されています")
            return False

        # ツール判定
        tool_name = input_data.get("tool_name", "")
        if not self.is_target_tool(tool_name):
            return False

        # セッションID取得
        session_id = input_data.get("session_id", "")
        if not session_id:
            self.log_debug("session_idなし、スキップ")
            return False

        # subagentアクティブ判定
        if not self.has_active_subagents(session_id):
            self.log_debug("アクティブsubagentなし、スキップ")
            return False

        # パス抽出
        tool_input = input_data.get("tool_input", {})
        cwd = input_data.get("cwd", "")
        file_path = self._extract_path(tool_name, tool_input)

        if not file_path:
            # パス情報なし（Grep/Globでpath未指定等）はソースコード全体対象とみなしブロック
            self.log_info(f"パス情報なし: {tool_name} をブロック対象と判定")
            return True

        # 免除パス判定
        if self.is_exempt_path(file_path, cwd):
            self.log_debug(f"免除パス: {file_path}")
            return False

        # ソースコードパス判定
        if self.is_source_path(file_path, cwd):
            self.log_info(f"ソースコード操作検出: {tool_name} -> {file_path}")
            return True

        return False

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """ブロックメッセージを返す

        Args:
            input_data: 入力データ

        Returns:
            decision と reason を含む辞書
        """
        tool_name = input_data.get("tool_name", "")
        tool_input = input_data.get("tool_input", {})
        file_path = self._extract_path(tool_name, tool_input) or "(パス不明)"

        self.log_info(f"BLOCK: leader直接操作 {tool_name} -> {file_path}")

        return {
            "decision": "block",
            "reason": self._constraint_config["block_message"],
        }

    # --- run() オーバーライド ---

    def run(self) -> int:
        """フックのメインエントリーポイント

        BaseHook.run() のセッションマーカー処理をスキップする簡略版。
        毎回のツール呼び出しを検査するためマーカーは不要。

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
