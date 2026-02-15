"""TranscriptRepository - トランスクリプトの格納・取得"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from domain.models.records import TranscriptLineRecord
from infrastructure.db.nagger_state_db import NaggerStateDB

logger = logging.getLogger(__name__)

# content_summaryの最大長
_SUMMARY_MAX_LEN = 100


class TranscriptRepository:
    """トランスクリプトの格納・取得。"""

    def __init__(self, db: NaggerStateDB, mode: str = "raw"):
        """初期化

        Args:
            db: NaggerStateDBインスタンス
            mode: 格納モード ("raw" | "indexed" | "structured")
        """
        self._db = db
        self._mode = mode

    def store_transcript(self, session_id: str, transcript_path: str) -> int:
        """.jsonlトランスクリプトをDBに格納

        行単位で逐次INSERTしメモリ効率を確保。
        line_typeはトップレベルの"type"フィールドから抽出。
        indexed/structuredモードではメタデータカラムも格納。

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
        use_metadata = self._mode in ("indexed", "structured")

        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                # line_typeを抽出
                line_type = self._extract_line_type(line)

                if use_metadata:
                    # indexed/structuredモード: メタデータも格納
                    meta = self._extract_metadata(line, line_type)
                    self._db.conn.execute(
                        """
                        INSERT INTO transcript_lines
                        (session_id, line_number, line_type, raw_json, created_at,
                         timestamp, content_summary, tool_name, token_count, model, uuid)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id, line_num, line_type, line, now,
                            meta.get("timestamp"),
                            meta.get("content_summary"),
                            meta.get("tool_name"),
                            meta.get("token_count"),
                            meta.get("model"),
                            meta.get("uuid"),
                        ),
                    )
                else:
                    # rawモード: 従来通り（メタデータカラムはNULL）
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
        logger.info(f"トランスクリプト格納完了: session={session_id}, {inserted_count}行, mode={self._mode}")
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
        cols = (
            "id, session_id, line_number, line_type, raw_json, created_at, "
            "timestamp, content_summary, tool_name, token_count, model, uuid"
        )
        if line_type:
            cursor = self._db.conn.execute(
                f"""
                SELECT {cols}
                FROM transcript_lines
                WHERE session_id = ? AND line_type = ?
                ORDER BY line_number ASC
                """,
                (session_id, line_type),
            )
        else:
            cursor = self._db.conn.execute(
                f"""
                SELECT {cols}
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
                timestamp=row[6],
                content_summary=row[7],
                tool_name=row[8],
                token_count=row[9],
                model=row[10],
                uuid=row[11],
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

    @staticmethod
    def _extract_metadata(line: str, line_type: Optional[str] = None) -> Dict[str, Any]:
        """JSON行からメタデータを抽出

        Args:
            line: JSON文字列
            line_type: 行タイプ（"user" | "assistant" | "progress" 等）

        Returns:
            メタデータ辞書（キー: timestamp, uuid, content_summary, tool_name, token_count, model）
        """
        meta: Dict[str, Any] = {}
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, AttributeError):
            return meta

        if not isinstance(entry, dict):
            return meta

        # timestamp: そのまま取得
        meta["timestamp"] = entry.get("timestamp")

        # uuid: そのまま取得
        meta["uuid"] = entry.get("uuid")

        # line_type別の抽出
        if line_type == "user":
            meta["content_summary"] = _extract_user_summary(entry)
        elif line_type == "assistant":
            meta["content_summary"] = _extract_assistant_summary(entry)
            meta["tool_name"] = _extract_assistant_tool_names(entry)
            meta["token_count"] = _extract_token_count(entry)
            meta["model"] = _safe_get(entry, "message", "model")
        elif line_type == "progress":
            meta["tool_name"] = _safe_get(entry, "data", "hookName")

        return meta


def _truncate(text: str, max_len: int = _SUMMARY_MAX_LEN) -> str:
    """文字列を最大長で切り詰め"""
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _safe_get(d: dict, *keys: str) -> Any:
    """ネストされた辞書から安全に値を取得"""
    current = d
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def _extract_user_summary(entry: dict) -> Optional[str]:
    """user行からcontent_summaryを抽出

    .messageが文字列ならその先頭100文字。
    dictなら.message.contentの先頭100文字。
    """
    msg = entry.get("message")
    if msg is None:
        return None
    if isinstance(msg, str):
        return _truncate(msg)
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return _truncate(content)
    return None


def _extract_assistant_summary(entry: dict) -> Optional[str]:
    """assistant行からcontent_summaryを抽出

    .message.content[0].textの先頭100文字（text typeの場合）。
    tool_useの場合はツール名。
    """
    content = _safe_get(entry, "message", "content")
    if not isinstance(content, list) or len(content) == 0:
        return None

    first = content[0]
    if not isinstance(first, dict):
        return None

    if first.get("type") == "text":
        text = first.get("text", "")
        if isinstance(text, str):
            return _truncate(text)
    elif first.get("type") == "tool_use":
        name = first.get("name", "")
        return name if name else None

    return None


def _extract_assistant_tool_names(entry: dict) -> Optional[str]:
    """assistant行からtool_nameを抽出（複数あればカンマ区切り）"""
    content = _safe_get(entry, "message", "content")
    if not isinstance(content, list):
        return None

    names = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "tool_use":
            name = item.get("name")
            if name:
                names.append(name)

    return ",".join(names) if names else None


def _extract_token_count(entry: dict) -> Optional[int]:
    """assistant行からtoken_count（input + output）を抽出"""
    usage = _safe_get(entry, "message", "usage")
    if not isinstance(usage, dict):
        return None

    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")

    if input_tokens is None and output_tokens is None:
        return None

    total = (input_tokens or 0) + (output_tokens or 0)
    return total
