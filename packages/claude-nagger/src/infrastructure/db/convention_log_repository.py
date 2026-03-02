"""ConventionLogRepository - conventions判定結果の永続化"""

import logging
from typing import Optional

from infrastructure.db.nagger_state_db import NaggerStateDB

logger = logging.getLogger(__name__)


class ConventionLogRepository:
    """conventions判定結果（deny/block/warn）をconvention_logテーブルに記録"""

    def __init__(self, db: NaggerStateDB):
        """初期化

        Args:
            db: NaggerStateDBインスタンス
        """
        self._db = db

    def insert_log(
        self,
        session_id: Optional[str],
        tool_name: str,
        convention_type: str,
        rule_name: str,
        severity: str,
        decision: str,
        reason: Optional[str] = None,
        scope: Optional[str] = None,
        caller_role: Optional[str] = None,
    ) -> None:
        """conventions判定結果を記録

        approve判定は記録しない（呼び出し側で制御）。

        Args:
            session_id: セッションID
            tool_name: 対象ツール名
            convention_type: 規約種別（file/command/mcp）
            rule_name: ルール名
            severity: 重要度（deny/block/warn）
            decision: 最終判定
            reason: 判定理由（オプション）
            scope: scope値（NULLは全agent対象）
            caller_role: 判定時のcaller role（オプション）
        """
        self._db.conn.execute(
            """
            INSERT INTO convention_log
            (session_id, tool_name, convention_type, rule_name,
             severity, decision, reason, scope, caller_role)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                tool_name,
                convention_type,
                rule_name,
                severity,
                decision,
                reason,
                scope,
                caller_role,
            ),
        )
        self._db.conn.commit()
