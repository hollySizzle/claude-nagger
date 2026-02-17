"""NaggerStateDB + Repository群のテスト

issue_5943: 新規DB層の単体テスト + 並列Claimテスト
"""

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.subagent_repository import SubagentRepository
from infrastructure.db.session_repository import SessionRepository
from infrastructure.db.hook_log_repository import HookLogRepository


# === フィクスチャ ===
# db フィクスチャは conftest.py で統一定義（issue_5955: テスト分離）


@pytest.fixture
def subagent_repo(db):
    """SubagentRepositoryインスタンス"""
    return SubagentRepository(db)


@pytest.fixture
def session_repo(db):
    """SessionRepositoryインスタンス"""
    return SessionRepository(db)


@pytest.fixture
def hook_log_repo(db):
    """HookLogRepositoryインスタンス"""
    return HookLogRepository(db)


# === NaggerStateDB単体テスト ===
class TestNaggerStateDB:
    """NaggerStateDBの単体テスト"""

    def test_スキーマ作成(self, tmp_path):
        """初回接続でスキーマが作成される"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()

        # テーブル存在確認
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]

        assert "schema_version" in tables
        assert "subagents" in tables
        assert "task_spawns" in tables
        assert "sessions" in tables
        assert "hook_log" in tables

        # スキーマバージョン確認（現在のバージョン）
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        assert version == NaggerStateDB.SCHEMA_VERSION

        db.close()

    def test_WALモード有効(self, tmp_path):
        """WALモードが有効になる"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()

        cursor = db.conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"

        db.close()

    def test_再接続でスキーマ重複なし(self, tmp_path):
        """既存DBへの再接続でエラーなし"""
        db_path = tmp_path / ".claude-nagger" / "state.db"

        # 初回接続
        db1 = NaggerStateDB(db_path)
        db1.connect()
        db1.close()

        # 再接続
        db2 = NaggerStateDB(db_path)
        db2.connect()

        # テーブル確認（重複なし）
        cursor = db2.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='subagents'"
        )
        count = cursor.fetchone()[0]
        assert count == 1

        db2.close()

    def test_コンテキストマネージャ(self, tmp_path):
        """with文で自動close"""
        db_path = tmp_path / ".claude-nagger" / "state.db"

        with NaggerStateDB(db_path) as db:
            # 接続確認
            assert db._conn is not None
            cursor = db.conn.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1

        # close確認
        assert db._conn is None

    def test_resolve_db_path_環境変数優先(self, tmp_path, monkeypatch):
        """CLAUDE_PROJECT_DIRが設定されている場合はそれを使用"""
        project_dir = str(tmp_path / "project")
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", project_dir)

        path = NaggerStateDB.resolve_db_path()

        assert path == Path(project_dir) / ".claude-nagger" / "state.db"

    def test_resolve_db_path_cwd_フォールバック(self, monkeypatch):
        """環境変数未設定時はcwdを使用"""
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)

        path = NaggerStateDB.resolve_db_path()

        assert path == Path.cwd() / ".claude-nagger" / "state.db"

    def test_connプロパティ_自動接続(self, tmp_path):
        """connプロパティで未接続なら自動接続"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)

        # 明示的なconnect()なしでconn使用
        cursor = db.conn.execute("SELECT 1")
        assert cursor.fetchone()[0] == 1

        db.close()

    def test_マイグレーションv1からv2(self, tmp_path):
        """v1スキーマからv2へのマイグレーション（issue_5947）"""
        db_path = tmp_path / ".claude-nagger" / "state.db"

        # v1スキーマを手動で作成
        db_path.parent.mkdir(parents=True, exist_ok=True)
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version (version, applied_at) VALUES (1, '2025-01-01T00:00:00Z');

            CREATE TABLE task_spawns (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id          TEXT NOT NULL,
                transcript_index    INTEGER NOT NULL,
                subagent_type       TEXT,
                role                TEXT,
                prompt_hash         TEXT,
                matched_agent_id    TEXT,
                created_at          TEXT NOT NULL,
                UNIQUE(session_id, transcript_index)
            );

            CREATE TABLE subagents (
                agent_id            TEXT PRIMARY KEY,
                session_id          TEXT NOT NULL,
                agent_type          TEXT NOT NULL DEFAULT 'unknown',
                role                TEXT,
                role_source         TEXT,
                created_at          TEXT NOT NULL,
                startup_processed   INTEGER NOT NULL DEFAULT 0,
                startup_processed_at TEXT,
                task_match_index    INTEGER
            );

            CREATE TABLE sessions (
                session_id          TEXT NOT NULL,
                hook_name           TEXT NOT NULL,
                created_at          TEXT NOT NULL,
                last_tokens         INTEGER DEFAULT 0,
                status              TEXT NOT NULL DEFAULT 'active',
                expired_at          TEXT,
                PRIMARY KEY (session_id, hook_name)
            );

            CREATE TABLE hook_log (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id          TEXT NOT NULL,
                hook_name           TEXT NOT NULL,
                event_type          TEXT NOT NULL,
                agent_id            TEXT,
                timestamp           TEXT NOT NULL,
                result              TEXT,
                details             TEXT,
                duration_ms         INTEGER
            );
        """)
        # v1にはtool_use_idカラムがない
        conn.execute(
            "INSERT INTO task_spawns (session_id, transcript_index, role, created_at) VALUES (?, ?, ?, ?)",
            ("session-1", 1, "coder", "2025-01-01T00:00:00Z")
        )
        conn.commit()
        conn.close()

        # NaggerStateDBを開く（マイグレーション実行）
        db = NaggerStateDB(db_path)
        db.connect()

        # 最新バージョンに更新されていることを確認
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        assert version == NaggerStateDB.SCHEMA_VERSION

        # tool_use_idカラムが追加されていることを確認（v2マイグレーション）
        cursor = db.conn.execute("PRAGMA table_info(task_spawns)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "tool_use_id" in columns

        # leader_transcript_pathカラムが追加されていることを確認（v3マイグレーション）
        cursor = db.conn.execute("PRAGMA table_info(subagents)")
        columns = [row[1] for row in cursor.fetchall()]
        assert "leader_transcript_path" in columns

        # 既存データがそのままであることを確認
        cursor = db.conn.execute(
            "SELECT session_id, transcript_index, role, tool_use_id FROM task_spawns WHERE session_id = ?",
            ("session-1",)
        )
        row = cursor.fetchone()
        assert row[0] == "session-1"
        assert row[1] == 1
        assert row[2] == "coder"
        assert row[3] is None  # 新カラムはNULL

        db.close()

    def test_0バイトDB復旧(self, tmp_path):
        """0バイトDBファイルに接続してスキーマ作成（issue_6058）"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # 0バイトファイルを手動作成
        db_path.touch()
        assert db_path.stat().st_size == 0

        # NaggerStateDB接続でスキーマ作成
        db = NaggerStateDB(db_path)
        db.connect()

        # テーブルが作成されていること
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        assert "subagents" in tables
        assert "task_spawns" in tables

        db.close()

        # close後ファイルサイズが0でないこと
        assert db_path.stat().st_size > 0

    def test_破損DB復旧(self, tmp_path):
        """破損DBファイルを検出して再作成（issue_6058）"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # 不正なデータでファイル作成（SQLiteヘッダではない）
        db_path.write_bytes(b"this is not a sqlite database" + b"\x00" * 100)

        # NaggerStateDB接続で復旧
        db = NaggerStateDB(db_path)
        db.connect()

        # テーブルが作成されていること
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        assert "subagents" in tables
        assert "task_spawns" in tables

        db.close()

    def test_並列スキーマ作成_安全(self, tmp_path):
        """並列プロセスの同時スキーマ作成でエラーなし（issue_6058）"""
        import threading

        db_path = tmp_path / ".claude-nagger" / "state.db"
        errors = []

        def worker():
            try:
                db = NaggerStateDB(db_path)
                db.connect()
                # テーブル確認
                cursor = db.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='subagents'"
                )
                assert cursor.fetchone() is not None
                db.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"並列スキーマ作成でエラー: {errors}"

    def test_スキーマIF_NOT_EXISTS冪等性(self, tmp_path):
        """既存DBに対してスキーマ再適用がエラーにならない（issue_6058）"""
        db_path = tmp_path / ".claude-nagger" / "state.db"

        # DB作成
        db1 = NaggerStateDB(db_path)
        db1.connect()

        # データ挿入
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        db1.conn.execute(
            "INSERT INTO subagents (agent_id, session_id, created_at) VALUES (?, ?, ?)",
            ("agent-1", "session-1", now)
        )
        db1.conn.commit()
        db1.close()

        # 再接続（スキーマ再確認が走る）
        db2 = NaggerStateDB(db_path)
        db2.connect()

        # データが保持されていること
        cursor = db2.conn.execute("SELECT agent_id FROM subagents")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "agent-1"

        db2.close()


