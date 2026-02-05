"""SubagentRepositoryのユニットテスト

issue_5955: テスト分離・TTL機能のテスト
- フォールバックマッチングのTTL検証
- テスト間の分離（tmp_path経由のDB使用）
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.subagent_repository import SubagentRepository
from shared.constants import TASK_SPAWN_TTL_MINUTES


class TestSubagentRepositoryTTL:
    """フォールバックマッチングのTTL機能テスト（issue_5955）"""

    def test_ttl_expired_entry_not_matched(self, db):
        """TTL切れエントリがフォールバックマッチング対象外になることを確認

        created_atを古い時刻（TTL超過）に設定したエントリはマッチしない
        """
        repo = SubagentRepository(db)
        session_id = "test-session-ttl-expired"
        agent_id = "agent-ttl-test"

        # subagentを登録
        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTL超過のtask_spawn（6分前 > 5分TTL）
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=TASK_SPAWN_TTL_MINUTES + 1)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "coder", "hash_expired", expired_time),
        )
        db.conn.commit()

        # フォールバックマッチング試行（transcript_pathなしでフォールバックを強制）
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role="coder", transcript_path=None
        )

        # TTL切れのためマッチしない
        assert result is None

    def test_ttl_valid_entry_matched(self, db):
        """TTL内のエントリがフォールバックマッチングでマッチすることを確認

        created_atが直近（TTL以内）のエントリはマッチする
        """
        repo = SubagentRepository(db)
        session_id = "test-session-ttl-valid"
        agent_id = "agent-ttl-valid"

        # subagentを登録
        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTL内のtask_spawn（1分前 < 5分TTL）
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "coder", "hash_valid", recent_time),
        )
        db.conn.commit()

        # フォールバックマッチング試行
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role="coder", transcript_path=None
        )

        # TTL内なのでマッチする
        assert result == "coder"

    def test_ttl_boundary_just_within(self, db):
        """TTL境界値テスト: ちょうどTTL以内のエントリはマッチする"""
        repo = SubagentRepository(db)
        session_id = "test-session-ttl-boundary-in"
        agent_id = "agent-ttl-boundary-in"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTLちょうど（5分前 - 余裕10秒）
        boundary_time = (datetime.now(timezone.utc) - timedelta(minutes=TASK_SPAWN_TTL_MINUTES - 0.17)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "tester", "hash_boundary_in", boundary_time),
        )
        db.conn.commit()

        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role="tester", transcript_path=None
        )

        # TTL内なのでマッチ
        assert result == "tester"

    def test_ttl_boundary_just_expired(self, db):
        """TTL境界値テスト: TTLをわずかに超えたエントリはマッチしない"""
        repo = SubagentRepository(db)
        session_id = "test-session-ttl-boundary-out"
        agent_id = "agent-ttl-boundary-out"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTLをわずかに超過（5分 + 30秒）
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=TASK_SPAWN_TTL_MINUTES + 0.5)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "reviewer", "hash_boundary_out", expired_time),
        )
        db.conn.commit()

        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role="reviewer", transcript_path=None
        )

        # TTL超過のためマッチしない
        assert result is None

    def test_ttl_applies_to_subagent_type_fallback(self, db):
        """TTLがsubagent_typeフォールバックマッチにも適用される"""
        repo = SubagentRepository(db)
        session_id = "test-session-ttl-type-fallback"
        agent_id = "agent-ttl-type-fallback"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTL超過のtask_spawn（subagent_typeマッチのみ）
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=TASK_SPAWN_TTL_MINUTES + 2)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "coder", "hash_type_expired", expired_time),
        )
        db.conn.commit()

        # roleを指定せずsubagent_typeでのフォールバック
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role=None, transcript_path=None
        )

        # TTL超過のためマッチしない
        assert result is None

    def test_ttl_mixed_valid_and_expired(self, db):
        """TTL内とTTL超過のエントリが混在する場合、TTL内のみマッチ"""
        repo = SubagentRepository(db)
        session_id = "test-session-ttl-mixed"
        agent_id = "agent-ttl-mixed"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTL超過エントリ（古い、transcript_index=1）
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "old-role", "hash_old", expired_time),
        )

        # TTL内エントリ（新しい、transcript_index=2）
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 2, "general-purpose", "new-role", "hash_new", recent_time),
        )
        db.conn.commit()

        # subagent_typeでフォールバックマッチ
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role=None, transcript_path=None
        )

        # TTL内のnew-roleのみマッチ
        assert result == "new-role"


class TestSubagentRepositoryExactMatch:
    """正確マッチング（tool_use_id経由）のテスト

    正確マッチングはTTLの影響を受けない（agent_progressで確実にマッチするため）
    """

    def test_exact_match_ignores_ttl(self, db, tmp_path):
        """正確マッチング（tool_use_id経由）はTTL制限を受けない"""
        repo = SubagentRepository(db)
        session_id = "test-session-exact"
        agent_id = "agent-exact"
        tool_use_id = "toolu_01EXACT"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTL超過のtask_spawnだがtool_use_idあり
        expired_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "architect", "hash_exact", tool_use_id, expired_time),
        )
        db.conn.commit()

        # agent_progressを含むtranscriptを作成
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {
                    "type": "agent_progress",
                    "agentId": agent_id,
                }
            }) + '\n')

        # 正確マッチング（transcript_path経由）
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role=None, transcript_path=str(transcript)
        )

        # TTL超過でも正確マッチングは成功する
        assert result == "architect"


class TestSubagentRepositoryBasic:
    """SubagentRepositoryの基本機能テスト（テスト分離確認含む）"""

    def test_register_and_get(self, db):
        """register→getの基本フロー"""
        repo = SubagentRepository(db)

        repo.register("agent-1", "session-1", "general-purpose", role="coder")

        record = repo.get("agent-1")
        assert record is not None
        assert record.agent_id == "agent-1"
        assert record.session_id == "session-1"
        assert record.agent_type == "general-purpose"
        assert record.role == "coder"

    def test_unregister(self, db):
        """unregisterでレコードが削除される"""
        repo = SubagentRepository(db)

        repo.register("agent-del", "session-del", "general-purpose")
        assert repo.get("agent-del") is not None

        repo.unregister("agent-del")
        assert repo.get("agent-del") is None

    def test_test_isolation(self, db, tmp_path):
        """テスト分離: dbフィクスチャはテスト専用DBを使用"""
        # dbフィクスチャのパスがtmp_path配下であることを確認
        db_path_str = str(db._db_path)
        tmp_path_str = str(tmp_path)

        assert tmp_path_str in db_path_str, f"DBパス {db_path_str} がtmp_path {tmp_path_str} 配下でない"

    def test_claim_next_unprocessed(self, db):
        """claim_next_unprocessedで未処理subagentを取得"""
        repo = SubagentRepository(db)
        session_id = "session-claim"

        repo.register("agent-claim", session_id, "general-purpose")

        record = repo.claim_next_unprocessed(session_id)
        assert record is not None
        assert record.agent_id == "agent-claim"
        assert record.startup_processed is False

    def test_mark_processed(self, db):
        """mark_processedでstartup_processed=1にマーク"""
        repo = SubagentRepository(db)
        session_id = "session-mark"

        repo.register("agent-mark", session_id, "general-purpose")
        repo.mark_processed("agent-mark")

        record = repo.get("agent-mark")
        assert record.startup_processed is True

        # 再度claimしても取得されない
        claimed = repo.claim_next_unprocessed(session_id)
        assert claimed is None

    def test_get_active(self, db):
        """get_activeでセッション内のアクティブsubagent一覧を取得"""
        repo = SubagentRepository(db)
        session_id = "session-active"

        repo.register("agent-a", session_id, "type-a")
        repo.register("agent-b", session_id, "type-b")
        repo.register("agent-c", "other-session", "type-c")

        records = repo.get_active(session_id)
        agent_ids = [r.agent_id for r in records]

        assert "agent-a" in agent_ids
        assert "agent-b" in agent_ids
        assert "agent-c" not in agent_ids  # 別セッションは含まれない


class TestRegisterTaskSpawns:
    """register_task_spawnsのテスト"""

    def test_register_task_spawns_with_role(self, db, tmp_path):
        """ROLEありのTask tool_useが登録される"""
        repo = SubagentRepository(db)
        session_id = "session-task-spawn"

        # Task tool_useを含むtranscriptを作成
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_01TEST",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "[ROLE:coder]\nFix the bug."
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        assert count == 1

        # DBに登録されたことを確認
        cursor = db.conn.execute(
            "SELECT role, tool_use_id FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "coder"
        assert row[1] == "toolu_01TEST"

    def test_register_task_spawns_without_role_skipped(self, db, tmp_path):
        """ROLEなしのTask tool_useはスキップされる"""
        repo = SubagentRepository(db)
        session_id = "session-task-no-role"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_02NOROLE",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "No ROLE prefix here."
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        # ROLEがないのでスキップ
        assert count == 0
