"""フック応答データクラス

Claude Code Hooks API の hookSpecificOutput 形式に対応した型定義。
IDE補完とバリデーションを提供する。
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional, Literal


# 許可決定の型
PermissionDecision = Literal["allow", "deny", "ask"]

# イベント名の型
HookEventName = Literal[
    "PreToolUse",
    "PostToolUse",
    "PermissionRequest",
    "Notification",
    "Stop",
    "SubagentStop",
    "UserPromptSubmit",
    "PreCompact",
    "SessionStart",
    "SessionEnd",
]


@dataclass
class HookResponse:
    """フック応答データクラス

    Claude Code Hooks API の hookSpecificOutput 形式を構造化。

    Attributes:
        hook_event_name: フックイベント名（PreToolUse等）
        permission_decision: 許可決定（allow/deny/ask）
        permission_decision_reason: 理由（deny/askではClaudeへ、allowではユーザーへ表示）
        updated_input: ツール入力の修正（PreToolUse/PermissionRequest用）
        additional_context: Claudeへの追加コンテキスト
        continue_processing: 処理続行フラグ（False=停止）
        stop_reason: 停止理由（continue_processing=False時、ユーザーへ表示）
        suppress_output: verbose モードでの出力抑制

    Examples:
        # 許可（シンプル）
        HookResponse(permission_decision="allow")

        # 拒否（理由付き）
        HookResponse(
            permission_decision="deny",
            permission_decision_reason="危険なコマンドです"
        )

        # ユーザー確認要求
        HookResponse(
            permission_decision="ask",
            permission_decision_reason="rm コマンドの確認"
        )

        # 入力修正して許可
        HookResponse(
            permission_decision="allow",
            updated_input={"command": "echo 'safe command'"}
        )

        # コンテキスト注入
        HookResponse(
            permission_decision="allow",
            additional_context="このプロジェクトでは..."
        )
    """
    # 必須フィールド
    hook_event_name: HookEventName = "PreToolUse"
    permission_decision: PermissionDecision = "allow"

    # オプションフィールド
    permission_decision_reason: Optional[str] = None
    updated_input: Optional[Dict[str, Any]] = None
    additional_context: Optional[str] = None
    continue_processing: Optional[bool] = None  # 'continue'はPython予約語
    stop_reason: Optional[str] = None
    suppress_output: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        """hookSpecificOutput形式の辞書に変換

        Returns:
            Claude Code Hooks API に準拠したJSON出力用辞書
        """
        hook_specific_output: Dict[str, Any] = {
            "hookEventName": self.hook_event_name,
            "permissionDecision": self.permission_decision,
        }

        if self.permission_decision_reason:
            hook_specific_output["permissionDecisionReason"] = self.permission_decision_reason

        if self.updated_input is not None:
            hook_specific_output["updatedInput"] = self.updated_input

        if self.additional_context is not None:
            hook_specific_output["additionalContext"] = self.additional_context

        result: Dict[str, Any] = {
            "hookSpecificOutput": hook_specific_output
        }

        # トップレベルフィールド
        if self.continue_processing is not None:
            result["continue"] = self.continue_processing

        if self.stop_reason is not None:
            result["stopReason"] = self.stop_reason

        if self.suppress_output is not None:
            result["suppressOutput"] = self.suppress_output

        return result

    @classmethod
    def allow(
        cls,
        reason: str = "",
        updated_input: Optional[Dict[str, Any]] = None,
        additional_context: Optional[str] = None,
        hook_event_name: HookEventName = "PreToolUse",
    ) -> "HookResponse":
        """許可応答を生成

        Args:
            reason: 許可理由（ユーザーに表示）
            updated_input: 入力修正（オプション）
            additional_context: 追加コンテキスト
            hook_event_name: イベント名

        Returns:
            許可設定済みHookResponse
        """
        return cls(
            hook_event_name=hook_event_name,
            permission_decision="allow",
            permission_decision_reason=reason if reason else None,
            updated_input=updated_input,
            additional_context=additional_context,
        )

    @classmethod
    def deny(
        cls,
        reason: str,
        hook_event_name: HookEventName = "PreToolUse",
    ) -> "HookResponse":
        """拒否応答を生成

        Args:
            reason: 拒否理由（Claudeに表示）
            hook_event_name: イベント名

        Returns:
            拒否設定済みHookResponse
        """
        return cls(
            hook_event_name=hook_event_name,
            permission_decision="deny",
            permission_decision_reason=reason,
        )

    @classmethod
    def ask(
        cls,
        reason: str,
        updated_input: Optional[Dict[str, Any]] = None,
        hook_event_name: HookEventName = "PreToolUse",
    ) -> "HookResponse":
        """ユーザー確認要求応答を生成

        Args:
            reason: 確認要求理由（ユーザーに表示）
            updated_input: 入力修正（確認画面に反映）
            hook_event_name: イベント名

        Returns:
            ユーザー確認要求設定済みHookResponse
        """
        return cls(
            hook_event_name=hook_event_name,
            permission_decision="ask",
            permission_decision_reason=reason,
            updated_input=updated_input,
        )