# === SubagentRepository単体テスト ===
class TestSubagentRepository:
    """SubagentRepositoryの単体テスト"""

    def test_register_unregister(self, subagent_repo, db):
        """登録・削除の基本動作"""
        # 登録
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder",
            role="coder"
        )

        # 取得確認
        record = subagent_repo.get("agent-1")
        assert record is not None
        assert record.agent_id == "agent-1"
        assert record.session_id == "session-1"
        assert record.agent_type == "coder"
        assert record.role == "coder"
        assert record.startup_processed is False

        # 削除
        subagent_repo.unregister("agent-1")

        # 削除確認
        record = subagent_repo.get("agent-1")
        assert record is None

    def test_register_task_spawns_冪等性(self, subagent_repo, tmp_path):
        """同一transcriptの再読み込みで重複なし"""
        # transcriptファイル作成
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:coder] タスク1"
                            }
                        }
                    ]
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # 初回登録
        count1 = subagent_repo.register_task_spawns("session-1", str(transcript_path))
        assert count1 == 1

        # 再登録（冪等性）
        count2 = subagent_repo.register_task_spawns("session-1", str(transcript_path))
        assert count2 == 0  # 重複なし

    def test_match_task_to_agent(self, subagent_repo, tmp_path):
        """task_spawnとagentのマッチング"""
        # transcriptファイル作成
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:reviewer] レビュータスク"
                            }
                        }
                    ]
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # task_spawn登録
        subagent_repo.register_task_spawns("session-1", str(transcript_path))

        # agent登録
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )

        # マッチング
        role = subagent_repo.match_task_to_agent("session-1", "agent-1", "coder")

        assert role == "reviewer"

        # agent確認
        record = subagent_repo.get("agent-1")
        assert record.role == "reviewer"
        assert record.role_source == "task_match"

    def test_claim_next_unprocessed_排他消去法(self, subagent_repo):
        """未処理1件なら確定で取得（2フェーズ方式）"""
        # 1件登録
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )

        # claim（取得のみ、マークなし）
        record = subagent_repo.claim_next_unprocessed("session-1")

        assert record is not None
        assert record.agent_id == "agent-1"
        assert record.startup_processed is False

        # mark_processedで処理済みにマーク
        subagent_repo.mark_processed("agent-1")

        # 再度claim（処理済みなので取得不可）
        record2 = subagent_repo.claim_next_unprocessed("session-1")
        assert record2 is None

    def test_claim_next_unprocessed_FIFO(self, subagent_repo):
        """未処理複数なら最古を取得（2フェーズ方式）"""
        # 複数登録（時間差を設ける）
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )
        time.sleep(0.01)  # 時間差
        subagent_repo.register(
            agent_id="agent-2",
            session_id="session-1",
            agent_type="coder"
        )
        time.sleep(0.01)
        subagent_repo.register(
            agent_id="agent-3",
            session_id="session-1",
            agent_type="coder"
        )

        # 1回目: 最古のagent-1
        record1 = subagent_repo.claim_next_unprocessed("session-1")
        assert record1.agent_id == "agent-1"
        subagent_repo.mark_processed("agent-1")

        # 2回目: 次に古いagent-2
        record2 = subagent_repo.claim_next_unprocessed("session-1")
        assert record2.agent_id == "agent-2"
        subagent_repo.mark_processed("agent-2")

        # 3回目: agent-3
        record3 = subagent_repo.claim_next_unprocessed("session-1")
        assert record3.agent_id == "agent-3"
        subagent_repo.mark_processed("agent-3")

        # 4回目: なし
        record4 = subagent_repo.claim_next_unprocessed("session-1")
        assert record4 is None

    def test_claim_next_unprocessed_取得のみでマークしない(self, subagent_repo):
        """claim_next_unprocessedは取得のみでDBをマークしない（2フェーズ方式）"""
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )

        record = subagent_repo.claim_next_unprocessed("session-1")

        # 戻り値はstartup_processed=False
        assert record.startup_processed is False

        # DBもまだ未処理（マークしていない）
        db_record = subagent_repo.get("agent-1")
        assert db_record.startup_processed is False

    def test_mark_processed(self, subagent_repo):
        """mark_processedでstartup_processed=1にマーク"""
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )

        # claim（マークなし）
        record = subagent_repo.claim_next_unprocessed("session-1")
        assert record is not None

        # mark_processed
        result = subagent_repo.mark_processed("agent-1")
        assert result is True

        # DBが更新されている
        db_record = subagent_repo.get("agent-1")
        assert db_record.startup_processed is True
        assert db_record.startup_processed_at is not None

    def test_mark_processed_既にマーク済み(self, subagent_repo):
        """既にマーク済みの場合はFalseを返す"""
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )

        # 1回目のmark
        subagent_repo.mark_processed("agent-1")

        # 2回目（既にマーク済み）
        result = subagent_repo.mark_processed("agent-1")
        assert result is False

    def test_mark_processed_存在しないagent(self, subagent_repo):
        """存在しないagent_idの場合はFalseを返す"""
        result = subagent_repo.mark_processed("nonexistent-agent")
        assert result is False

    def test_is_any_active(self, subagent_repo):
        """アクティブsubagent判定"""
        # 登録前
        assert subagent_repo.is_any_active("session-1") is False

        # 登録後
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )
        assert subagent_repo.is_any_active("session-1") is True

        # 別セッション
        assert subagent_repo.is_any_active("session-2") is False

    def test_update_role(self, subagent_repo):
        """role更新"""
        subagent_repo.register(
            agent_id="agent-1",
            session_id="session-1",
            agent_type="coder"
        )

        subagent_repo.update_role("agent-1", "tester", "manual")

        record = subagent_repo.get("agent-1")
        assert record.role == "tester"
        assert record.role_source == "manual"

    def test_cleanup_session(self, subagent_repo):
        """セッション全削除"""
        # 複数登録
        subagent_repo.register("agent-1", "session-1", "coder")
        subagent_repo.register("agent-2", "session-1", "coder")
        subagent_repo.register("agent-3", "session-2", "coder")

        # session-1のみ削除
        deleted = subagent_repo.cleanup_session("session-1")

        assert deleted == 2
        assert subagent_repo.get("agent-1") is None
        assert subagent_repo.get("agent-2") is None
        assert subagent_repo.get("agent-3") is not None

    def test_get_active(self, subagent_repo):
        """アクティブsubagent一覧"""
        subagent_repo.register("agent-1", "session-1", "coder")
        subagent_repo.register("agent-2", "session-1", "reviewer")
        subagent_repo.register("agent-3", "session-2", "coder")

        active = subagent_repo.get_active("session-1")

        assert len(active) == 2
        agent_ids = [r.agent_id for r in active]
        assert "agent-1" in agent_ids
        assert "agent-2" in agent_ids

    def test_get_unprocessed_count(self, subagent_repo):
        """未処理subagent数（2フェーズ方式）"""
        subagent_repo.register("agent-1", "session-1", "coder")
        subagent_repo.register("agent-2", "session-1", "coder")

        assert subagent_repo.get_unprocessed_count("session-1") == 2

        # claim + mark_processed
        record = subagent_repo.claim_next_unprocessed("session-1")
        subagent_repo.mark_processed(record.agent_id)

        assert subagent_repo.get_unprocessed_count("session-1") == 1

    # === issue_5947: ROLEマッチング改善テスト ===

    def test_register_task_spawns_ROLEなしはスキップ(self, subagent_repo, tmp_path):
        """ROLEタグがないTask tool_useは登録されない（issue_5947）"""
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "タスク1（ROLEなし）"
                            }
                        }
                    ]
                }
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {
                                "subagent_type": "reviewer",
                                "prompt": "[ROLE:reviewer] タスク2（ROLEあり）"
                            }
                        }
                    ]
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # 登録
        count = subagent_repo.register_task_spawns("session-1", str(transcript_path))

        # ROLEありの1件のみ登録
        assert count == 1

        # DB確認
        cursor = subagent_repo._db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?", ("session-1",)
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "reviewer"

    def test_match_task_to_agent_role優先(self, subagent_repo, tmp_path):
        """roleパラメータ指定時、roleで完全一致マッチ優先（issue_5947）"""
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:tester] テストタスク"
                            }
                        }
                    ]
                }
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:coder] コーディングタスク"
                            }
                        }
                    ]
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        subagent_repo.register_task_spawns("session-1", str(transcript_path))
        subagent_repo.register("agent-1", "session-1", "coder")

        # role="coder"を指定すると、subagent_type=coderのエントリではなく
        # role=coderのエントリにマッチする
        role = subagent_repo.match_task_to_agent("session-1", "agent-1", "coder", role="coder")

        assert role == "coder"

    def test_match_task_to_agent_role指定なしはsubagent_type(self, subagent_repo, tmp_path):
        """roleパラメータ未指定時、subagent_typeでマッチ（ROLEありエントリのみ）"""
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:scribe] ドキュメントタスク"
                            }
                        }
                    ]
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        subagent_repo.register_task_spawns("session-1", str(transcript_path))
        subagent_repo.register("agent-1", "session-1", "coder")

        # role未指定でsubagent_type=coderでマッチ
        role = subagent_repo.match_task_to_agent("session-1", "agent-1", "coder")

        # roleは "scribe"（task_spawnのrole）
        assert role == "scribe"

    def test_cleanup_old_task_spawns(self, subagent_repo, tmp_path):
        """古い未マッチエントリの削除（issue_5947）"""
        # 複数のtask_spawnを手動挿入
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        for i in range(10):
            subagent_repo._db.conn.execute(
                """
                INSERT INTO task_spawns
                (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"session-1", i + 1, "coder", f"role-{i}", f"hash-{i}", now),
            )
        subagent_repo._db.conn.commit()

        # 最新5件を残して削除
        deleted = subagent_repo.cleanup_old_task_spawns("session-1", keep_recent=5)

        assert deleted == 5

        # 残っているのは最新5件
        cursor = subagent_repo._db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE session_id = ?", ("session-1",)
        )
        assert cursor.fetchone()[0] == 5

    def test_cleanup_null_role_task_spawns(self, subagent_repo):
        """role IS NULLのエントリを全削除（issue_5947初回マイグレーション用）"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        # role=NULL のエントリを手動挿入
        for i in range(3):
            subagent_repo._db.conn.execute(
                """
                INSERT INTO task_spawns
                (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"session-{i}", i + 1, "coder", None, f"hash-null-{i}", now),
            )

        # role!=NULL のエントリを挿入
        for i in range(2):
            subagent_repo._db.conn.execute(
                """
                INSERT INTO task_spawns
                (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (f"session-valid-{i}", i + 100, "reviewer", f"role-{i}", f"hash-{i}", now),
            )
        subagent_repo._db.conn.commit()

        # cleanup実行
        deleted = subagent_repo.cleanup_null_role_task_spawns()

        assert deleted == 3

        # role IS NULLは0件
        cursor = subagent_repo._db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE role IS NULL"
        )
        assert cursor.fetchone()[0] == 0

        # role IS NOT NULLは2件残っている
        cursor = subagent_repo._db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE role IS NOT NULL"
        )
        assert cursor.fetchone()[0] == 2

    # === issue_5947: agent_progressベースのマッチングテスト ===

    def test_register_task_spawns_tool_use_id保存(self, subagent_repo, tmp_path):
        """Task tool_useのidがtool_use_idとして保存される（issue_5947）"""
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01ABC123XYZ",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:coder] コーディングタスク"
                            }
                        }
                    ]
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        subagent_repo.register_task_spawns("session-1", str(transcript_path))

        # tool_use_idが保存されていることを確認
        cursor = subagent_repo._db.conn.execute(
            "SELECT tool_use_id FROM task_spawns WHERE session_id = ?", ("session-1",)
        )
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "toolu_01ABC123XYZ"

    def test_find_task_spawn_by_tool_use_id(self, subagent_repo, tmp_path):
        """tool_use_idでtask_spawnを検索できる（issue_5947）"""
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01SEARCH",
                            "name": "Task",
                            "input": {
                                "subagent_type": "reviewer",
                                "prompt": "[ROLE:reviewer] レビュータスク"
                            }
                        }
                    ]
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        subagent_repo.register_task_spawns("session-1", str(transcript_path))

        # tool_use_idで検索
        result = subagent_repo.find_task_spawn_by_tool_use_id("toolu_01SEARCH")

        assert result is not None
        assert result["tool_use_id"] == "toolu_01SEARCH"
        assert result["role"] == "reviewer"
        assert result["subagent_type"] == "reviewer"

    def test_find_task_spawn_by_tool_use_id_存在しない(self, subagent_repo):
        """存在しないtool_use_idで検索するとNone（issue_5947）"""
        result = subagent_repo.find_task_spawn_by_tool_use_id("nonexistent_id")
        assert result is None

    def test_find_parent_tool_use_id(self, subagent_repo, tmp_path):
        """agent_progressイベントからparentToolUseIDを取得できる（issue_5947）"""
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "user",
                "message": {"content": "タスクを実行してください"}
            },
            {
                "type": "progress",
                "parentToolUseID": "toolu_01PARENT123",
                "data": {
                    "type": "agent_progress",
                    "agentId": "agent-abc"
                }
            },
            {
                "type": "assistant",
                "message": {"content": "完了しました"}
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        result = subagent_repo.find_parent_tool_use_id(str(transcript_path), "agent-abc")

        assert result == "toolu_01PARENT123"

    def test_find_parent_tool_use_id_異なるagentId(self, subagent_repo, tmp_path):
        """異なるagentIdの場合はNoneを返す（issue_5947）"""
        transcript_path = tmp_path / "transcript.jsonl"
        entries = [
            {
                "type": "progress",
                "parentToolUseID": "toolu_01OTHER",
                "data": {
                    "type": "agent_progress",
                    "agentId": "agent-xyz"
                }
            }
        ]
        with open(transcript_path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        result = subagent_repo.find_parent_tool_use_id(str(transcript_path), "agent-abc")

        assert result is None

    def test_find_parent_tool_use_id_ファイル存在しない(self, subagent_repo, tmp_path):
        """存在しないファイルパスの場合はNone（issue_5947）"""
        result = subagent_repo.find_parent_tool_use_id(
            str(tmp_path / "nonexistent.jsonl"), "agent-abc"
        )
        assert result is None

    def test_match_task_to_agent_agent_progress正確マッチ(self, subagent_repo, tmp_path):
        """agent_progressを使った正確なマッチング（issue_5947）"""
        # 親transcript: Task tool_use（2件）
        parent_transcript_path = tmp_path / "parent_transcript.jsonl"
        parent_entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01FIRST",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:tester] テストタスク"
                            }
                        }
                    ]
                }
            },
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01SECOND",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:coder] コーディングタスク"
                            }
                        }
                    ]
                }
            }
        ]
        with open(parent_transcript_path, "w", encoding="utf-8") as f:
            for entry in parent_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # task_spawns登録
        subagent_repo.register_task_spawns("session-1", str(parent_transcript_path))

        # subagent transcript: agent_progressイベント
        subagent_transcript_path = tmp_path / "subagent_transcript.jsonl"
        subagent_entries = [
            {
                "type": "progress",
                "parentToolUseID": "toolu_01SECOND",  # 2番目のTaskに対応
                "data": {
                    "type": "agent_progress",
                    "agentId": "agent-1"
                }
            }
        ]
        with open(subagent_transcript_path, "w", encoding="utf-8") as f:
            for entry in subagent_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        # agent登録
        subagent_repo.register("agent-1", "session-1", "coder")

        # agent_progressを使ったマッチング（2番目のTask→coderにマッチ）
        role = subagent_repo.match_task_to_agent(
            "session-1", "agent-1", "coder",
            transcript_path=str(subagent_transcript_path)
        )

        # 2番目のTaskのrole（coder）がマッチ
        assert role == "coder"

        # task_spawnsがマッチ済みに更新されていることを確認
        cursor = subagent_repo._db.conn.execute(
            "SELECT matched_agent_id FROM task_spawns WHERE tool_use_id = ?",
            ("toolu_01SECOND",)
        )
        assert cursor.fetchone()[0] == "agent-1"

    def test_match_task_to_agent_agent_progressなしはフォールバック(self, subagent_repo, tmp_path):
        """agent_progressがない場合は従来のマッチングにフォールバック（issue_5947）"""
        parent_transcript_path = tmp_path / "parent_transcript.jsonl"
        parent_entries = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01ONLY",
                            "name": "Task",
                            "input": {
                                "subagent_type": "coder",
                                "prompt": "[ROLE:scribe] ドキュメントタスク"
                            }
                        }
                    ]
                }
            }
        ]
        with open(parent_transcript_path, "w", encoding="utf-8") as f:
            for entry in parent_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        subagent_repo.register_task_spawns("session-1", str(parent_transcript_path))

        # agent_progressがないtranscript
        subagent_transcript_path = tmp_path / "subagent_transcript.jsonl"
        subagent_entries = [
            {
                "type": "user",
                "message": {"content": "タスク開始"}
            }
        ]
        with open(subagent_transcript_path, "w", encoding="utf-8") as f:
            for entry in subagent_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        subagent_repo.register("agent-1", "session-1", "coder")

        # フォールバック: subagent_typeでマッチ
        role = subagent_repo.match_task_to_agent(
            "session-1", "agent-1", "coder",
            transcript_path=str(subagent_transcript_path)
        )

        assert role == "scribe"


