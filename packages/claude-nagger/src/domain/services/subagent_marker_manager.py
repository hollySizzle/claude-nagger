"""subagentマーカー管理サービス

SubagentStart/Stopイベントに基づくマーカーファイルのCRUDを担当。
PreToolUse hookがsubagent活動中か否かを判定するための間接的伝達機構。
"""

import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class SubagentMarkerManager:
    """subagentマーカーファイルの作成・削除・照会を管理

    マーカーパス: {tempdir}/claude-nagger/{session_id}/subagents/{agent_id}.json
    並行subagent対応: agent_id単位の個別マーカー
    """

    BASE_DIR = Path(tempfile.gettempdir()) / "claude-nagger"

    def __init__(self, session_id: str):
        """初期化

        Args:
            session_id: 親セッションID
        """
        self.session_id = session_id
        self._subagents_dir = self.BASE_DIR / session_id / "subagents"

    @property
    def subagents_dir(self) -> Path:
        """subagentマーカーディレクトリ"""
        return self._subagents_dir

    def _get_marker_path(self, agent_id: str) -> Path:
        """agent_id に対応するマーカーファイルパスを取得"""
        return self._subagents_dir / f"{agent_id}.json"

    def create_marker(self, agent_id: str, agent_type: str) -> bool:
        """SubagentStartイベント時にマーカーファイルを作成

        Args:
            agent_id: サブエージェントID
            agent_type: サブエージェント種別（例: general-purpose, Explore, Bash）

        Returns:
            作成成功の場合True
        """
        try:
            self._subagents_dir.mkdir(parents=True, exist_ok=True)

            marker_data = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "session_id": self.session_id,
                "created_at": datetime.now().isoformat(),
            }

            marker_path = self._get_marker_path(agent_id)
            with open(marker_path, "w", encoding="utf-8") as f:
                json.dump(marker_data, f, ensure_ascii=False)

            logger.debug(f"Subagent marker created: {marker_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to create subagent marker: {e}")
            return False

    def delete_marker(self, agent_id: str) -> bool:
        """SubagentStopイベント時にマーカーファイルを削除

        Args:
            agent_id: サブエージェントID

        Returns:
            削除成功の場合True
        """
        try:
            marker_path = self._get_marker_path(agent_id)
            if marker_path.exists():
                marker_path.unlink()
                logger.debug(f"Subagent marker deleted: {marker_path}")
                return True
            else:
                logger.debug(f"Subagent marker not found (already deleted): {marker_path}")
                return True  # 冪等: 既に削除済みでもTrue
        except Exception as e:
            logger.error(f"Failed to delete subagent marker: {e}")
            return False

    def get_active_subagent(self) -> Optional[Dict[str, Any]]:
        """現在アクティブなsubagentの情報を1件取得（最新）

        並行subagentが複数いる場合は最後に開始されたものを返す。

        Returns:
            マーカーデータ辞書、アクティブなsubagentがない場合はNone
        """
        markers = self.get_all_active_subagents()
        if not markers:
            return None
        # 作成日時の降順で最新を返す
        return sorted(markers, key=lambda m: m.get("created_at", ""), reverse=True)[0]

    def get_all_active_subagents(self) -> List[Dict[str, Any]]:
        """全アクティブsubagentのマーカーデータを取得

        Returns:
            マーカーデータ辞書のリスト
        """
        markers = []
        if not self._subagents_dir.exists():
            return markers

        for marker_file in self._subagents_dir.glob("*.json"):
            try:
                with open(marker_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    markers.append(data)
            except Exception as e:
                logger.warning(f"Failed to read subagent marker {marker_file}: {e}")

        return markers

    def is_subagent_active(self) -> bool:
        """subagentが1つ以上アクティブか判定

        Returns:
            アクティブなsubagentがある場合True
        """
        if not self._subagents_dir.exists():
            return False
        return any(self._subagents_dir.glob("*.json"))

    def get_active_count(self) -> int:
        """アクティブなsubagent数を取得

        Returns:
            アクティブなsubagent数
        """
        if not self._subagents_dir.exists():
            return 0
        return len(list(self._subagents_dir.glob("*.json")))

    def cleanup(self) -> int:
        """全subagentマーカーを削除（セッション終了時等）

        Returns:
            削除されたマーカー数
        """
        count = 0
        if not self._subagents_dir.exists():
            return count

        for marker_file in self._subagents_dir.glob("*.json"):
            try:
                marker_file.unlink()
                count += 1
            except Exception as e:
                logger.warning(f"Failed to delete marker {marker_file}: {e}")

        return count
