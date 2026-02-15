"""SubagentRepository - subagentの登録・識別・Claim操作"""

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

from domain.models.records import SubagentRecord
from infrastructure.db.nagger_state_db import NaggerStateDB
from shared.constants import TASK_SPAWN_TTL_MINUTES, VALID_ROLE_VALUES
from shared.structured_logging import DEFAULT_LOG_DIR, StructuredLogger

_logger = StructuredLogger(name="SubagentRepository", log_dir=DEFAULT_LOG_DIR)


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
        self, agent_id: str, session_id: str, agent_type: str, role: str = None,
        leader_transcript_path: str = None,
    ) -> None:
        """SubagentStart時。INSERT INTO subagents。created_at=現在時刻(ISO8601 UTC)

        Args:
            agent_id: エージェントID
            session_id: セッションID
            agent_type: エージェントタイプ
            role: 役割（オプション）
            leader_transcript_path: leaderのtranscript_path（issue_6057: leader/subagent区別用）
        """
        now = datetime.now(timezone.utc).isoformat()
        self._db.conn.execute(
            """
            INSERT INTO subagents (agent_id, session_id, agent_type, role, created_at, leader_transcript_path)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent_id, session_id, agent_type, role, now, leader_transcript_path),
        )
        self._db.conn.commit()

    def unregister(self, agent_id: str, agent_transcript_path: str = None) -> None:
        """SubagentStop時。subagent_historyにコピー後、DELETE FROM subagents + task_spawns

        DELETE前に対象レコードをSELECTし、subagent_historyテーブルにINSERTして
        ライフサイクル履歴を永続化する（issue_6089）。

        Args:
            agent_id: エージェントID
            agent_transcript_path: subagentのトランスクリプトパス（issue_6184）
        """
        # DELETE前に履歴をsubagent_historyへコピー
        cursor = self._db.conn.execute(
            """
            SELECT agent_id, session_id, agent_type, role, role_source,
                   leader_transcript_path, created_at
            FROM subagents
            WHERE agent_id = ?
            """,
            (agent_id,),
        )
        row = cursor.fetchone()
        if row is not None:
            now = datetime.now(timezone.utc).isoformat()
            self._db.conn.execute(
                """
                INSERT INTO subagent_history
                    (agent_id, session_id, agent_type, role, role_source,
                     leader_transcript_path, started_at, stopped_at,
                     agent_transcript_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row[0], row[1], row[2], row[3], row[4], row[5], row[6], now,
                 agent_transcript_path),
            )

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

                    # tool_use.id を取得（issue_5947）
                    tool_use_id = content_item.get("id")

                    # [ROLE:xxx] を抽出
                    role_match = role_pattern.search(prompt)
                    role = role_match.group(1) if role_match else None

                    # ROLEがないTask tool_useはスキップ（issue_5947）
                    if role is None:
                        continue

                    # prompt_hash = SHA256(prompt)[:16]
                    prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]

                    # INSERT OR IGNORE（冪等性）
                    cursor = self._db.conn.execute(
                        """
                        INSERT OR IGNORE INTO task_spawns
                        (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (session_id, line_num, subagent_type, role, prompt_hash, tool_use_id, now),
                    )
                    inserted_count += cursor.rowcount

        self._db.conn.commit()
        return inserted_count

    def find_task_spawn_by_tool_use_id(self, tool_use_id: str) -> Optional[dict]:
        """tool_use_idでtask_spawnを検索（issue_5947）

        Args:
            tool_use_id: Task tool_useのid

        Returns:
            task_spawnレコード（dict形式）、存在しない場合None
        """
        cursor = self._db.conn.execute(
            """
            SELECT id, session_id, transcript_index, subagent_type, role, prompt_hash,
                   tool_use_id, matched_agent_id, created_at
            FROM task_spawns
            WHERE tool_use_id = ?
            """,
            (tool_use_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return {
            "id": row[0],
            "session_id": row[1],
            "transcript_index": row[2],
            "subagent_type": row[3],
            "role": row[4],
            "prompt_hash": row[5],
            "tool_use_id": row[6],
            "matched_agent_id": row[7],
            "created_at": row[8],
        }

    def find_parent_tool_use_id(
        self, transcript_path: str, agent_id: str
    ) -> Optional[str]:
        """親transcriptからagent_progressイベントを検索し、parentToolUseIDを取得（issue_5947）

        Args:
            transcript_path: transcriptファイルパス
            agent_id: subagentのagent_id

        Returns:
            parentToolUseID（存在しない場合None）
        """
        _logger.info(f"find_parent_tool_use_id: searching for agent_id={agent_id} in {transcript_path}")
        path = Path(transcript_path)
        if not path.exists():
            _logger.info(f"find_parent_tool_use_id: transcript_path does not exist")
            return None

        agent_progress_count = 0
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # type='progress' かつ data.type='agent_progress' のエントリを検索
                if entry.get("type") != "progress":
                    continue

                data = entry.get("data", {})
                if data.get("type") != "agent_progress":
                    continue

                agent_progress_count += 1

                # data.agentIdが一致するか確認
                if data.get("agentId") != agent_id:
                    continue

                # parentToolUseIDを返す
                parent_tool_use_id = entry.get("parentToolUseID")
                if parent_tool_use_id:
                    _logger.info(f"find_parent_tool_use_id: found {agent_progress_count} agent_progress entries, match found")
                    return parent_tool_use_id

        _logger.info(f"find_parent_tool_use_id: found {agent_progress_count} agent_progress entries, no match")
        return None

    def match_task_to_agent(
        self,
        session_id: str,
        agent_id: str,
        agent_type: str,
        role: str = None,
        transcript_path: str = None,
    ) -> Optional[str]:
        """未マッチのtask_spawnから、agent_typeが一致する最古を取得し、マッチング。

        アルゴリズム（issue_5947改善）:
        0. transcript_pathがある場合、agent_progressでtool_use_idを取得し正確マッチ
        1. BEGIN EXCLUSIVE
        2. Step 1: roleが指定されている場合、roleで完全一致マッチ
           SELECT * FROM task_spawns WHERE session_id = ? AND role = ? AND matched_agent_id IS NULL
           ORDER BY transcript_index ASC LIMIT 1
        3. Step 2: roleマッチなければsubagent_typeでマッチ（ROLEありエントリのみ）
           SELECT * FROM task_spawns WHERE session_id = ? AND subagent_type = ? AND role IS NOT NULL AND matched_agent_id IS NULL
           ORDER BY transcript_index ASC LIMIT 1
        4. if found:
           UPDATE task_spawns SET matched_agent_id = ? WHERE id = ?
           UPDATE subagents SET role = ?, role_source = 'task_match', task_match_index = ? WHERE agent_id = ?
           COMMIT
           return role
        5. else: COMMIT, return None

        Args:
            session_id: セッションID
            agent_id: マッチ対象のエージェントID
            agent_type: エージェントタイプ
            role: 優先マッチするrole（オプション）
            transcript_path: 親transcriptパス（オプション、issue_5947）

        Returns:
            マッチしたrole（存在しない場合None）
        """
        # Step 0: agent_progressベースの正確なマッチング（issue_5947）
        _logger.info(f"match_task_to_agent: agent_id={agent_id}, transcript_path={transcript_path}")
        if transcript_path:
            parent_tool_use_id = self.find_parent_tool_use_id(transcript_path, agent_id)
            _logger.info(f"find_parent_tool_use_id result: {parent_tool_use_id}")
            if parent_tool_use_id:
                task_spawn = self.find_task_spawn_by_tool_use_id(parent_tool_use_id)
                _logger.info(f"find_task_spawn_by_tool_use_id result: {task_spawn}")
                if task_spawn and task_spawn.get("matched_agent_id") is None:
                    _logger.info(f"Exact match success: role={task_spawn.get('role')}")
                    matched_role = task_spawn.get("role")
                    task_id = task_spawn.get("id")
                    transcript_index = task_spawn.get("transcript_index")

                    # アトミックに更新
                    self._db.conn.execute("BEGIN EXCLUSIVE")
                    try:
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
                            (matched_role, transcript_index, agent_id),
                        )

                        self._db.conn.commit()
                        return matched_role
                    except Exception:
                        self._db.conn.rollback()
                        raise
                else:
                    _logger.info(f"Exact match failed: task_spawn={task_spawn}")
            else:
                _logger.info("No agent_progress found, falling back")
        else:
            _logger.info("No transcript_path, falling back")

        # フォールバック: 従来のマッチングロジック
        _logger.info("Fallback matching started")
        self._db.conn.execute("BEGIN EXCLUSIVE")
        try:
            row = None

            # TTLチェック用の閾値時刻を計算（issue_5955）
            # SQLiteのdatetime()とPythonのISO8601形式が異なるため、Pythonで計算
            ttl_threshold = (datetime.now(timezone.utc) - timedelta(minutes=TASK_SPAWN_TTL_MINUTES)).isoformat()

            # Step 1: roleが指定されている場合、roleで完全一致マッチ
            if role:
                cursor = self._db.conn.execute(
                    """
                    SELECT id, role, transcript_index FROM task_spawns
                    WHERE session_id = ? AND role = ? AND matched_agent_id IS NULL
                    AND created_at > ?
                    ORDER BY transcript_index ASC LIMIT 1
                    """,
                    (session_id, role, ttl_threshold),
                )
                row = cursor.fetchone()

            # Step 2: roleマッチなければsubagent_typeでマッチ（ROLEありエントリのみ）
            if row is None:
                cursor = self._db.conn.execute(
                    """
                    SELECT id, role, transcript_index FROM task_spawns
                    WHERE session_id = ? AND subagent_type = ? AND role IS NOT NULL AND matched_agent_id IS NULL
                    AND created_at > ?
                    ORDER BY transcript_index ASC LIMIT 1
                    """,
                    (session_id, agent_type, ttl_threshold),
                )
                row = cursor.fetchone()

            if row is None:
                self._db.conn.commit()
                return None

            task_id, matched_role, transcript_index = row

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
                (matched_role, transcript_index, agent_id),
            )

            self._db.conn.commit()
            return matched_role
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
                       created_at, startup_processed, startup_processed_at, task_match_index,
                       leader_transcript_path
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
                leader_transcript_path=row[9],
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
                   created_at, startup_processed, startup_processed_at, task_match_index,
                   leader_transcript_path
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
            leader_transcript_path=row[9],
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
                   created_at, startup_processed, startup_processed_at, task_match_index,
                   leader_transcript_path
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
                leader_transcript_path=row[9],
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
        """session_idの全subagentを削除。DELETE前にsubagent_historyへコピーする。

        異常終了時等にunregister()を経由せずcleanup_session()が呼ばれるケースで
        履歴が消失することを防ぐ（issue_6090）。

        Args:
            session_id: セッションID

        Returns:
            削除件数
        """
        # DELETE前に対象レコードをsubagent_historyへコピー
        cursor = self._db.conn.execute(
            """
            SELECT agent_id, session_id, agent_type, role, role_source,
                   leader_transcript_path, created_at
            FROM subagents
            WHERE session_id = ?
            """,
            (session_id,),
        )
        rows = cursor.fetchall()
        if rows:
            now = datetime.now(timezone.utc).isoformat()
            self._db.conn.executemany(
                """
                INSERT INTO subagent_history
                    (agent_id, session_id, agent_type, role, role_source,
                     leader_transcript_path, started_at, stopped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [(row[0], row[1], row[2], row[3], row[4], row[5], row[6], now)
                 for row in rows],
            )

        cursor = self._db.conn.execute(
            "DELETE FROM subagents WHERE session_id = ?", (session_id,)
        )
        deleted_count = cursor.rowcount
        self._db.conn.commit()
        return deleted_count

    def cleanup_old_task_spawns(self, session_id: str, keep_recent: int = 100) -> int:
        """matched_agent_idがNULLで古いエントリを削除。

        最新keep_recent件を除く未マッチエントリを削除する。

        Args:
            session_id: セッションID
            keep_recent: 保持する最新エントリ数（デフォルト100）

        Returns:
            削除件数
        """
        cursor = self._db.conn.execute(
            """
            DELETE FROM task_spawns
            WHERE session_id = ? AND matched_agent_id IS NULL
            AND id NOT IN (
                SELECT id FROM task_spawns
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (session_id, session_id, keep_recent),
        )
        deleted_count = cursor.rowcount
        self._db.conn.commit()
        return deleted_count

    def cleanup_null_role_task_spawns(self) -> int:
        """role IS NULLのtask_spawnsエントリを全削除。

        issue_5947: 初回実行時の既存データクリーンアップ用。
        register_task_spawnsがROLEありのみ登録するようになったため、
        既存のrole=NULLエントリは不要。

        Returns:
            削除件数
        """
        cursor = self._db.conn.execute(
            "DELETE FROM task_spawns WHERE role IS NULL"
        )
        deleted_count = cursor.rowcount
        self._db.conn.commit()
        return deleted_count

    # === 案D簡易版（ハイブリッドアプローチ） ===
    def retry_match_from_agent_progress(
        self, session_id: str, agent_id: str, transcript_path: str
    ) -> Optional[str]:
        """PreToolUse時にrole=NULLのsubagentに対してagent_progressベースの再マッチを試行

        SubagentStart時点ではagent_progressが未書き込みのため、最初のsubagentでマッチ失敗する。
        PreToolUse時点ではagent_progressが存在するため、Claim時に再マッチを試行する。

        Args:
            session_id: セッションID
            agent_id: subagentのagent_id
            transcript_path: 親transcriptパス

        Returns:
            マッチしたrole（存在しない場合None）
        """
        _logger.info(f"retry_match_from_agent_progress: agent_id={agent_id}, transcript_path={transcript_path}")

        # 1. find_parent_tool_use_id()でparentToolUseIDを取得
        parent_tool_use_id = self.find_parent_tool_use_id(transcript_path, agent_id)
        if not parent_tool_use_id:
            _logger.info("retry_match: No parentToolUseID found in agent_progress")
            return None

        _logger.info(f"retry_match: Found parentToolUseID={parent_tool_use_id}")

        # 2. find_task_spawn_by_tool_use_id()でtask_spawnを検索
        task_spawn = self.find_task_spawn_by_tool_use_id(parent_tool_use_id)
        if not task_spawn:
            _logger.info("retry_match: No task_spawn found for tool_use_id")
            return None

        matched_role = task_spawn.get("role")
        if not matched_role:
            _logger.info("retry_match: task_spawn has no role")
            return None

        task_id = task_spawn.get("id")
        transcript_index = task_spawn.get("transcript_index")

        _logger.info(f"retry_match: Found task_spawn with role={matched_role}, id={task_id}")

        # 3. マッチしたらsubagentsテーブルのroleを更新
        self._db.conn.execute("BEGIN EXCLUSIVE")
        try:
            # task_spawnsをマッチ済みに更新（まだ未マッチの場合のみ）
            cursor = self._db.conn.execute(
                "UPDATE task_spawns SET matched_agent_id = ? WHERE id = ? AND matched_agent_id IS NULL",
                (agent_id, task_id),
            )
            if cursor.rowcount == 0:
                # 既に他のagentにマッチ済み
                self._db.conn.commit()
                _logger.info("retry_match: task_spawn already matched to another agent")
                return None

            # subagentsのroleを更新
            self._db.conn.execute(
                """
                UPDATE subagents
                SET role = ?, role_source = 'retry_match', task_match_index = ?
                WHERE agent_id = ?
                """,
                (matched_role, transcript_index, agent_id),
            )

            self._db.conn.commit()
            _logger.info(f"retry_match: Successfully updated role to {matched_role}")
            return matched_role
        except Exception:
            self._db.conn.rollback()
            raise