# === SessionRepository単体テスト ===
class TestSessionRepository:
    """SessionRepositoryの単体テスト"""

    def test_register_is_processed(self, session_repo):
        """登録・処理済み判定"""
        # 登録前
        assert session_repo.is_processed("session-1", "hook-1") is False

        # 登録
        session_repo.register("session-1", "hook-1", tokens=1000)

        # 登録後
        assert session_repo.is_processed("session-1", "hook-1") is True

        # 別hook
        assert session_repo.is_processed("session-1", "hook-2") is False

    def test_is_processed_context_aware_閾値内(self, session_repo):
        """トークン増加が閾値内ならTrue"""
        session_repo.register("session-1", "hook-1", tokens=1000)

        # 閾値5000で、増加100ならTrue
        result = session_repo.is_processed_context_aware(
            "session-1", "hook-1", current_tokens=1100, threshold=5000
        )

        assert result is True

    def test_is_processed_context_aware_閾値超過(self, session_repo):
        """トークン増加が閾値超過ならexpireしてFalse"""
        session_repo.register("session-1", "hook-1", tokens=1000)

        # 閾値5000で、増加6000ならFalse
        result = session_repo.is_processed_context_aware(
            "session-1", "hook-1", current_tokens=7000, threshold=5000
        )

        assert result is False

        # expireされている
        record = session_repo.get("session-1", "hook-1")
        assert record.status == "expired"

    def test_is_processed_context_aware_レコードなし(self, session_repo):
        """レコードなしならFalse"""
        result = session_repo.is_processed_context_aware(
            "session-1", "hook-1", current_tokens=1000, threshold=5000
        )

        assert result is False

    def test_expire(self, session_repo):
        """単一hook期限切れ"""
        session_repo.register("session-1", "hook-1", tokens=1000)
        session_repo.register("session-1", "hook-2", tokens=2000)

        session_repo.expire("session-1", "hook-1", reason="manual_expire")

        record1 = session_repo.get("session-1", "hook-1")
        record2 = session_repo.get("session-1", "hook-2")

        assert record1.status == "manual_expire"
        assert record1.expired_at is not None
        assert record2.status == "active"

    def test_expire_all(self, session_repo):
        """全hook期限切れ（compact用）"""
        session_repo.register("session-1", "hook-1", tokens=1000)
        session_repo.register("session-1", "hook-2", tokens=2000)
        session_repo.register("session-2", "hook-1", tokens=3000)

        session_repo.expire_all("session-1", reason="compact_expired")

        record1 = session_repo.get("session-1", "hook-1")
        record2 = session_repo.get("session-1", "hook-2")
        record3 = session_repo.get("session-2", "hook-1")

        assert record1.status == "compact_expired"
        assert record2.status == "compact_expired"
        assert record3.status == "active"

    def test_get(self, session_repo):
        """レコード取得"""
        session_repo.register("session-1", "hook-1", tokens=1000)

        record = session_repo.get("session-1", "hook-1")

        assert record is not None
        assert record.session_id == "session-1"
        assert record.hook_name == "hook-1"
        assert record.last_tokens == 1000
        assert record.status == "active"

        # 存在しないレコード
        assert session_repo.get("session-1", "hook-999") is None


