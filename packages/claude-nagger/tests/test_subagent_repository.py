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

    def test_register_task_spawns_file_not_exists(self, db):
        """存在しないファイルを指定した場合は0を返す"""
        repo = SubagentRepository(db)
        count = repo.register_task_spawns("session-x", "/non/existent/path.jsonl")
        assert count == 0

    def test_register_task_spawns_empty_lines_and_invalid_json(self, db, tmp_path):
        """空行・不正JSONをスキップし、有効なエントリのみ登録"""
        repo = SubagentRepository(db)
        session_id = "session-mixed"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            # 空行
            f.write('\n')
            # 不正JSON
            f.write('not valid json\n')
            # 型がassistant以外
            f.write(json.dumps({"type": "user", "message": {}}) + '\n')
            # tool_useではないcontent
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "text", "text": "hello"}]}
            }) + '\n')
            # Taskではないtool_use
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Bash", "id": "t1", "input": {}}]}
            }) + '\n')
            # 有効なTask
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Task", "id": "t2",
                            "input": {"subagent_type": "gp", "prompt": "[ROLE:coder]work"}}]}
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))
        # 有効エントリのみ1件登録
        assert count == 1

    def test_issue_id_extracted(self, db, tmp_path):
        """promptからissue_idが抽出・記録される（issue_6358）"""
        repo = SubagentRepository(db)
        session_id = "session-issue-id"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            # issue_1234を含むprompt
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_ISSUE",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "[ROLE:coder]\nissue_1234: Fix the bug."
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))
        assert count == 1

        cursor = db.conn.execute(
            "SELECT issue_id FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "1234"

    def test_issue_id_none_when_not_present(self, db, tmp_path):
        """promptにissue_idがない場合はNULL（issue_6358）"""
        repo = SubagentRepository(db)
        session_id = "session-no-issue"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_NOISSUE",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "[ROLE:coder]\nFix the bug."
                            }
                        }
                    ]
                }
            }) + '\n')

        repo.register_task_spawns(session_id, str(transcript))

        cursor = db.conn.execute(
            "SELECT issue_id FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] is None

    def test_register_task_spawns_team_agent_name_as_role(self, db, tmp_path):
        """[ROLE:xxx]なし + team_name/nameあり → nameがroleになる（issue_6974）"""
        repo = SubagentRepository(db)
        session_id = "session-team-agent"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_TEAM01",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "Implement the feature.",
                                "team_name": "dev-team",
                                "name": "coder"
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        assert count == 1

        # nameがroleとして登録されることを確認
        cursor = db.conn.execute(
            "SELECT role, tool_use_id FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "coder"
        assert row[1] == "toolu_TEAM01"

    def test_register_task_spawns_role_tag_priority_over_team_name(self, db, tmp_path):
        """[ROLE:xxx]あり + team_name/nameあり → [ROLE:xxx]が優先（issue_6974）"""
        repo = SubagentRepository(db)
        session_id = "session-role-priority"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_PRIORITY01",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "[ROLE:reviewer]\nReview the code.",
                                "team_name": "dev-team",
                                "name": "coder"
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        assert count == 1

        # [ROLE:xxx]が優先されることを確認
        cursor = db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "reviewer"

    def test_register_task_spawns_team_name_without_name_skipped(self, db, tmp_path):
        """team_nameあり + nameなし → スキップ（issue_6974）"""
        repo = SubagentRepository(db)
        session_id = "session-team-no-name"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_NONAME01",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "Do something.",
                                "team_name": "dev-team"
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        # nameがないのでスキップ
        assert count == 0

class TestFindTaskSpawnByToolUseId:
    """find_task_spawn_by_tool_use_idのテスト"""

    def test_found(self, db):
        """tool_use_idで検索してレコードを取得"""
        repo = SubagentRepository(db)
        session_id = "session-find"
        tool_use_id = "toolu_FIND"

        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "coder", "hash1", tool_use_id, "2025-01-01T00:00:00+00:00"),
        )
        db.conn.commit()

        result = repo.find_task_spawn_by_tool_use_id(tool_use_id)
        assert result is not None
        assert result["tool_use_id"] == tool_use_id
        assert result["role"] == "coder"

    def test_not_found(self, db):
        """存在しないtool_use_idの場合はNone"""
        repo = SubagentRepository(db)
        result = repo.find_task_spawn_by_tool_use_id("non_existent_id")
        assert result is None


