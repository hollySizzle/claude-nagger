"""SessionStart[compact]イベント処理フック

compact検知時に履歴保存とClaudeへのリマインダー注入を行う。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .base_hook import BaseHook
from .hook_response import HookResponse


class CompactDetectedHook(BaseHook):
    """compact検知フック
    
    SessionStart[compact]イベントを処理し:
    - compact履歴を.claude-nagger/compact_history.jsonlに保存
    - additionalContextでClaudeにリマインダー注入
    """

    def __init__(self):
        """初期化"""
        super().__init__(debug=True)
        self.history_file = Path.cwd() / ".claude-nagger" / "compact_history.jsonl"

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """compact起源のSessionStartイベントのみ処理対象
        
        Args:
            input_data: 入力データ
            
        Returns:
            source="compact"の場合True
        """
        source = input_data.get("source", "")
        hook_event = input_data.get("hook_event_name", "")
        
        self.log_info(f"📋 CompactDetectedHook - source: {source}, event: {hook_event}")
        
        # compact起源のSessionStartのみ処理
        if source != "compact":
            self.log_info("❌ Not a compact source, skipping")
            return False
        
        self.log_info("🚀 Compact detected, processing")
        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """compact検知時の処理
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理結果（後方互換性のため辞書形式）
        """
        session_id = input_data.get("session_id", "")
        transcript_path = input_data.get("transcript_path", "")
        
        self.log_info(f"🎯 Processing compact for session: {session_id}")
        
        # compact履歴を保存
        self._save_compact_history(session_id, transcript_path)
        
        # リマインダーメッセージを構築
        reminder = self._build_reminder_message()
        
        # HookResponseでadditionalContextを注入
        response = HookResponse.allow(
            additional_context=reminder,
            hook_event_name="SessionStart",
        )
        
        self.log_info(f"✅ Compact processed, injecting reminder")
        self.exit_with_response(response)
        
        # exit_with_responseで終了するので到達しない（後方互換性のため残す）
        return {"decision": "approve", "reason": ""}

    def _save_compact_history(self, session_id: str, transcript_path: str) -> None:
        """compact履歴をJSONLに保存
        
        Args:
            session_id: セッションID
            transcript_path: transcriptパス
        """
        try:
            # ディレクトリ作成
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            
            # 履歴レコード作成
            record = {
                "timestamp": datetime.now().isoformat(),
                "session_id": session_id,
                "transcript_path": transcript_path,
            }
            
            # JSONL追記
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            
            self.log_info(f"📝 Saved compact history: {self.history_file}")
            
        except Exception as e:
            self.log_error(f"Failed to save compact history: {e}")

    def _build_reminder_message(self) -> str:
        """リマインダーメッセージを構築
        
        Returns:
            Claudeに注入するリマインダー文字列
        """
        return (
            "[COMPACT DETECTED] 会話がコンパクト化されました。\n"
            "重要なコンテキストが失われた可能性があります。\n"
            "必要に応じてユーザーに確認してください。"
        )


def main():
    """エントリーポイント"""
    hook = CompactDetectedHook()
    exit(hook.run())


if __name__ == "__main__":
    main()
