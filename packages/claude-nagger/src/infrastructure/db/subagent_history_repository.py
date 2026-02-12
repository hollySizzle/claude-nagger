"""SubagentHistoryRepository - subagentライフサイクル履歴の参照（issue_6089）"""

from typing import List, Optional

from infrastructure.db.nagger_state_db import NaggerStateDB


class SubagentHistoryRepository:
    """subagent_historyテーブルの参照操作。"""

    def __init__(self, db: NaggerStateDB):
        """初期化

        Args:
            db: NaggerStateDBインスタンス
        """
        self._db = db

    def get_by_session(self, session_id: str) -> List[dict]:
        """セッション内の全subagent履歴を取得

        Args:
            session_id: セッションID

        Returns:
            履歴レコードのリスト（dict形式）
        """
        cursor = self._db.conn.execute(
            """
            SELECT id, agent_id, session_id, agent_type, role, role_source,
                   leader_transcript_path, started_at, stopped_at, issue_id
            FROM subagent_history
            WHERE session_id = ?
            ORDER BY started_at ASC
            """,
            (session_id,),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_by_agent(self, agent_id: str) -> List[dict]:
        """特定agentの履歴を取得

        Args:
            agent_id: エージェントID

        Returns:
            履歴レコードのリスト（dict形式）
        """
        cursor = self._db.conn.execute(
            """
            SELECT id, agent_id, session_id, agent_type, role, role_source,
                   leader_transcript_path, started_at, stopped_at, issue_id
            FROM subagent_history
            WHERE agent_id = ?
            ORDER BY started_at ASC
            """,
            (agent_id,),
        )
        return [self._row_to_dict(row) for row in cursor.fetchall()]


    def get_previous_session_id(self, current_session_id: str) -> Optional[str]:
        """現在セッションの直前セッションIDを取得

        current_session_idのsubagent_historyレコードの最小started_atより前の、
        別セッションの最新session_idを返す。
        現在セッションにレコードがない場合は全体の最新セッションIDを返す。

        Args:
            current_session_id: 現在のセッションID

        Returns:
            前セッションID。履歴がなければNone
        """
        # 現在セッションの最小started_atを取得
        cursor = self._db.conn.execute(
            "SELECT MIN(started_at) FROM subagent_history WHERE session_id = ?",
            (current_session_id,),
        )
        row = cursor.fetchone()
        min_started_at = row[0] if row else None

        if min_started_at:
            # 現在セッションより前の、別セッションの最新session_idを取得
            cursor = self._db.conn.execute(
                """
                SELECT session_id FROM subagent_history
                WHERE session_id != ? AND started_at < ?
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (current_session_id, min_started_at),
            )
        else:
            # 現在セッションにレコードがない場合、全体の最新セッションIDを返す
            cursor = self._db.conn.execute(
                """
                SELECT session_id FROM subagent_history
                ORDER BY started_at DESC
                LIMIT 1
                """,
            )

        row = cursor.fetchone()
        return row[0] if row else None

    def get_stats(self, session_id: str = None) -> dict:
        """統計情報: role別件数、平均所要時間等

        Args:
            session_id: セッションID（指定時はそのセッションのみ、未指定時は全体）

        Returns:
            統計情報dict。キー:
            - total: 総件数
            - by_role: role別件数 {role: count}
            - avg_duration_seconds: 平均所要時間（秒）。stopped_atがNULLのレコードは除外
        """
        # role別件数
        if session_id:
            cursor = self._db.conn.execute(
                """
                SELECT role, COUNT(*) FROM subagent_history
                WHERE session_id = ?
                GROUP BY role
                """,
                (session_id,),
            )
        else:
            cursor = self._db.conn.execute(
                "SELECT role, COUNT(*) FROM subagent_history GROUP BY role"
            )
        by_role = {}
        total = 0
        for row in cursor.fetchall():
            role_key = row[0] if row[0] is not None else "(none)"
            by_role[role_key] = row[1]
            total += row[1]

        # 平均所要時間（stopped_atがあるレコードのみ）
        # SQLiteのjulianday()で秒単位の差分を計算
        if session_id:
            cursor = self._db.conn.execute(
                """
                SELECT AVG(
                    (julianday(stopped_at) - julianday(started_at)) * 86400
                )
                FROM subagent_history
                WHERE session_id = ? AND stopped_at IS NOT NULL
                """,
                (session_id,),
            )
        else:
            cursor = self._db.conn.execute(
                """
                SELECT AVG(
                    (julianday(stopped_at) - julianday(started_at)) * 86400
                )
                FROM subagent_history
                WHERE stopped_at IS NOT NULL
                """
            )
        avg_row = cursor.fetchone()
        avg_duration = avg_row[0] if avg_row and avg_row[0] is not None else None

        return {
            "total": total,
            "by_role": by_role,
            "avg_duration_seconds": avg_duration,
        }

    @staticmethod
    def _row_to_dict(row: tuple) -> dict:
        """SQLite行をdict変換"""
        return {
            "id": row[0],
            "agent_id": row[1],
            "session_id": row[2],
            "agent_type": row[3],
            "role": row[4],
            "role_source": row[5],
            "leader_transcript_path": row[6],
            "started_at": row[7],
            "stopped_at": row[8],
            "issue_id": row[9],
        }
