"""SessionStart[compact]イベント処理フック

compact検知時にマーカーファイルをリセットし、既存フローを再発火させる。
"""

from pathlib import Path
from typing import Any, Dict

from .base_hook import BaseHook


class CompactDetectedHook(BaseHook):
    """compact検知フック
    
    SessionStart[compact]イベントを処理し、マーカーファイルをリセット。
    これにより次のPreToolUseで既存フローが再発火する。
    """

    def __init__(self):
        """初期化"""
        super().__init__(debug=True)

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
        """compact検知時の処理: マーカーファイルをリセット
        
        Args:
            input_data: 入力データ
            
        Returns:
            処理結果
        """
        session_id = input_data.get("session_id", "")
        
        self.log_info(f"🎯 Processing compact for session: {session_id}")
        
        # マーカーファイルをリセット
        reset_count = self._reset_marker_files(session_id)
        
        self.log_info(f"✅ Reset {reset_count} marker files")
        
        return {"decision": "approve", "reason": ""}

    def _reset_marker_files(self, session_id: str) -> int:
        """マーカーファイルをリセット（削除）
        
        Args:
            session_id: セッションID
            
        Returns:
            削除したファイル数
        """
        temp_dir = Path("/tmp")
        reset_count = 0
        
        # リセット対象のパターン
        patterns = [
            f"claude_session_startup_*{session_id}*",  # SessionStartupHook
            f"claude_rule_*{session_id}*",              # 規約リマインダー
            f"claude_cmd_{session_id}_*",               # コマンド規約
            f"claude_hook_*_session_{session_id}",      # BaseHook汎用マーカー
        ]
        
        for pattern in patterns:
            for marker_path in temp_dir.glob(pattern):
                try:
                    marker_path.unlink()
                    self.log_info(f"🗑️ Deleted marker: {marker_path.name}")
                    reset_count += 1
                except Exception as e:
                    self.log_error(f"Failed to delete {marker_path}: {e}")
        
        return reset_count


def main():
    """エントリーポイント"""
    hook = CompactDetectedHook()
    exit(hook.run())


if __name__ == "__main__":
    main()
