"""permission_mode 定義モジュール

Claude Code Hooks API の permission_mode フィールドに対応
"""

from enum import Enum


class PermissionMode(str, Enum):
    """Claude Code 許可モード

    Claude Code Hooks API の permission_mode フィールド値:
    - default: 通常モード（ユーザー確認あり）
    - plan: プランモード（計画段階）
    - acceptEdits: 編集自動承認モード
    - dontAsk: 確認なしモード
    - bypassPermissions: 許可バイパスモード

    参照: docs/apis/ClaudeCodeHooks.md
    """
    DEFAULT = "default"
    PLAN = "plan"
    ACCEPT_EDITS = "acceptEdits"
    DONT_ASK = "dontAsk"
    BYPASS_PERMISSIONS = "bypassPermissions"
    UNKNOWN = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "PermissionMode":
        """文字列からPermissionModeを取得

        Args:
            value: permission_mode文字列

        Returns:
            対応するPermissionMode（不明な場合はUNKNOWN）
        """
        for mode in cls:
            if mode.value == value:
                return mode
        return cls.UNKNOWN


class PermissionModeBehavior(str, Enum):
    """permission_mode に対する挙動

    各permission_modeでフックがどう動作するか:
    - NORMAL: 通常処理（ブロック可能）
    - SKIP: 全処理スキップ（何もしない）
    - WARN_ONLY: 警告のみ（ブロックしない）
    - LOG_ONLY: ログのみ（出力なし）
    """
    NORMAL = "normal"
    SKIP = "skip"
    WARN_ONLY = "warn_only"
    LOG_ONLY = "log_only"


# デフォルトのモード別挙動マッピング
DEFAULT_MODE_BEHAVIORS: dict[PermissionMode, PermissionModeBehavior] = {
    PermissionMode.DEFAULT: PermissionModeBehavior.NORMAL,
    PermissionMode.PLAN: PermissionModeBehavior.NORMAL,
    PermissionMode.ACCEPT_EDITS: PermissionModeBehavior.NORMAL,
    PermissionMode.DONT_ASK: PermissionModeBehavior.WARN_ONLY,
    PermissionMode.BYPASS_PERMISSIONS: PermissionModeBehavior.SKIP,
    PermissionMode.UNKNOWN: PermissionModeBehavior.NORMAL,
}
