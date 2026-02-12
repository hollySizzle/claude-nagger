"""subagent_historyのテスト（issue_6089）

- subagent_historyテーブル生成確認
- unregister時のhistoryコピー確認
- stopped_atが正しく記録されること
- SubagentHistoryRepository.get_by_session, get_by_agent, get_stats の動作確認
- スキーマv4マイグレーション確認
"""

import time
from datetime import datetime, timezone

import pytest

from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.subagent_history_repository import SubagentHistoryRepository
from infrastructure.db.subagent_repository import SubagentRepository


class TestSubagentHistoryTableCreation:
    """subagent_historyテーブル生成確認"""

    def test_table_exists_on_fresh_db(self, db):
        """新規DB作成時にsubagent_historyテーブルが存在する"""
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subagent_history'"
        )
        assert cursor.fetchone() is not None

    def test_indexes_exist(self, db):
        """subagent_historyのインデックスが存在する"""
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_subagent_history_%'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_subagent_history_session" in indexes
        assert "idx_subagent_history_role" in indexes

    def test_schema_version_is_4(self, db):
        """スキーマバージョンが4"""
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        assert version == 4


class TestUnregisterHistoryCopy:
    """unregister時のhistoryコピー確認"""

    def test_unregister_creates_history_record(self, db):
        """unregister()がsubagent_historyにレコードをコピーする"""
        repo = SubagentRepository(db)
        agent_id = "agent-hist-1"
        session_id = "session-hist-1"

        repo.register(agent_id, session_id, "general-purpose", role="coder")
        repo.unregister(agent_id)

        # subagentsからは削除されている
        assert repo.get(agent_id) is None

        # subagent_historyにレコードが存在する
        cursor = db.conn.execute(
            "SELECT agent_id, session_id, agent_type, role FROM subagent_history WHERE agent_id = ?",
            (agent_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == agent_id
        assert row[1] == session_id
        assert row[2] == "general-purpose"
        assert row[3] == "coder"

    def test_unregister_records_stopped_at(self, db):
        """unregister()がstopped_atを現在時刻(UTC ISO8601)で記録する"""
        repo = SubagentRepository(db)
        agent_id = "agent-hist-stop"
        session_id = "session-hist-stop"

        repo.register(agent_id, session_id, "general-purpose")

        before = datetime.now(timezone.utc)
        repo.unregister(agent_id)
        after = datetime.now(timezone.utc)

        cursor = db.conn.execute(
            "SELECT stopped_at FROM subagent_history WHERE agent_id = ?",
            (agent_id,),
        )
        stopped_at_str = cursor.fetchone()[0]
        assert stopped_at_str is not None

        # ISO8601パース確認（stopped_atがbefore〜afterの範囲内）
        stopped_at = datetime.fromisoformat(stopped_at_str)
        assert before <= stopped_at <= after

    def test_unregister_records_started_at_from_created_at(self, db):
        """unregister()がstarted_atにsubagentsのcreated_atを使用する"""
        repo = SubagentRepository(db)
        agent_id = "agent-hist-start"
        session_id = "session-hist-start"

        repo.register(agent_id, session_id, "general-purpose")

        # subagentsのcreated_atを取得
        record = repo.get(agent_id)
        original_created_at = record.created_at

        repo.unregister(agent_id)

        # subagent_historyのstarted_atがcreated_atと一致
        cursor = db.conn.execute(
            "SELECT started_at FROM subagent_history WHERE agent_id = ?",
            (agent_id,),
        )
        started_at = cursor.fetchone()[0]
        assert started_at == original_created_at

    def test_unregister_copies_role_source(self, db):
        """unregister()がrole_sourceをコピーする"""
        repo = SubagentRepository(db)
        agent_id = "agent-hist-rs"
        session_id = "session-hist-rs"

        repo.register(agent_id, session_id, "general-purpose", role="coder")
        repo.update_role(agent_id, "reviewer", "task_match")
        repo.unregister(agent_id)

        cursor = db.conn.execute(
            "SELECT role, role_source FROM subagent_history WHERE agent_id = ?",
            (agent_id,),
        )
        row = cursor.fetchone()
        assert row[0] == "reviewer"
        assert row[1] == "task_match"

    def test_unregister_copies_leader_transcript_path(self, db):
        """unregister()がleader_transcript_pathをコピーする"""
        repo = SubagentRepository(db)
        agent_id = "agent-hist-ltp"
        session_id = "session-hist-ltp"
        leader_tp = "/home/user/.claude/projects/test/leader.jsonl"

        repo.register(agent_id, session_id, "general-purpose",
                       leader_transcript_path=leader_tp)
        repo.unregister(agent_id)

        cursor = db.conn.execute(
            "SELECT leader_transcript_path FROM subagent_history WHERE agent_id = ?",
            (agent_id,),
        )
        row = cursor.fetchone()
        assert row[0] == leader_tp

    def test_unregister_nonexistent_agent_no_history(self, db):
        """存在しないagent_idのunregisterではhistoryが作成されない"""
        repo = SubagentRepository(db)
        repo.unregister("nonexistent-agent")

        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM subagent_history WHERE agent_id = ?",
            ("nonexistent-agent",),
        )
        count = cursor.fetchone()[0]
        assert count == 0

    def test_unregister_still_deletes_subagent(self, db):
        """unregister()後もsubagentsテーブルからは削除される（既存動作維持）"""
        repo = SubagentRepository(db)
        agent_id = "agent-hist-del"
        session_id = "session-hist-del"

        repo.register(agent_id, session_id, "general-purpose")
        repo.unregister(agent_id)

        assert repo.get(agent_id) is None

    def test_unregister_still_deletes_task_spawns(self, db):
        """unregister()後もtask_spawnsのmatched_agent_idレコードは削除される（既存動作維持）"""
        repo = SubagentRepository(db)
        agent_id = "agent-hist-ts"
        session_id = "session-hist-ts"

        repo.register(agent_id, session_id, "general-purpose")

        # task_spawnをマッチ済みにする
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, matched_agent_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "coder", "hash", agent_id, now),
        )
        db.conn.commit()

        repo.unregister(agent_id)

        # task_spawnsからも削除
        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE matched_agent_id = ?",
            (agent_id,),
        )
        assert cursor.fetchone()[0] == 0


