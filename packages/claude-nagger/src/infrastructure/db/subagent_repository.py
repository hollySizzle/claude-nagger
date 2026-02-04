"""SubagentRepository - subagentの登録・識別・Claim操作"""

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from domain.models.records import SubagentRecord
from infrastructure.db.nagger_state_db import NaggerStateDB


class SubagentRepository:
    """subagentの登録・識別・Claim操作。"""

    def __init__(self, db: NaggerStateDB):
        """初期化

        Args:
            db: NaggerStateDBインスタンス
        """
        self._db = db

    # === ライフサイクル ===
    def register(
        self, agent_id: str, session_id: str, agent_type: str, role: str = None
    ) -> None:
        """SubagentStart時。INSERT INTO subagents。created_at=現在時刻(ISO8601 UTC)

        Args:
            agent_id: エージェントID
            session_id: セッションID
            agent_type: エージェントタイプ
            role: 役割（オプション）
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.conn.execute(
            """
            INSERT INTO subagents (agent_id, session_id, agent_type, role, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, session_id, agent_type, role, now),
        )
        self._db.conn.commit()

    def unregister(self, agent_id: str) -> None:
        """SubagentStop時。DELETE FROM subagents + DELETE FROM task_spawns WHERE matched_agent_id = agent_id

        Args:
            agent_id: エージェントID
        """
        self._db.conn.execute(
            "DELETE FROM task_spawns WHERE matched_agent_id = ?", (agent_id,)
        )
        self._db.conn.execute("DELETE FROM subagents WHERE agent_id = ?", (agent_id,))
        self._db.conn.commit()

    # === Task tool_useマッチング（Phase 1） ===
    def register_task_spawns(self, session_id: str, transcript_path: str) -> int:
        """親transcriptからTask tool_useを解析し、未登録分をINSERT。

        解析対象:
        - トップレベル type='assistant' のエントリを対象
        - message.content[] 内の type='tool_use' かつ name='Task' ブロックを抽出
        - tool_use.input から subagent_type, prompt を取得
        - prompt から [ROLE:xxx] を正規表現で抽出
        - prompt_hash = SHA256(prompt)[:16]
        - transcript_index = 行番号

        冪等性: UNIQUE(session_id, transcript_index) で重複排除（INSERT OR IGNORE）

        Args:
            session_id: セッションID
            transcript_path: トランスクリプトファイルパス

        Returns:
            新規登録件数
        """
        path = Path(transcript_path)
        if not path.exists():
            return 0

        # [ROLE:xxx] パターン
        role_pattern = re.compile(r"\[ROLE:([^\]]+)\]")
        now = datetime.now(timezone.utc).isoformat()
        inserted_count = 0

        with open(path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # トップレベル type='assistant' のみ対象
                if entry.get("type") != "assistant":
                    continue

                # message.content[] を走査
                message = entry.get("message", {})
                content_list = message.get("content", [])

                for content_item in content_list:
                    # type='tool_use' かつ name='Task' を抽出
                    if content_item.get("type") != "tool_use":
                        continue
                    if content_item.get("name") != "Task":
                        continue

                    # input から subagent_type, prompt を取得
                    tool_input = content_item.get("input", {})
                    subagent_type = tool_input.get("subagent_type")
                    prompt = tool_input.get("prompt", "")

                    # [ROLE:xxx] を抽出
                    role_match = role_pattern.search(prompt)
                    role = role_match.group(1) if role_match else None

                    # prompt_hash = SHA256(prompt)[:16]
                    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

                    # INSERT OR IGNORE（冪等性）
                    cursor = self._db.conn.execute(
                        """
                        INSERT OR IGNORE INTO task_spawns
                        (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (session_id, line_num, subagent_type, role, prompt_hash, now),
                    )
                    inserted_count += cursor.rowcount

        self._db.conn.commit()
        return inserted_count

    def match_task_to_agent(
        self, session_id: str, agent_id: str, agent_type: str
    ) -> Optional[str]:
        """未マッチのtask_spawnから、agent_typeが一致する最古を取得し、マッチング。

        アルゴリズム:
        1. BEGIN EXCLUSIVE
        2. SELECT * FROM task_spawns WHERE session_id = ? AND matched_agent_id IS NULL AND subagent_type = ? ORDER BY transcript_index ASC LIMIT 1
        3. if found:
           UPDATE task_spawns SET matched_agent_id = ? WHERE id = ?
           UPDATE subagents SET role = ?, role_source = 'task_match', task_match_index = ? WHERE agent_id = ?
           COMMIT
           return role
        4. else: COMMIT, return None

        Args:
            session_id: セッションID
            agent_id: マッチ対象のエージェントID
            agent_type: エージェントタイプ

        Returns:
            マッチしたrole（存在しない場合None）
        """
        self._db.conn.execute("BEGIN EXCLUSIVE")
        try:
            cursor = self._db.conn.execute(
                """
                SELECT id, role, transcript_index FROM task_spawns
                WHERE session_id = ? AND matched_agent_id IS NULL AND subagent_type = ?
                ORDER BY transcript_index ASC LIMIT 1
                """,
                (session_id, agent_type),
            )
            row = cursor.fetchone()

            if row is None:
                self._db.conn.commit()
                return None

            task_id, role, transcript_index = row

            # task_spawnsをマッチ済みに更新
            self._db.conn.execute(
                "UPDATE task_spawns SET matched_agent_id = ? WHERE id = ?",
                (agent_id, task_id),
            )

            # subagentsのroleを更新
            self._db.conn.execute(
                """
                UPDATE subagents
                SET role = ?, role_source = 'task_match', task_match_index = ?
                WHERE agent_id = ?
                """,
                (role, transcript_index, agent_id),
            )

            self._db.conn.commit()
            return role
        except Exception:
            self._db.conn.rollback()
            raise

    # === Claimパターン（Phase 2） ===
    def claim_next_unprocessed(self, session_id: str) -> Optional[SubagentRecord]:
        """PreToolUse時。未処理(startup_processed=0)の最古subagentを取得（マークしない）。

        2フェーズ方式: 取得のみ行い、マークはmark_processed()で別途実行する。
        これにより、process()完了前にDBがマークされてしまう問題を防ぐ。

        アルゴリズム:
        1. BEGIN EXCLUSIVE
        2. SELECT * FROM subagents WHERE session_id = ? AND startup_processed = 0 ORDER BY created_at ASC LIMIT 1
        3. 0件ならNone、1件以上なら最古を返却
        4. COMMIT（UPDATEなし）

        Args:
            session_id: セッションID

        Returns:
            SubagentRecord（startup_processed=False）、存在しない場合None
        """
        self._db.conn.execute("BEGIN EXCLUSIVE")
        try:
            cursor = self._db.conn.execute(
                """
                SELECT agent_id, session_id, agent_type, role, role_source,
                       created_at, startup_processed, startup_processed_at, task_match_index
                FROM subagents
                WHERE session_id = ? AND startup_processed = 0
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (session_id,),
            )
            row = cursor.fetchone()

            if not row:
                self._db.conn.commit()
                return None

            # SubagentRecordを作成（UPDATEなし）
            record = SubagentRecord(
                agent_id=row[0],
                session_id=row[1],
                agent_type=row[2],
                role=row[3],
                role_source=row[4],
                created_at=row[5],
                startup_processed=bool(row[6]),
                startup_processed_at=row[7],
                task_match_index=row[8],
            )

            self._db.conn.commit()
            return record
        except Exception:
            self._db.conn.rollback()
            raise

    def mark_processed(self, agent_id: str) -> bool:
        """subagentをstartup_processed=1にマーク。

        process()完了後に呼び出すこと。

        Args:
            agent_id: エージェントID

        Returns:
            更新成功時True、対象レコードなし時False
        """
        now = datetime.now(timezone.utc).isoformat()
        cursor = self._db.conn.execute(
            """
            UPDATE subagents
            SET startup_processed = 1, startup_processed_at = ?
            WHERE agent_id = ? AND startup_processed = 0
            """,
            (now, agent_id),
        )
        self._db.conn.commit()
        return cursor.rowcount > 0

    # === クエリ ===
    def get(self, agent_id: str) -> Optional[SubagentRecord]:
        """agent_idでsubagent取得

        Args:
            agent_id: エージェントID

        Returns:
            SubagentRecord、存在しない場合None
        """
        cursor = self._db.conn.execute(
            """
            SELECT agent_id, session_id, agent_type, role, role_source,
                   created_at, startup_processed, startup_processed_at, task_match_index
            FROM subagents
            WHERE agent_id = ?
            """,
            (agent_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return SubagentRecord(
            agent_id=row[0],
            session_id=row[1],
            agent_type=row[2],
            role=row[3],
            role_source=row[4],
            created_at=row[5],
            startup_processed=bool(row[6]),
            startup_processed_at=row[7],
            task_match_index=row[8],
        )

    def get_active(self, session_id: str) -> List[SubagentRecord]:
        """session_idのアクティブsubagent一覧

        Args:
            session_id: セッションID

        Returns:
            SubagentRecordのリスト
        """
        cursor = self._db.conn.execute(
            """
            SELECT agent_id, session_id, agent_type, role, role_source,
                   created_at, startup_processed, startup_processed_at, task_match_index
            FROM subagents
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            (session_id,),
        )
        rows = cursor.fetchall()

        return [
            SubagentRecord(
                agent_id=row[0],
                session_id=row[1],
                agent_type=row[2],
                role=row[3],
                role_source=row[4],
                created_at=row[5],
                startup_processed=bool(row[6]),
                startup_processed_at=row[7],
                task_match_index=row[8],
            )
            for row in rows
        ]

    def get_unprocessed_count(self, session_id: str) -> int:
        """未処理subagent数

        Args:
            session_id: セッションID

        Returns:
            未処理subagent数
        """
        cursor = self._db.conn.execute(
            """
            SELECT COUNT(*) FROM subagents
            WHERE session_id = ? AND startup_processed = 0
            """,
            (session_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else 0

    def is_any_active(self, session_id: str) -> bool:
        """アクティブsubagentの存在判定

        Args:
            session_id: セッションID

        Returns:
            アクティブsubagentが存在する場合True
        """
        cursor = self._db.conn.execute(
            """
            SELECT 1 FROM subagents
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        )
        return cursor.fetchone() is not None

    # === 更新 ===
    def update_role(self, agent_id: str, role: str, source: str) -> None:
        """roleとrole_sourceを更新

        Args:
            agent_id: エージェントID
            role: 新しいrole
            source: role_source
        """
        self._db.conn.execute(
            """
            UPDATE subagents
            SET role = ?, role_source = ?
            WHERE agent_id = ?
            """,
            (role, source, agent_id),
        )
        self._db.conn.commit()

    # === クリーンアップ ===
    def cleanup_session(self, session_id: str) -> int:
        """session_idの全subagentを削除。

        Args:
            session_id: セッションID

        Returns:
            削除件数
        """
        cursor = self._db.conn.execute(
            "DELETE FROM subagents WHERE session_id = ?", (session_id,)
        )
        deleted_count = cursor.rowcount
        self._db.conn.commit()
        return deleted_count
