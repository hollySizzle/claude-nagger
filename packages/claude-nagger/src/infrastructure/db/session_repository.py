"""SessionRepository - セッション処理状態の管理"""

from datetime import datetime, timezone
from typing import Optional

from domain.models.records import SessionRecord
from infrastructure.db.nagger_state_db import NaggerStateDB


class SessionRepository:
    """セッション処理状態の管理。現行BaseHookマーカーの代替。"""

    def __init__(self, db: NaggerStateDB):
        """初期化

        Args:
            db: NaggerStateDBインスタンス
        """
        self._db = db

    def register(self, session_id: str, hook_name: str, tokens: int = 0) -> None:
        """処理済みマーク

        INSERT OR REPLACE INTO sessions。
        created_at=現在時刻(ISO8601 UTC), status='active', last_tokens=tokens

        Args:
            session_id: セッションID
            hook_name: フック名
            tokens: トークン数（デフォルト0）
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.conn.execute(
            """
            INSERT OR REPLACE INTO sessions
            (session_id, hook_name, created_at, last_tokens, status, expired_at)
            VALUES (?, ?, ?, ?, 'active', NULL)
            """,
            (session_id, hook_name, now, tokens),
        )
        self._db.conn.commit()

    def is_processed(self, session_id: str, hook_name: str) -> bool:
        """処理済みか判定

        status='active'のレコードが存在すればTrue

        Args:
            session_id: セッションID
            hook_name: フック名

        Returns:
            処理済みならTrue
        """
        cursor = self._db.conn.execute(
            """
            SELECT 1 FROM sessions
            WHERE session_id = ? AND hook_name = ? AND status = 'active'
            """,
            (session_id, hook_name),
        )
        return cursor.fetchone() is not None

    def is_processed_context_aware(
        self,
        session_id: str,
        hook_name: str,
        current_tokens: int,
        threshold: int,
    ) -> bool:
        """トークン増加量ベースの判定

        1. SELECT from sessions WHERE session_id = ? AND hook_name = ? AND status = 'active'
        2. レコードなし -> return False
        3. current_tokens - last_tokens >= threshold -> expire() してreturn False
        4. それ以外 -> return True

        Args:
            session_id: セッションID
            hook_name: フック名
            current_tokens: 現在のトークン数
            threshold: トークン増加閾値

        Returns:
            処理済み（再処理不要）ならTrue
        """
        cursor = self._db.conn.execute(
            """
            SELECT last_tokens FROM sessions
            WHERE session_id = ? AND hook_name = ? AND status = 'active'
            """,
            (session_id, hook_name),
        )
        row = cursor.fetchone()

        # レコードなし
        if row is None:
            return False

        last_tokens = row[0]

        # トークン増加量が閾値以上なら期限切れ
        if current_tokens - last_tokens >= threshold:
            self.expire(session_id, hook_name, reason="expired")
            return False

        return True

    def expire(self, session_id: str, hook_name: str, reason: str = "expired") -> None:
        """セッションを期限切れに

        UPDATE sessions SET status = reason, expired_at = 現在時刻
        WHERE session_id = ? AND hook_name = ?

        Args:
            session_id: セッションID
            hook_name: フック名
            reason: 期限切れ理由（デフォルト'expired'）
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.conn.execute(
            """
            UPDATE sessions
            SET status = ?, expired_at = ?
            WHERE session_id = ? AND hook_name = ?
            """,
            (reason, now, session_id, hook_name),
        )
        self._db.conn.commit()

    def expire_all(self, session_id: str, reason: str = "compact_expired") -> None:
        """セッション全hookを期限切れに（compact時）

        UPDATE sessions SET status = reason, expired_at = 現在時刻
        WHERE session_id = ? AND status = 'active'

        Args:
            session_id: セッションID
            reason: 期限切れ理由（デフォルト'compact_expired'）
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.conn.execute(
            """
            UPDATE sessions
            SET status = ?, expired_at = ?
            WHERE session_id = ? AND status = 'active'
            """,
            (reason, now, session_id),
        )
        self._db.conn.commit()

    def get(self, session_id: str, hook_name: str) -> Optional[SessionRecord]:
        """セッションレコード取得

        Args:
            session_id: セッションID
            hook_name: フック名

        Returns:
            SessionRecord または None
        """
        cursor = self._db.conn.execute(
            """
            SELECT session_id, hook_name, created_at, last_tokens, status, expired_at
            FROM sessions
            WHERE session_id = ? AND hook_name = ?
            """,
            (session_id, hook_name),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return SessionRecord(
            session_id=row[0],
            hook_name=row[1],
            created_at=row[2],
            last_tokens=row[3],
            status=row[4],
            expired_at=row[5],
        )