class TestSubagentHistoryRepository:
    """SubagentHistoryRepositoryのテスト"""

    def _insert_history(self, db, agent_id, session_id, role=None, role_source=None,
                        started_at=None, stopped_at=None, agent_type="general-purpose"):
        """テスト用履歴レコードを直接INSERT"""
        if started_at is None:
            started_at = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            """
            INSERT INTO subagent_history
                (agent_id, session_id, agent_type, role, role_source, started_at, stopped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (agent_id, session_id, agent_type, role, role_source, started_at, stopped_at),
        )
        db.conn.commit()

    def test_get_by_session(self, db):
        """get_by_sessionでセッション内の全履歴を取得"""
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-by-sess"

        self._insert_history(db, "agent-a", session_id, role="coder")
        self._insert_history(db, "agent-b", session_id, role="reviewer")
        self._insert_history(db, "agent-c", "other-session", role="tester")

        results = history_repo.get_by_session(session_id)
        assert len(results) == 2
        agent_ids = [r["agent_id"] for r in results]
        assert "agent-a" in agent_ids
        assert "agent-b" in agent_ids
        assert "agent-c" not in agent_ids

    def test_get_by_session_empty(self, db):
        """該当セッションの履歴がない場合は空リスト"""
        history_repo = SubagentHistoryRepository(db)
        results = history_repo.get_by_session("no-such-session")
        assert results == []

    def test_get_by_agent(self, db):
        """get_by_agentで特定agentの履歴を取得"""
        history_repo = SubagentHistoryRepository(db)
        agent_id = "agent-multi"

        self._insert_history(db, agent_id, "session-1", role="coder")
        self._insert_history(db, agent_id, "session-2", role="reviewer")
        self._insert_history(db, "other-agent", "session-1", role="tester")

        results = history_repo.get_by_agent(agent_id)
        assert len(results) == 2
        assert all(r["agent_id"] == agent_id for r in results)

    def test_get_by_agent_empty(self, db):
        """該当agentの履歴がない場合は空リスト"""
        history_repo = SubagentHistoryRepository(db)
        results = history_repo.get_by_agent("no-such-agent")
        assert results == []

    def test_get_stats_total(self, db):
        """get_statsでtotalが正しい"""
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-stats"

        self._insert_history(db, "a1", session_id, role="coder")
        self._insert_history(db, "a2", session_id, role="coder")
        self._insert_history(db, "a3", session_id, role="reviewer")

        stats = history_repo.get_stats(session_id=session_id)
        assert stats["total"] == 3

    def test_get_stats_by_role(self, db):
        """get_statsでby_roleが正しい"""
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-stats-role"

        self._insert_history(db, "a1", session_id, role="coder")
        self._insert_history(db, "a2", session_id, role="coder")
        self._insert_history(db, "a3", session_id, role="reviewer")
        self._insert_history(db, "a4", session_id, role=None)

        stats = history_repo.get_stats(session_id=session_id)
        assert stats["by_role"]["coder"] == 2
        assert stats["by_role"]["reviewer"] == 1
        assert stats["by_role"]["(none)"] == 1

    def test_get_stats_avg_duration(self, db):
        """get_statsでavg_duration_secondsが計算される"""
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-stats-dur"

        # 10秒間のsubagent
        self._insert_history(
            db, "a1", session_id, role="coder",
            started_at="2025-01-01T00:00:00+00:00",
            stopped_at="2025-01-01T00:00:10+00:00",
        )
        # 20秒間のsubagent
        self._insert_history(
            db, "a2", session_id, role="reviewer",
            started_at="2025-01-01T00:00:00+00:00",
            stopped_at="2025-01-01T00:00:20+00:00",
        )

        stats = history_repo.get_stats(session_id=session_id)
        # 平均 = (10 + 20) / 2 = 15秒
        assert stats["avg_duration_seconds"] is not None
        assert abs(stats["avg_duration_seconds"] - 15.0) < 0.1

    def test_get_stats_no_stopped_at(self, db):
        """stopped_atがNULLのレコードのみの場合、avg_duration_secondsはNone"""
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-stats-no-stop"

        self._insert_history(db, "a1", session_id, role="coder", stopped_at=None)

        stats = history_repo.get_stats(session_id=session_id)
        assert stats["avg_duration_seconds"] is None

    def test_get_stats_global(self, db):
        """session_id未指定で全体統計"""
        history_repo = SubagentHistoryRepository(db)

        self._insert_history(db, "a1", "session-g1", role="coder")
        self._insert_history(db, "a2", "session-g2", role="reviewer")

        stats = history_repo.get_stats()
        assert stats["total"] == 2

    def test_get_stats_empty(self, db):
        """履歴がない場合のget_stats"""
        history_repo = SubagentHistoryRepository(db)

        stats = history_repo.get_stats(session_id="empty-session")
        assert stats["total"] == 0
        assert stats["by_role"] == {}
        assert stats["avg_duration_seconds"] is None

    def test_dict_fields(self, db):
        """_row_to_dictが全フィールドを含む"""
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-fields"
        leader_tp = "/path/to/leader.jsonl"

        db.conn.execute(
            """
            INSERT INTO subagent_history
                (agent_id, session_id, agent_type, role, role_source,
                 leader_transcript_path, started_at, stopped_at, issue_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("a-fields", session_id, "gp", "coder", "task_match",
             leader_tp, "2025-01-01T00:00:00+00:00", "2025-01-01T00:01:00+00:00", "1234"),
        )
        db.conn.commit()

        results = history_repo.get_by_session(session_id)
        assert len(results) == 1
        r = results[0]
        assert r["id"] is not None
        assert r["agent_id"] == "a-fields"
        assert r["session_id"] == session_id
        assert r["agent_type"] == "gp"
        assert r["role"] == "coder"
        assert r["role_source"] == "task_match"
        assert r["leader_transcript_path"] == leader_tp
        assert r["started_at"] == "2025-01-01T00:00:00+00:00"
        assert r["stopped_at"] == "2025-01-01T00:01:00+00:00"
        assert r["issue_id"] == "1234"


