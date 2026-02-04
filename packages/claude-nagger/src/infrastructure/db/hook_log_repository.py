"""HookLogRepository - hook実行ログの記録・照会"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from domain.models.records import HookLogRecord
from infrastructure.db.nagger_state_db import NaggerStateDB


class HookLogRepository:
    """hook実行ログの記録・照会。監査・メトリクス用。"""

    def __init__(self, db: NaggerStateDB):
        """初期化

        Args:
            db: NaggerStateDBインスタンス
        """
        self._db = db

    def log(
        self,
        session_id: str,
        hook_name: str,
        event_type: str,
        agent_id: str = None,
        result: str = None,
        details: dict = None,
        duration_ms: int = None,
    ) -> None:
        """hook実行を記録

        INSERT INTO hook_log (session_id, hook_name, event_type, agent_id,
                              timestamp, result, details, duration_ms)
        - timestamp = 現在時刻(ISO8601 UTC)
        - details は json.dumps() して TEXT として保存（Noneなら NULL）

        Args:
            session_id: セッションID
            hook_name: フック名
            event_type: イベントタイプ
            agent_id: エージェントID（オプション）
            result: 結果（オプション）
            details: 詳細情報（辞書、オプション）
            duration_ms: 実行時間（ミリ秒、オプション）
        """
        now = datetime.now(timezone.utc).isoformat()

        # detailsはjson.dumps()してTEXTとして保存（Noneならそのまま）
        details_json = json.dumps(details, ensure_ascii=False) if details is not None else None

        self._db.conn.execute(
            """
            INSERT INTO hook_log
            (session_id, hook_name, event_type, agent_id, timestamp, result, details, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, hook_name, event_type, agent_id, now, result, details_json, duration_ms),
        )
        self._db.conn.commit()

    def get_recent(self, session_id: str, limit: int = 50) -> List[HookLogRecord]:
        """直近ログ取得

        ORDER BY timestamp DESC LIMIT ?
        detailsカラムはそのまま文字列として返す（呼び出し側でjson.loads()必要なら行う）

        Args:
            session_id: セッションID
            limit: 取得件数上限（デフォルト50）

        Returns:
            HookLogRecordのリスト（新しい順）
        """
        cursor = self._db.conn.execute(
            """
            SELECT id, session_id, hook_name, event_type, agent_id,
                   timestamp, result, details, duration_ms
            FROM hook_log
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (session_id, limit),
        )
        rows = cursor.fetchall()

        return [
            HookLogRecord(
                id=row[0],
                session_id=row[1],
                hook_name=row[2],
                event_type=row[3],
                agent_id=row[4],
                timestamp=row[5],
                result=row[6],
                details=row[7],
                duration_ms=row[8],
            )
            for row in rows
        ]

    def get_stats(self, session_id: str) -> dict:
        """統計情報

        以下の形式で返す:
        {
            'total_count': int,
            'by_hook': {hook_name: count, ...},
            'by_event': {event_type: count, ...},
            'avg_duration_ms': float or None
        }

        Args:
            session_id: セッションID

        Returns:
            統計情報辞書
        """
        # 総件数
        cursor = self._db.conn.execute(
            "SELECT COUNT(*) FROM hook_log WHERE session_id = ?",
            (session_id,),
        )
        row = cursor.fetchone()
        total_count = row[0] if row else 0

        # hook_name別カウント
        cursor = self._db.conn.execute(
            """
            SELECT hook_name, COUNT(*) as cnt
            FROM hook_log
            WHERE session_id = ?
            GROUP BY hook_name
            """,
            (session_id,),
        )
        by_hook = {row[0]: row[1] for row in cursor.fetchall()}

        # event_type別カウント
        cursor = self._db.conn.execute(
            """
            SELECT event_type, COUNT(*) as cnt
            FROM hook_log
            WHERE session_id = ?
            GROUP BY event_type
            """,
            (session_id,),
        )
        by_event = {row[0]: row[1] for row in cursor.fetchall()}

        # 平均実行時間（duration_msがNULLでないもののみ）
        cursor = self._db.conn.execute(
            """
            SELECT AVG(duration_ms)
            FROM hook_log
            WHERE session_id = ? AND duration_ms IS NOT NULL
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        avg_duration_ms = row[0] if row and row[0] is not None else None

        return {
            "total_count": total_count,
            "by_hook": by_hook,
            "by_event": by_event,
            "avg_duration_ms": avg_duration_ms,
        }
