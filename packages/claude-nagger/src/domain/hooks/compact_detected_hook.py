"""SessionStart[compact]イベント処理フック

compact検知時にマーカーファイルをリネームし、既存フローを再発火させる。
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .base_hook import BaseHook, MarkerPatterns


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
        
        # マーカーファイルをリネーム（履歴保持）
        renamed_count = self._rename_markers_for_compact(session_id)
        
        self.log_info(f"✅ Renamed {renamed_count} marker files for compact")
        
        return {"decision": "approve", "reason": ""}

    def _rename_markers_for_compact(self, session_id: str) -> int:
        """マーカーファイルをcompact用にリネーム（履歴保持）
        
        Args:
            session_id: セッションID
            
        Returns:
            リネームしたファイル数
        """
        temp_dir = Path("/tmp")
        renamed_count = 0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # リネーム対象のパターン（MarkerPatternsから一元取得）
        patterns = MarkerPatterns.get_glob_patterns(session_id)
        
        for pattern in patterns:
            for marker_path in temp_dir.glob(pattern):
                # 既にexpiredファイルはスキップ
                if ".expired" in marker_path.name:
                    continue
                try:
                    expired_name = f"{marker_path.name}.expired_compact_{timestamp}"
                    expired_path = marker_path.parent / expired_name
                    marker_path.rename(expired_path)
                    self.log_info(f"🗃️ Renamed marker: {marker_path.name} -> {expired_name}")
                    renamed_count += 1
                except Exception as e:
                    self.log_error(f"Failed to rename {marker_path}: {e}")
        
        return renamed_count


def main():
    """エントリーポイント"""
    hook = CompactDetectedHook()
    exit(hook.run())


if __name__ == "__main__":
    main()