class TestSchemaV4Migration:
    """スキーマv4マイグレーションのテスト"""

    def test_migration_creates_subagent_history_table(self, tmp_path):
        """v3→v4マイグレーションでsubagent_historyテーブルが作成される"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()

        # テーブル存在確認
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subagent_history'"
        )
        assert cursor.fetchone() is not None

        # スキーマバージョン確認
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        assert version >= 4

        db.close()

    def test_migration_from_v3_to_v4(self, tmp_path):
        """既存v3 DBからv4へのマイグレーションが正常動作する"""
        import sqlite3

        db_path = tmp_path / ".claude-nagger" / "state.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # v3相当のDBを手動作成
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version (version, applied_at) VALUES (3, '2025-01-01T00:00:00+00:00');

            CREATE TABLE subagents (
                agent_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_type TEXT NOT NULL DEFAULT 'unknown',
                role TEXT,
                role_source TEXT,
                created_at TEXT NOT NULL,
                startup_processed INTEGER NOT NULL DEFAULT 0,
                startup_processed_at TEXT,
                task_match_index INTEGER,
                leader_transcript_path TEXT
            );

            CREATE TABLE task_spawns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                transcript_index INTEGER NOT NULL,
                subagent_type TEXT,
                role TEXT,
                prompt_hash TEXT,
                tool_use_id TEXT,
                matched_agent_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, transcript_index)
            );

            CREATE TABLE sessions (
                session_id TEXT NOT NULL,
                hook_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_tokens INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                expired_at TEXT,
                PRIMARY KEY (session_id, hook_name)
            );

            CREATE TABLE hook_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                hook_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                agent_id TEXT,
                timestamp TEXT NOT NULL,
                result TEXT,
                details TEXT,
                duration_ms INTEGER
            );
        """)
        conn.close()

        # NaggerStateDBで開くとv4マイグレーションが実行される
        db = NaggerStateDB(db_path)
        db.connect()

        # subagent_historyテーブルが存在する
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='subagent_history'"
        )
        assert cursor.fetchone() is not None

        # バージョン4が記録されている
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 4

        db.close()


