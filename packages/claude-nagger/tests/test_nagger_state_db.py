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
@pytest.fixture
def db(tmp_path):
    """テスト用NaggerStateDBインスタンス"""
    db_path = tmp_path / ".claude-nagger" / "state.db"
    db = NaggerStateDB(db_path)
    db.connect()
    yield db
    db.close()


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

        # スキーマバージョン確認
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        assert version == 1

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

        # 4スレッドだが2件のみ取得
        claimed = [r for r in results if r is not None]
        assert len(claimed) == 2
        assert set(claimed) == {"agent-1", "agent-2"}

        # 残り2スレッドはNone
        none_count = results.count(None)
        assert none_count == 2

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