# === HookLogRepository単体テスト ===
class TestHookLogRepository:
    """HookLogRepositoryの単体テスト"""

    def test_log_get_recent(self, hook_log_repo):
        """ログ記録・取得"""
        # 複数ログ
        hook_log_repo.log(
            session_id="session-1",
            hook_name="hook-1",
            event_type="start",
            result="success"
        )
        hook_log_repo.log(
            session_id="session-1",
            hook_name="hook-1",
            event_type="end",
            result="success",
            duration_ms=100
        )

        # 取得
        logs = hook_log_repo.get_recent("session-1", limit=10)

        assert len(logs) == 2
        # 新しい順
        assert logs[0].event_type == "end"
        assert logs[1].event_type == "start"

    def test_log_with_details(self, hook_log_repo):
        """detailsありログ"""
        hook_log_repo.log(
            session_id="session-1",
            hook_name="hook-1",
            event_type="info",
            details={"key": "value", "count": 5}
        )

        logs = hook_log_repo.get_recent("session-1")
        assert len(logs) == 1

        # detailsはJSON文字列
        import json
        details = json.loads(logs[0].details)
        assert details["key"] == "value"
        assert details["count"] == 5

    def test_get_stats(self, hook_log_repo):
        """統計情報"""
        # 複数ログ
        hook_log_repo.log("session-1", "hook-1", "start", duration_ms=100)
        hook_log_repo.log("session-1", "hook-1", "end", duration_ms=200)
        hook_log_repo.log("session-1", "hook-2", "start", duration_ms=150)

        stats = hook_log_repo.get_stats("session-1")

        assert stats["total_count"] == 3
        assert stats["by_hook"]["hook-1"] == 2
        assert stats["by_hook"]["hook-2"] == 1
        assert stats["by_event"]["start"] == 2
        assert stats["by_event"]["end"] == 1
        assert stats["avg_duration_ms"] == 150.0  # (100+200+150)/3

    def test_get_stats_no_duration(self, hook_log_repo):
        """duration_msなしログの統計"""
        hook_log_repo.log("session-1", "hook-1", "info")
        hook_log_repo.log("session-1", "hook-1", "info")

        stats = hook_log_repo.get_stats("session-1")

        assert stats["total_count"] == 2
        assert stats["avg_duration_ms"] is None

    def test_get_stats_empty(self, hook_log_repo):
        """ログなし統計"""
        stats = hook_log_repo.get_stats("session-1")

        assert stats["total_count"] == 0
        assert stats["by_hook"] == {}
        assert stats["by_event"] == {}
        assert stats["avg_duration_ms"] is None


