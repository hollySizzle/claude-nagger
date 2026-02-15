"""TranscriptRepository - トランスクリプトの格納・取得"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from domain.models.records import TranscriptLineRecord
from infrastructure.db.nagger_state_db import NaggerStateDB

logger = logging.getLogger(__name__)


class TranscriptRepository:
    """トランスクリプトの格納・取得。"""

    def __init__(self, db: NaggerStateDB):
        """初期化

        Args:
            db: NaggerStateDBインスタンス
        """
        self._db = db

    def store_transcript(self, session_id: str, transcript_path: str) -> int:
        """.jsonlトランスクリプトをDBに格納

        行単位で逐次INSERTしメモリ効率を確保。
        line_typeはトップレベルの"type"フィールドから抽出。

        Args:
            session_id: セッションID
            transcript_path: .jsonlファイルパス

        Returns:
            格納した行数
        """
        path = Path(transcript_path)
        if not path.exists():
            logger.warning(f"トランスクリプトファイル不在: {transcript_path}")
            return 0

        now = datetime.now(timezone.utc).isoformat()
        inserted_count = 0

        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                # line_typeを抽出
                line_type = self._extract_line_type(line)

                self._db.conn.execute(
                    """
                    INSERT INTO transcript_lines
                    (session_id, line_number, line_type, raw_json, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (session_id, line_num, line_type, line, now),
                )
                inserted_count += 1

        self._db.conn.commit()
        logger.info(f"トランスクリプト格納完了: session={session_id}, {inserted_count}行")
        return inserted_count

    def get_transcript_lines(
        self, session_id: str, line_type: Optional[str] = None
    ) -> List[TranscriptLineRecord]:
        """session_idでトランスクリプト行を取得

        Args:
            session_id: セッションID
            line_type: フィルタするline_type（オプション）

        Returns:
            TranscriptLineRecordのリスト
        """
        if line_type:
            cursor = self._db.conn.execute(
                """
                SELECT id, session_id, line_number, line_type, raw_json, created_at
                FROM transcript_lines
                WHERE session_id = ? AND line_type = ?
                ORDER BY line_number ASC
                """,
                (session_id, line_type),
            )
        else:
            cursor = self._db.conn.execute(
                """
                SELECT id, session_id, line_number, line_type, raw_json, created_at
                FROM transcript_lines
                WHERE session_id = ?
                ORDER BY line_number ASC
                """,
                (session_id,),
            )

        rows = cursor.fetchall()
        return [
            TranscriptLineRecord(
                id=row[0],
                session_id=row[1],
                line_number=row[2],
                line_type=row[3],
                raw_json=row[4],
                created_at=row[5],
            )
            for row in rows
        ]

    def delete_old_transcripts(self, retention_days: int) -> int:
        """retention管理用（将来US #6176 で使用）

        Args:
            retention_days: 保持日数

        Returns:
            削除した行数
        """
        # スタブ実装: 将来US #6176で本実装
        return 0

    @staticmethod
    def _extract_line_type(line: str) -> Optional[str]:
        """JSON行からtypeフィールドを抽出

        Args:
            line: JSON文字列

        Returns:
            typeフィールドの値、抽出失敗時はNone
        """
        try:
            entry = json.loads(line)
            return entry.get("type")
        except (json.JSONDecodeError, AttributeError):
            return None