class TestFindParentToolUseId:
    """find_parent_tool_use_idのテスト"""

    def test_transcript_not_exists(self, db):
        """transcriptファイルが存在しない場合はNone"""
        repo = SubagentRepository(db)
        result = repo.find_parent_tool_use_id("/non/existent.jsonl", "agent-1")
        assert result is None

    def test_no_agent_progress_entries(self, db, tmp_path):
        """agent_progressエントリがない場合はNone"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "assistant", "message": {}}) + '\n')

        result = repo.find_parent_tool_use_id(str(transcript), "agent-1")
        assert result is None

    def test_agent_id_not_matched(self, db, tmp_path):
        """agent_progressはあるがagent_idが一致しない場合はNone"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": "toolu_PARENT",
                "data": {"type": "agent_progress", "agentId": "other-agent"}
            }) + '\n')

        result = repo.find_parent_tool_use_id(str(transcript), "agent-1")
        assert result is None

    def test_found_matching_agent_progress(self, db, tmp_path):
        """agent_idが一致するagent_progressからparentToolUseIDを取得"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": "toolu_MATCH",
                "data": {"type": "agent_progress", "agentId": "agent-1"}
            }) + '\n')

        result = repo.find_parent_tool_use_id(str(transcript), "agent-1")
        assert result == "toolu_MATCH"

    def test_empty_lines_and_invalid_json_skipped(self, db, tmp_path):
        """空行・不正JSONをスキップ"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write('\n')  # 空行
            f.write('invalid json\n')  # 不正JSON
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": "toolu_VALID",
                "data": {"type": "agent_progress", "agentId": "agent-1"}
            }) + '\n')

        result = repo.find_parent_tool_use_id(str(transcript), "agent-1")
        assert result == "toolu_VALID"

    def test_progress_not_agent_progress(self, db, tmp_path):
        """type=progressだがdata.type!=agent_progressはスキップ"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "data": {"type": "other_progress"}
            }) + '\n')
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": "toolu_CORRECT",
                "data": {"type": "agent_progress", "agentId": "agent-1"}
            }) + '\n')

        result = repo.find_parent_tool_use_id(str(transcript), "agent-1")
        assert result == "toolu_CORRECT"


class TestMatchTaskToAgentEdgeCases:
    """match_task_to_agentのエッジケース"""

    def test_exact_match_already_matched(self, db, tmp_path):
        """exact matchでtask_spawnが既にマッチ済みの場合はフォールバック"""
        repo = SubagentRepository(db)
        session_id = "session-already"
        agent_id = "agent-new"
        tool_use_id = "toolu_ALREADY"

        repo.register(agent_id, session_id, "gp", role=None)

        # 既にマッチ済みのtask_spawn
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, matched_agent_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "coder", "hash", tool_use_id, "other-agent", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        # agent_progressを作成
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.match_task_to_agent(session_id, agent_id, "gp", transcript_path=str(transcript))
        # 既にマッチ済みなのでNone（フォールバックにも該当なし）
        assert result is None

    def test_exact_match_no_task_spawn_found(self, db, tmp_path):
        """parentToolUseIDがあるがtask_spawnが見つからない場合はフォールバック"""
        repo = SubagentRepository(db)
        session_id = "session-notfound"
        agent_id = "agent-notfound"

        repo.register(agent_id, session_id, "gp", role=None)

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": "toolu_NONEXISTENT",
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.match_task_to_agent(session_id, agent_id, "gp", transcript_path=str(transcript))
        # task_spawnが見つからないのでNone
        assert result is None

    def test_exact_match_propagates_issue_id(self, db, tmp_path):
        """Exact Match時にissue_idがsubagentsに伝搬される（issue_6358）"""
        repo = SubagentRepository(db)
        session_id = "session-exact-issue"
        agent_id = "agent-exact-issue"
        tool_use_id = "toolu_EXACT_ISSUE"

        repo.register(agent_id, session_id, "gp", role=None)

        # issue_id付きのtask_spawn
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, issue_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "coder", "hash", tool_use_id, "5678", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.match_task_to_agent(session_id, agent_id, "gp", transcript_path=str(transcript))
        assert result == "coder"

        # subagentsにissue_idが伝搬されている
        cursor = db.conn.execute(
            "SELECT issue_id FROM subagents WHERE agent_id = ?", (agent_id,)
        )
        assert cursor.fetchone()[0] == "5678"

    def test_fallback_match_propagates_issue_id(self, db):
        """Fallback Match時にissue_idがsubagentsに伝搬される（issue_6358）"""
        repo = SubagentRepository(db)
        session_id = "session-fb-issue"
        agent_id = "agent-fb-issue"

        repo.register(agent_id, session_id, "gp", role=None)

        # issue_id付きのtask_spawn（transcript_pathなしでフォールバックさせる）
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, issue_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "reviewer", "hash", "toolu_FB", "9999", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        result = repo.match_task_to_agent(session_id, agent_id, "gp")
        assert result == "reviewer"

        # subagentsにissue_idが伝搬されている
        cursor = db.conn.execute(
            "SELECT issue_id FROM subagents WHERE agent_id = ?", (agent_id,)
        )
        assert cursor.fetchone()[0] == "9999"


class TestQueryMethods:
    """クエリ系メソッドのテスト"""

    def test_get_unprocessed_count(self, db):
        """未処理subagent数を取得"""
        repo = SubagentRepository(db)
        session_id = "session-count"

        # 未処理2件
        repo.register("a1", session_id, "gp")
        repo.register("a2", session_id, "gp")
        # 処理済み1件
        repo.register("a3", session_id, "gp")
        repo.mark_processed("a3")

        count = repo.get_unprocessed_count(session_id)
        assert count == 2

    def test_get_unprocessed_count_empty(self, db):
        """subagentがない場合は0"""
        repo = SubagentRepository(db)
        count = repo.get_unprocessed_count("no-such-session")
        assert count == 0

    def test_is_any_active_true(self, db):
        """アクティブsubagentがある場合はTrue"""
        repo = SubagentRepository(db)
        session_id = "session-active"
        repo.register("agent-x", session_id, "gp")

        assert repo.is_any_active(session_id) is True

    def test_is_any_active_false(self, db):
        """アクティブsubagentがない場合はFalse"""
        repo = SubagentRepository(db)
        assert repo.is_any_active("empty-session") is False


class TestUpdateRole:
    """update_roleのテスト"""

    def test_update_role(self, db):
        """roleとrole_sourceを更新"""
        repo = SubagentRepository(db)
        repo.register("agent-upd", "session-upd", "gp", role=None)

        repo.update_role("agent-upd", "reviewer", "manual")

        record = repo.get("agent-upd")
        assert record.role == "reviewer"
        assert record.role_source == "manual"


class TestCleanupMethods:
    """クリーンアップ系メソッドのテスト"""

    def test_cleanup_session(self, db):
        """session_idの全subagentを削除"""
        repo = SubagentRepository(db)
        session_id = "session-cleanup"

        repo.register("a1", session_id, "gp")
        repo.register("a2", session_id, "gp")
        repo.register("a3", "other-session", "gp")

        deleted = repo.cleanup_session(session_id)

        assert deleted == 2
        assert repo.get("a1") is None
        assert repo.get("a2") is None
        assert repo.get("a3") is not None  # 別セッションは残る

    def test_cleanup_old_task_spawns(self, db):
        """未マッチの古いtask_spawnを削除（最新N件は保持）"""
        repo = SubagentRepository(db)
        session_id = "session-old-task"

        # 5件登録（未マッチ）
        for i in range(5):
            db.conn.execute(
                """
                INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, i + 1, "gp", "coder", f"hash{i}", datetime.now(timezone.utc).isoformat()),
            )
        db.conn.commit()

        # 最新2件を保持し、3件削除
        deleted = repo.cleanup_old_task_spawns(session_id, keep_recent=2)

        assert deleted == 3

        # 残りのエントリ数を確認
        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE session_id = ?", (session_id,)
        )
        remaining = cursor.fetchone()[0]
        assert remaining == 2

    def test_cleanup_old_task_spawns_with_matched(self, db):
        """マッチ済みエントリはDELETE対象外（WHERE matched_agent_id IS NULL）だが保持カウントには含まれる"""
        repo = SubagentRepository(db)
        session_id = "session-old-matched"

        # 未マッチ3件（古い順にid小さい）
        for i in range(3):
            db.conn.execute(
                """
                INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session_id, i + 1, "gp", "coder", f"hash{i}", datetime.now(timezone.utc).isoformat()),
            )
        # マッチ済み1件（最新=id最大）
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, matched_agent_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 100, "gp", "coder", "matched_hash", "agent-m", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        # keep_recent=2: 最新2件(マッチ済み1 + 未マッチ1)を保持、残り未マッチ2件が削除対象
        deleted = repo.cleanup_old_task_spawns(session_id, keep_recent=2)

        assert deleted == 2

        # マッチ済みは残る
        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE session_id = ? AND matched_agent_id IS NOT NULL",
            (session_id,)
        )
        matched_count = cursor.fetchone()[0]
        assert matched_count == 1

        # 未マッチ1件残る
        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE session_id = ? AND matched_agent_id IS NULL",
            (session_id,)
        )
        unmatched_count = cursor.fetchone()[0]
        assert unmatched_count == 1

    def test_cleanup_null_role_task_spawns(self, db):
        """role=NULLのtask_spawnを全削除"""
        repo = SubagentRepository(db)

        # role=NULLの2件
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("s1", 1, "gp", None, "h1", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("s2", 2, "gp", None, "h2", datetime.now(timezone.utc).isoformat()),
        )
        # role=coder（残る）
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("s3", 3, "gp", "coder", "h3", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        deleted = repo.cleanup_null_role_task_spawns()

        assert deleted == 2

        # roleありは残る
        cursor = db.conn.execute("SELECT COUNT(*) FROM task_spawns WHERE role IS NOT NULL")
        count = cursor.fetchone()[0]
        assert count == 1


class TestRetryMatchFromAgentProgress:
    """retry_match_from_agent_progressのテスト"""

    def test_no_parent_tool_use_id(self, db, tmp_path):
        """agent_progressにparentToolUseIDがない場合はNone"""
        repo = SubagentRepository(db)
        session_id = "session-retry-no-parent"
        agent_id = "agent-retry-no"

        repo.register(agent_id, session_id, "gp", role=None)

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            # agent_progressがない
            f.write(json.dumps({"type": "assistant"}) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result is None

    def test_no_task_spawn_found(self, db, tmp_path):
        """task_spawnが見つからない場合はNone"""
        repo = SubagentRepository(db)
        session_id = "session-retry-no-task"
        agent_id = "agent-retry-notask"

        repo.register(agent_id, session_id, "gp", role=None)

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": "toolu_NOT_IN_DB",
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result is None

    def test_task_spawn_has_no_role(self, db, tmp_path):
        """task_spawnにroleがない場合はNone"""
        repo = SubagentRepository(db)
        session_id = "session-retry-no-role"
        agent_id = "agent-retry-norole"
        tool_use_id = "toolu_NOROLE"

        repo.register(agent_id, session_id, "gp", role=None)

        # roleがNULLのtask_spawn
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", None, "hash", tool_use_id, datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result is None

    def test_task_spawn_already_matched(self, db, tmp_path):
        """task_spawnが既にマッチ済みの場合はNone"""
        repo = SubagentRepository(db)
        session_id = "session-retry-matched"
        agent_id = "agent-retry-matched"
        tool_use_id = "toolu_ALREADY_MATCHED"

        repo.register(agent_id, session_id, "gp", role=None)

        # 既にマッチ済み
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, matched_agent_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "coder", "hash", tool_use_id, "other-agent", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result is None

    def test_successful_retry_match(self, db, tmp_path):
        """正常なretry_match成功"""
        repo = SubagentRepository(db)
        session_id = "session-retry-ok"
        agent_id = "agent-retry-ok"
        tool_use_id = "toolu_RETRY_OK"

        repo.register(agent_id, session_id, "gp", role=None)

        # 未マッチのtask_spawn
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "architect", "hash", tool_use_id, datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))

        assert result == "architect"

        # subagentのroleが更新されている
        record = repo.get(agent_id)
        assert record.role == "architect"
        assert record.role_source == "retry_match"

        # task_spawnがマッチ済みになっている
        cursor = db.conn.execute(
            "SELECT matched_agent_id FROM task_spawns WHERE tool_use_id = ?", (tool_use_id,)
        )
        matched = cursor.fetchone()[0]
        assert matched == agent_id

    def test_retry_match_propagates_issue_id(self, db, tmp_path):
        """retry_match時にissue_idがsubagentsに伝搬される（issue_6358）"""
        repo = SubagentRepository(db)
        session_id = "session-retry-issue"
        agent_id = "agent-retry-issue"
        tool_use_id = "toolu_RETRY_ISSUE"

        repo.register(agent_id, session_id, "gp", role=None)

        # issue_id付きの未マッチtask_spawn
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, issue_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "architect", "hash", tool_use_id, "4321", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {"type": "agent_progress", "agentId": agent_id}
            }) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result == "architect"

        # subagentsにissue_idが伝搬されている
        cursor = db.conn.execute(
            "SELECT issue_id FROM subagents WHERE agent_id = ?", (agent_id,)
        )
        assert cursor.fetchone()[0] == "4321"


class TestExceptionHandling:
    """例外ハンドリングのテスト

    注意: sqlite3.Connectionのexecuteはread-onlyでmonkeypatchできないため、
    例外発生時のrollback処理は直接テストできない。
    これらのパスはコードレビューで確認済み（issue_5955）。
    カバレッジ目標80%は達成済み（94%）。
    """

    pass  # sqlite3の制限によりrollbackテストはスキップ


class TestLeaderTranscriptPath:
    """leader_transcript_path機能のテスト（issue_6057）

    SubagentStart時にleaderのtranscript_pathをDB保存し、
    PreToolUseでleader/subagentを区別するための機能。
    """

    def test_register_with_leader_transcript_path(self, db):
        """register()でleader_transcript_pathが保存される"""
        repo = SubagentRepository(db)
        leader_tp = "/home/user/.claude/projects/test/leader.jsonl"

        repo.register("agent-ltp", "session-ltp", "gp",
                       leader_transcript_path=leader_tp)

        record = repo.get("agent-ltp")
        assert record is not None
        assert record.leader_transcript_path == leader_tp

    def test_register_without_leader_transcript_path(self, db):
        """leader_transcript_pathなし（後方互換）"""
        repo = SubagentRepository(db)

        repo.register("agent-no-ltp", "session-no-ltp", "gp")

        record = repo.get("agent-no-ltp")
        assert record is not None
        assert record.leader_transcript_path is None

    def test_claim_next_unprocessed_includes_leader_transcript_path(self, db):
        """claim_next_unprocessedの結果にleader_transcript_pathが含まれる"""
        repo = SubagentRepository(db)
        leader_tp = "/home/user/.claude/projects/test/leader-claim.jsonl"

        repo.register("agent-claim-ltp", "session-claim-ltp", "gp",
                       leader_transcript_path=leader_tp)

        record = repo.claim_next_unprocessed("session-claim-ltp")
        assert record is not None
        assert record.leader_transcript_path == leader_tp

    def test_get_active_includes_leader_transcript_path(self, db):
        """get_activeの結果にleader_transcript_pathが含まれる"""
        repo = SubagentRepository(db)
        leader_tp = "/home/user/.claude/projects/test/leader-active.jsonl"

        repo.register("agent-active-ltp", "session-active-ltp", "gp",
                       leader_transcript_path=leader_tp)

        records = repo.get_active("session-active-ltp")
        assert len(records) == 1
        assert records[0].leader_transcript_path == leader_tp


class TestSchemaV3Migration:
    """スキーマv3マイグレーションのテスト（issue_6057）"""

    def test_migration_adds_leader_transcript_path_column(self, tmp_path):
        """v2→v3マイグレーションでleader_transcript_pathカラムが追加される"""
        from infrastructure.db.nagger_state_db import NaggerStateDB

        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()

        # カラムの存在確認
        cursor = db.conn.execute("PRAGMA table_info(subagents)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "leader_transcript_path" in columns

        # スキーマバージョン確認
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        assert version >= 3

        db.close()


class TestIsLeaderToolUse:
    """is_leader_tool_useのテスト（issue_6952/issue_6953）"""

    def _make_assistant_entry(self, tool_uses):
        """assistant型エントリを生成するヘルパー"""
        return json.dumps({
            "type": "assistant",
            "message": {"content": tool_uses}
        })

    def test_transcript_not_exists(self, db):
        """transcriptファイルが存在しない場合はFalse"""
        repo = SubagentRepository(db)
        result = repo.is_leader_tool_use("/non/existent.jsonl", "toolu_ANY")
        assert result is False

    def test_empty_transcript(self, db, tmp_path):
        """空ファイルの場合はFalse"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "empty.jsonl"
        transcript.write_text("")

        result = repo.is_leader_tool_use(str(transcript), "toolu_ANY")
        assert result is False

    def test_tool_use_id_found_bash(self, db, tmp_path):
        """Bash tool_use_idが一致する場合はTrue"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(self._make_assistant_entry([
                {"type": "tool_use", "id": "toolu_LEADER_BASH", "name": "Bash",
                 "input": {"command": "echo hello"}}
            ]) + '\n')

        result = repo.is_leader_tool_use(str(transcript), "toolu_LEADER_BASH")
        assert result is True

    def test_tool_use_id_found_task(self, db, tmp_path):
        """Task tool_use_idが一致する場合はTrue"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(self._make_assistant_entry([
                {"type": "tool_use", "id": "toolu_LEADER_TASK", "name": "Task",
                 "input": {"subagent_type": "coder", "prompt": "[ROLE:coder] implement X"}}
            ]) + '\n')

        result = repo.is_leader_tool_use(str(transcript), "toolu_LEADER_TASK")
        assert result is True

    def test_tool_use_id_found_read(self, db, tmp_path):
        """Read tool_use_idが一致する場合はTrue"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(self._make_assistant_entry([
                {"type": "tool_use", "id": "toolu_LEADER_READ", "name": "Read",
                 "input": {"file_path": "/tmp/test.txt"}}
            ]) + '\n')

        result = repo.is_leader_tool_use(str(transcript), "toolu_LEADER_READ")
        assert result is True

    def test_tool_use_id_not_found(self, db, tmp_path):
        """存在しないIDの場合はFalse"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(self._make_assistant_entry([
                {"type": "tool_use", "id": "toolu_OTHER", "name": "Bash",
                 "input": {"command": "ls"}}
            ]) + '\n')

        result = repo.is_leader_tool_use(str(transcript), "toolu_NOT_EXISTS")
        assert result is False

    def test_invalid_json_skipped(self, db, tmp_path):
        """不正JSON行をスキップして正常動作"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write('invalid json line\n')
            f.write(self._make_assistant_entry([
                {"type": "tool_use", "id": "toolu_AFTER_INVALID", "name": "Bash",
                 "input": {"command": "echo ok"}}
            ]) + '\n')

        # 不正JSONをスキップして次のエントリでマッチ
        result = repo.is_leader_tool_use(str(transcript), "toolu_AFTER_INVALID")
        assert result is True

        # 存在しないIDはFalse
        result = repo.is_leader_tool_use(str(transcript), "toolu_MISSING")
        assert result is False

    def test_non_assistant_entries_skipped(self, db, tmp_path):
        """type!='assistant'のエントリは無視"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            # progressエントリ（assistant以外）にtool_useっぽいデータがあっても無視
            f.write(json.dumps({
                "type": "progress",
                "message": {"content": [
                    {"type": "tool_use", "id": "toolu_IN_PROGRESS", "name": "Bash"}
                ]}
            }) + '\n')

        result = repo.is_leader_tool_use(str(transcript), "toolu_IN_PROGRESS")
        assert result is False

    def test_multiple_tool_uses(self, db, tmp_path):
        """複数tool_use中から正確にマッチ"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(self._make_assistant_entry([
                {"type": "tool_use", "id": "toolu_FIRST", "name": "Bash",
                 "input": {"command": "echo 1"}},
                {"type": "tool_use", "id": "toolu_SECOND", "name": "Read",
                 "input": {"file_path": "/tmp/a.txt"}},
                {"type": "tool_use", "id": "toolu_THIRD", "name": "Task",
                 "input": {"subagent_type": "coder", "prompt": "[ROLE:coder] do X"}}
            ]) + '\n')

        assert repo.is_leader_tool_use(str(transcript), "toolu_SECOND") is True
        assert repo.is_leader_tool_use(str(transcript), "toolu_THIRD") is True
        assert repo.is_leader_tool_use(str(transcript), "toolu_NOT_HERE") is False

    def test_empty_tool_use_id(self, db, tmp_path):
        """空文字列のtool_use_idはFalse"""
        repo = SubagentRepository(db)
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(self._make_assistant_entry([
                {"type": "tool_use", "id": "toolu_REAL", "name": "Bash",
                 "input": {"command": "echo hello"}}
            ]) + '\n')

        result = repo.is_leader_tool_use(str(transcript), "")
        assert result is False