class TestIntegrationUnregisterAndHistory:
    """unregister→履歴参照の統合テスト"""

    def test_full_lifecycle(self, db):
        """register→unregister→get_by_sessionの一連の流れ"""
        repo = SubagentRepository(db)
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-lifecycle"

        # 3つのsubagentを登録
        repo.register("a1", session_id, "gp", role="coder")
        repo.register("a2", session_id, "gp", role="reviewer")
        repo.register("a3", session_id, "gp", role="tester")

        # 2つをunregister
        repo.unregister("a1")
        repo.unregister("a2")

        # a3はまだアクティブ
        assert repo.get("a3") is not None

        # 履歴には2件
        history = history_repo.get_by_session(session_id)
        assert len(history) == 2
        history_agent_ids = {h["agent_id"] for h in history}
        assert history_agent_ids == {"a1", "a2"}

        # statsで確認
        stats = history_repo.get_stats(session_id=session_id)
        assert stats["total"] == 2
        assert stats["by_role"]["coder"] == 1
        assert stats["by_role"]["reviewer"] == 1


class TestGetPreviousSessionId:
    """get_previous_session_idのテスト（issue_6095）"""

    def _insert_history(self, db, agent_id, session_id, role=None,
                        started_at=None, stopped_at=None):
        """テスト用履歴レコードを直接INSERT"""
        if started_at is None:
            started_at = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            """
            INSERT INTO subagent_history
                (agent_id, session_id, agent_type, role, started_at, stopped_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (agent_id, session_id, "general-purpose", role, started_at, stopped_at),
        )
        db.conn.commit()

    def test_returns_previous_session(self, db):
        """現在セッションより前のセッションIDを返す"""
        history_repo = SubagentHistoryRepository(db)

        # 前セッションの履歴
        self._insert_history(db, "a1", "session-prev", role="coder",
                             started_at="2025-01-01T00:00:00+00:00",
                             stopped_at="2025-01-01T00:10:00+00:00")
        # 現在セッションの履歴
        self._insert_history(db, "a2", "session-current", role="reviewer",
                             started_at="2025-01-02T00:00:00+00:00",
                             stopped_at="2025-01-02T00:10:00+00:00")

        result = history_repo.get_previous_session_id("session-current")
        assert result == "session-prev"

    def test_returns_none_when_no_history(self, db):
        """履歴が全くない場合はNoneを返す"""
        history_repo = SubagentHistoryRepository(db)
        result = history_repo.get_previous_session_id("session-any")
        assert result is None

    def test_returns_none_when_only_current_session(self, db):
        """現在セッションの履歴のみの場合はNoneを返す"""
        history_repo = SubagentHistoryRepository(db)

        self._insert_history(db, "a1", "session-only", role="coder",
                             started_at="2025-01-01T00:00:00+00:00")

        result = history_repo.get_previous_session_id("session-only")
        assert result is None

    def test_returns_latest_when_current_has_no_records(self, db):
        """現在セッションにレコードがない場合は全体の最新セッションIDを返す"""
        history_repo = SubagentHistoryRepository(db)

        self._insert_history(db, "a1", "session-old", role="coder",
                             started_at="2025-01-01T00:00:00+00:00")
        self._insert_history(db, "a2", "session-newer", role="reviewer",
                             started_at="2025-01-02T00:00:00+00:00")

        # 存在しないセッションIDで問い合わせ
        result = history_repo.get_previous_session_id("session-nonexistent")
        assert result == "session-newer"

    def test_multiple_previous_sessions_returns_latest(self, db):
        """複数の前セッションがある場合は最新のものを返す"""
        history_repo = SubagentHistoryRepository(db)

        self._insert_history(db, "a1", "session-old", role="coder",
                             started_at="2025-01-01T00:00:00+00:00")
        self._insert_history(db, "a2", "session-middle", role="reviewer",
                             started_at="2025-01-02T00:00:00+00:00")
        self._insert_history(db, "a3", "session-current", role="tester",
                             started_at="2025-01-03T00:00:00+00:00")

        result = history_repo.get_previous_session_id("session-current")
        assert result == "session-middle"

    def test_excludes_current_session_id(self, db):
        """現在セッション自身は除外される"""
        history_repo = SubagentHistoryRepository(db)

        # 同一セッションに複数レコード
        self._insert_history(db, "a1", "session-same", role="coder",
                             started_at="2025-01-01T00:00:00+00:00")
        self._insert_history(db, "a2", "session-same", role="reviewer",
                             started_at="2025-01-01T01:00:00+00:00")

        result = history_repo.get_previous_session_id("session-same")
        assert result is None


class TestCleanupSessionHistoryCopy:
    """cleanup_session時のhistoryコピー確認（issue_6090）"""

    def test_cleanup_session_copies_to_history(self, db):
        """cleanup_session()がDELETE前にsubagent_historyへコピーする"""
        repo = SubagentRepository(db)
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-cleanup-hist"

        repo.register("a1", session_id, "gp", role="coder")
        repo.register("a2", session_id, "gp", role="reviewer")

        deleted = repo.cleanup_session(session_id)
        assert deleted == 2

        # subagentsからは全削除
        assert repo.get("a1") is None
        assert repo.get("a2") is None

        # subagent_historyに2件コピーされている
        history = history_repo.get_by_session(session_id)
        assert len(history) == 2
        agent_ids = {h["agent_id"] for h in history}
        assert agent_ids == {"a1", "a2"}

    def test_cleanup_session_records_stopped_at(self, db):
        """cleanup_session()がstopped_atを記録する"""
        repo = SubagentRepository(db)
        session_id = "session-cleanup-stop"

        repo.register("a1", session_id, "gp")

        before = datetime.now(timezone.utc)
        repo.cleanup_session(session_id)
        after = datetime.now(timezone.utc)

        cursor = db.conn.execute(
            "SELECT stopped_at FROM subagent_history WHERE agent_id = ?",
            ("a1",),
        )
        stopped_at_str = cursor.fetchone()[0]
        assert stopped_at_str is not None

        stopped_at = datetime.fromisoformat(stopped_at_str)
        assert before <= stopped_at <= after

    def test_cleanup_session_copies_all_fields(self, db):
        """cleanup_session()が全フィールドを正しくコピーする"""
        repo = SubagentRepository(db)
        session_id = "session-cleanup-fields"
        leader_tp = "/path/to/leader.jsonl"

        repo.register("a1", session_id, "general-purpose",
                       role="coder", leader_transcript_path=leader_tp)
        repo.update_role("a1", "reviewer", "task_match")

        # subagentsのcreated_atを取得
        record = repo.get("a1")
        original_created_at = record.created_at

        repo.cleanup_session(session_id)

        cursor = db.conn.execute(
            """SELECT agent_id, session_id, agent_type, role, role_source,
                      leader_transcript_path, started_at
               FROM subagent_history WHERE agent_id = ?""",
            ("a1",),
        )
        row = cursor.fetchone()
        assert row[0] == "a1"
        assert row[1] == session_id
        assert row[2] == "general-purpose"
        assert row[3] == "reviewer"
        assert row[4] == "task_match"
        assert row[5] == leader_tp
        assert row[6] == original_created_at

    def test_cleanup_session_no_agents_no_history(self, db):
        """対象agentがない場合はhistoryも作成されない"""
        repo = SubagentRepository(db)
        history_repo = SubagentHistoryRepository(db)

        deleted = repo.cleanup_session("nonexistent-session")
        assert deleted == 0

        history = history_repo.get_by_session("nonexistent-session")
        assert history == []

    def test_cleanup_session_other_session_unaffected(self, db):
        """他セッションのsubagentはhistoryにコピーされない"""
        repo = SubagentRepository(db)
        history_repo = SubagentHistoryRepository(db)
        target_session = "session-cleanup-target"
        other_session = "session-cleanup-other"

        repo.register("a1", target_session, "gp", role="coder")
        repo.register("a2", other_session, "gp", role="reviewer")

        repo.cleanup_session(target_session)

        # ターゲットのみhistoryにコピー
        history = history_repo.get_by_session(target_session)
        assert len(history) == 1
        assert history[0]["agent_id"] == "a1"

        # 他セッションのsubagentは残っている
        assert repo.get("a2") is not None
        # 他セッションのhistoryは空
        other_history = history_repo.get_by_session(other_session)
        assert other_history == []

    def test_cleanup_session_already_unregistered_no_duplicate(self, db):
        """unregister済みのagentはcleanup_sessionで重複コピーしない"""
        repo = SubagentRepository(db)
        history_repo = SubagentHistoryRepository(db)
        session_id = "session-cleanup-dedup"

        repo.register("a1", session_id, "gp", role="coder")
        repo.register("a2", session_id, "gp", role="reviewer")

        # a1だけ先にunregister
        repo.unregister("a1")

        # cleanup_sessionで残りを削除
        deleted = repo.cleanup_session(session_id)
        assert deleted == 1  # a2のみ削除

        # historyにはa1とa2が各1件ずつ（重複なし）
        history = history_repo.get_by_session(session_id)
        assert len(history) == 2
        agent_ids = {h["agent_id"] for h in history}
        assert agent_ids == {"a1", "a2"}