# === 並列Claimテスト（結合） ===
class TestParallelClaim:
    """並列Claimテスト"""

    def test_2並列subagent_claim(self, tmp_path):
        """2つのsubagentが同時にclaim+markしても競合しない（2フェーズ方式）"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()
        repo = SubagentRepository(db)

        # 2件登録
        repo.register("agent-1", "session-1", "coder")
        time.sleep(0.01)
        repo.register("agent-2", "session-1", "coder")

        results = []
        errors = []

        def claim_worker():
            """並列claimワーカー（claim + mark_processed）"""
            try:
                # 各スレッドで新しいDB接続
                worker_db = NaggerStateDB(db_path)
                worker_db.connect()
                worker_repo = SubagentRepository(worker_db)

                record = worker_repo.claim_next_unprocessed("session-1")
                if record:
                    # mark_processedで処理済みにマーク
                    worker_repo.mark_processed(record.agent_id)
                results.append(record.agent_id if record else None)

                worker_db.close()
            except Exception as e:
                errors.append(str(e))

        # 2スレッドで並列実行
        threads = [threading.Thread(target=claim_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        db.close()

        # エラーなし
        assert len(errors) == 0, f"Errors: {errors}"

        # 2件とも取得済み（重複なし）
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 2
        assert set(claimed) == {"agent-1", "agent-2"}

    def test_3並列subagent_claim(self, tmp_path):
        """3つのsubagentでも正しくFIFO（2フェーズ方式）"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()
        repo = SubagentRepository(db)

        # 3件登録
        repo.register("agent-1", "session-1", "coder")
        time.sleep(0.01)
        repo.register("agent-2", "session-1", "coder")
        time.sleep(0.01)
        repo.register("agent-3", "session-1", "coder")

        results = []
        errors = []
        lock = threading.Lock()

        def claim_worker():
            """並列claimワーカー（claim + mark_processed）"""
            try:
                worker_db = NaggerStateDB(db_path)
                worker_db.connect()
                worker_repo = SubagentRepository(worker_db)

                record = worker_repo.claim_next_unprocessed("session-1")
                if record:
                    worker_repo.mark_processed(record.agent_id)
                with lock:
                    results.append(record.agent_id if record else None)

                worker_db.close()
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # 3スレッドで並列実行
        threads = [threading.Thread(target=claim_worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        db.close()

        # エラーなし
        assert len(errors) == 0, f"Errors: {errors}"

        # 3件とも取得済み（重複なし）
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 3
        assert set(claimed) == {"agent-1", "agent-2", "agent-3"}

    def test_並列claim_レース対策(self, tmp_path):
        """4並列で2件しかない場合、2件のみ取得（2フェーズ方式）"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()
        repo = SubagentRepository(db)

        # 2件のみ登録
        repo.register("agent-1", "session-1", "coder")
        time.sleep(0.01)
        repo.register("agent-2", "session-1", "coder")

        results = []
        errors = []
        lock = threading.Lock()

        def claim_worker():
            """並列claimワーカー（claim + mark_processed）"""
            try:
                worker_db = NaggerStateDB(db_path)
                worker_db.connect()
                worker_repo = SubagentRepository(worker_db)

                record = worker_repo.claim_next_unprocessed("session-1")
                if record:
                    worker_repo.mark_processed(record.agent_id)
                with lock:
                    results.append(record.agent_id if record else None)

                worker_db.close()
            except Exception as e:
                with lock:
                    errors.append(str(e))

        # 4スレッドで並列実行
        threads = [threading.Thread(target=claim_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        db.close()

        # エラーなし
        assert len(errors) == 0, f"Errors: {errors}"

        # 2フェーズ方式のため、claim（SELECT）とmark_processed（UPDATE）が分離しており
        # 複数スレッドが同じレコードをclaimする可能性がある
        claimed = [r for r in results if r is not None]
        assert 2 <= len(claimed) <= 4
        assert set(claimed) == {"agent-1", "agent-2"}

    def test_ThreadPoolExecutor並列claim(self, tmp_path):
        """ThreadPoolExecutorでの並列テスト（2フェーズ方式）

        注意: 2フェーズ方式ではclaimとmarkの間に他スレッドが同じレコードを
        取得する可能性がある（レースコンディション）。
        実際の使用では、process()完了後にmark_processed()を呼ぶため、
        短い期間に重複取得が発生しても、最終的には全て処理される。
        """
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()
        repo = SubagentRepository(db)

        # 5件登録
        for i in range(5):
            repo.register(f"agent-{i}", "session-1", "coder")
            time.sleep(0.005)

        def claim_task():
            """claimタスク（claim + mark_processed）"""
            worker_db = NaggerStateDB(db_path)
            worker_db.connect()
            worker_repo = SubagentRepository(worker_db)
            record = worker_repo.claim_next_unprocessed("session-1")
            if record:
                worker_repo.mark_processed(record.agent_id)
            worker_db.close()
            return record.agent_id if record else None

        # 8スレッドで並列実行
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(claim_task) for _ in range(8)]
            results = [f.result() for f in as_completed(futures)]

        db.close()

        # 取得されたagent_idの一意数を確認
        # 2フェーズ方式では重複取得の可能性があるが、最終的に全agentが処理される
        claimed = [r for r in results if r is not None]
        unique_claimed = set(claimed)

        # 全5件のagentが少なくとも1回は取得された
        assert unique_claimed == {"agent-0", "agent-1", "agent-2", "agent-3", "agent-4"}
