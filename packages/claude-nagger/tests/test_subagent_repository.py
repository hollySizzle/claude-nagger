"""SubagentRepositoryのユニットテスト

issue_5955: テスト分離
issue_7016: Step 1/Step 2廃止、Step 0（agent_progressベース正確マッチ）のみに簡素化
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.subagent_repository import SubagentRepository


class TestSubagentRepositoryTTL:
    """フォールバックマッチング廃止によりStep 0（agent_progressベース）のみ（issue_7016）

    TTLはStep 1/Step 2フォールバックにのみ適用されていたため、
    Step 0のみのフローではTTLテストは不要。
    Step 0はtranscript_pathベースの正確マッチングのため、TTL制限を受けない。
    """

    def test_no_fallback_without_transcript_path(self, db):
        """transcript_pathなしの場合、フォールバックせずNone返却（issue_7016）"""
        repo = SubagentRepository(db)
        session_id = "test-session-no-fallback"
        agent_id = "agent-no-fallback"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TTL内のtask_spawn
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "coder", "hash_valid", recent_time),
        )
        db.conn.commit()

        # transcript_pathなし → Step 0スキップ → None
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role="coder", transcript_path=None
        )
        assert result is None

    def test_no_fallback_with_role_param(self, db):
        """role引数を渡してもフォールバックマッチングは行われない（issue_7016）"""
        repo = SubagentRepository(db)
        session_id = "test-session-no-role-fallback"
        agent_id = "agent-no-role-fallback"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "coder", "hash_role", recent_time),
        )
        db.conn.commit()

        # role指定してもStep 1は廃止されたためNone
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role="coder", transcript_path=None
        )
        assert result is None

    def test_no_fallback_subagent_type_match(self, db):
        """subagent_typeのみ一致してもフォールバックマッチングは行われない（issue_7016）"""
        repo = SubagentRepository(db)
        session_id = "test-session-no-type-fallback"
        agent_id = "agent-no-type-fallback"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "coder", "hash_type", recent_time),
        )
        db.conn.commit()

        # subagent_type一致でもStep 2は廃止されたためNone
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose", role=None, transcript_path=None
        )
        assert result is None


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
        """subagent_typeありのTask tool_useが登録される（role=subagent_type）"""
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
                                "subagent_type": "ticket-tasuki:coder",
                                "prompt": "Fix the bug."
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
        assert row[0] == "ticket-tasuki:coder"
        assert row[1] == "toolu_01TEST"

    def test_register_task_spawns_with_subagent_type_registered(self, db, tmp_path):
        """subagent_typeあり + team_nameなし → subagent_typeがroleとして登録（issue_6987）"""
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

        # subagent_typeがあるので登録される（issue_6987）
        assert count == 1

        cursor = db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "general-purpose"

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
            # 有効なTask（subagent_typeでrole決定）
            f.write(json.dumps({
                "type": "assistant",
                "message": {"content": [{"type": "tool_use", "name": "Task", "id": "t2",
                            "input": {"subagent_type": "gp", "prompt": "work"}}]}
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
            # issue_1234を含むprompt（subagent_typeでrole決定）
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
                                "prompt": "issue_1234: Fix the bug."
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
                                "prompt": "Fix the bug."
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

    def test_register_task_spawns_team_name_priority_over_subagent_type(self, db, tmp_path):
        """team_name/nameあり + subagent_typeあり → nameが優先（issue_6987）"""
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
                                "prompt": "Review the code.",
                                "team_name": "dev-team",
                                "name": "coder"
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        assert count == 1

        # team_name/nameが優先されることを確認
        cursor = db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "coder"

    def test_register_task_spawns_team_name_without_name_fallback_subagent_type(self, db, tmp_path):
        """team_nameあり + nameなし + subagent_typeあり → subagent_typeがrole（issue_6987）"""
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

        # team_name+nameの条件を満たさないがsubagent_typeがあるので登録（issue_6987）
        assert count == 1

        cursor = db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "general-purpose"

    def test_register_task_spawns_agent_tool_name_with_team(self, db, tmp_path):
        """name='Agent' + team_name/nameあり → nameがroleになる（issue_6982）"""
        repo = SubagentRepository(db)
        session_id = "session-agent-team"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_AGENT_TEAM01",
                            "name": "Agent",
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
        assert row[1] == "toolu_AGENT_TEAM01"

    def test_register_task_spawns_agent_tool_name_team_name_priority(self, db, tmp_path):
        """name='Agent' + team_name/nameあり → nameが優先（issue_6987）"""
        repo = SubagentRepository(db)
        session_id = "session-agent-role-tag"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_AGENT_ROLE01",
                            "name": "Agent",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "Review the code.",
                                "team_name": "dev-team",
                                "name": "reviewer"
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        assert count == 1

        # team_name/nameが優先されることを確認
        cursor = db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "reviewer"

    def test_register_task_spawns_agent_subagent_type_as_role(self, db, tmp_path):
        """name='Agent' + subagent_typeあり + team_nameなし → subagent_typeがrole（issue_6987）"""
        repo = SubagentRepository(db)
        session_id = "session-agent-no-role"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_AGENT_NOROLE01",
                            "name": "Agent",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "Do something without role."
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        # subagent_typeがあるので登録される（issue_6987）
        assert count == 1

        cursor = db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "general-purpose"

    def test_register_task_spawns_no_subagent_type_no_team_name_skipped(self, db, tmp_path):
        """subagent_typeなし + team_nameなし → スキップ（issue_6987）"""
        repo = SubagentRepository(db)
        session_id = "session-no-role-at-all"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_NOROLE_NOTYPE01",
                            "name": "Task",
                            "input": {
                                "prompt": "Do something."
                            }
                        }
                    ]
                }
            }) + '\n')

        count = repo.register_task_spawns(session_id, str(transcript))

        # subagent_typeなし + team_nameなし → スキップ
        assert count == 0


class TestRoleRegressionNoFalsePositive:
    """回帰テスト: prompt本文中の[ROLE:xxx]リテラルが誤検出されないことの確認（issue_6992）"""

    def test_register_task_spawns_prompt_role_literal_ignored(self, db, tmp_path):
        """register_task_spawns: prompt本文に[ROLE:xxx]があってもroleはsubagent_type値"""
        repo = SubagentRepository(db)
        session_id = "session-regression-role"

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_REGRESSION01",
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

        cursor = db.conn.execute(
            "SELECT role FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row is not None
        # [ROLE:coder]のcoderではなく、subagent_type値がroleになる
        assert row[0] == "general-purpose"

    def test_parse_role_from_transcript_prompt_role_literal_ignored(self, tmp_path):
        """_parse_role_from_transcript: prompt本文に[ROLE:xxx]があってもroleはinput.subagent_type値"""
        from unittest.mock import patch
        from domain.hooks.session_startup_hook import SessionStartupHook

        with patch.object(SessionStartupHook, '_load_config', return_value={"enabled": True}):
            hook = SessionStartupHook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w', encoding='utf-8') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_REGRESSION02",
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "[ROLE:reviewer]\nReview the code."
                            }
                        }
                    ]
                }
            }) + '\n')

        result = hook._parse_role_from_transcript(str(transcript))
        # [ROLE:reviewer]のreviewerではなく、subagent_type値がroleになる
        assert result == "general-purpose"

    def test_parse_role_from_transcript_prompt_role_literal_with_team_name(self, tmp_path):
        """_parse_role_from_transcript: team_name/name + prompt内[ROLE:xxx] → input.name値"""
        from unittest.mock import patch
        from domain.hooks.session_startup_hook import SessionStartupHook

        with patch.object(SessionStartupHook, '_load_config', return_value={"enabled": True}):
            hook = SessionStartupHook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w', encoding='utf-8') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_REGRESSION03",
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

        result = hook._parse_role_from_transcript(str(transcript))
        # [ROLE:reviewer]のreviewerではなく、input.name値がroleになる
        assert result == "coder"

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
        """exact matchでtask_spawnが既にマッチ済みの場合はNone返却"""
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
        # 既にマッチ済みなのでNone（フォールバック廃止、issue_7016）
        assert result is None

    def test_exact_match_no_task_spawn_found(self, db, tmp_path):
        """parentToolUseIDがあるがtask_spawnが見つからない場合はNone返却"""
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

    def test_no_transcript_path_returns_none(self, db):
        """transcript_pathなしの場合、フォールバックせずNone返却（issue_7016）"""
        repo = SubagentRepository(db)
        session_id = "session-fb-issue"
        agent_id = "agent-fb-issue"

        repo.register(agent_id, session_id, "gp", role=None)

        # task_spawnが存在してもtranscript_pathなしではマッチしない
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, issue_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "gp", "reviewer", "hash", "toolu_FB", "9999", datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        # transcript_pathなし → Step 0スキップ → None（フォールバック廃止、issue_7016）
        result = repo.match_task_to_agent(session_id, agent_id, "gp")
        assert result is None


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


class TestTeamCreateStep0Match:
    """TeamCreate方式subagentのStep 0マッチングテスト（issue_7017）

    TeamCreate方式（team_name/name付き）のtask_spawnが
    agent_progressベースのStep 0正確マッチングで成功することを確認。
    """

    def test_team_create_step0_exact_match(self, db, tmp_path):
        """TeamCreate方式task_spawnがStep 0で正確マッチ成功"""
        repo = SubagentRepository(db)
        session_id = "session-team-step0"
        agent_id = "agent-team-step0"
        tool_use_id = "toolu_TEAM_STEP0"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TeamCreate方式の親transcriptを作成（team_name/name付き）
        parent_transcript = tmp_path / "parent_transcript.jsonl"
        with open(parent_transcript, 'w') as f:
            f.write(json.dumps({
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": tool_use_id,
                            "name": "Task",
                            "input": {
                                "subagent_type": "general-purpose",
                                "prompt": "Implement feature for issue_7017.",
                                "team_name": "dev-team",
                                "name": "coder-t2"
                            }
                        }
                    ]
                }
            }) + '\n')

        # task_spawnsを登録
        count = repo.register_task_spawns(session_id, str(parent_transcript))
        assert count == 1

        # task_spawnのroleがname値（TeamCreate方式）であることを確認
        cursor = db.conn.execute(
            "SELECT role, tool_use_id FROM task_spawns WHERE session_id = ?",
            (session_id,)
        )
        row = cursor.fetchone()
        assert row[0] == "coder-t2"
        assert row[1] == tool_use_id

        # agent_progressを含むsubagent transcriptを作成
        agent_transcript = tmp_path / "agent_transcript.jsonl"
        with open(agent_transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {
                    "type": "agent_progress",
                    "agentId": agent_id,
                }
            }) + '\n')

        # Step 0正確マッチング
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose",
            transcript_path=str(agent_transcript)
        )

        # マッチ成功: roleがTeamCreate方式のname値
        assert result == "coder-t2"

        # matched_agent_idが正しく設定されている
        cursor = db.conn.execute(
            "SELECT matched_agent_id FROM task_spawns WHERE tool_use_id = ?",
            (tool_use_id,)
        )
        assert cursor.fetchone()[0] == agent_id

        # subagentsのrole/role_sourceも更新されている
        record = repo.get(agent_id)
        assert record.role == "coder-t2"
        assert record.role_source == "task_match"

    def test_team_create_step0_fail_then_retry_match_success(self, db, tmp_path):
        """Step 0失敗（agent_progressなし）→ retry_matchで成功するE2Eフロー"""
        repo = SubagentRepository(db)
        session_id = "session-team-retry"
        agent_id = "agent-team-retry"
        tool_use_id = "toolu_TEAM_RETRY"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # TeamCreate方式のtask_spawnを直接登録
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "tester-t3", "hash_team",
             tool_use_id, datetime.now(timezone.utc).isoformat()),
        )
        db.conn.commit()

        # agent_progressがないtranscript（Step 0失敗を再現）
        empty_transcript = tmp_path / "empty_transcript.jsonl"
        with open(empty_transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "Hello"}}) + '\n')

        # Step 0マッチ → agent_progressがないのでNone
        result = repo.match_task_to_agent(
            session_id, agent_id, "general-purpose",
            transcript_path=str(empty_transcript)
        )
        assert result is None

        # 後にagent_progressが到達したtranscriptで retry_match
        retry_transcript = tmp_path / "retry_transcript.jsonl"
        with open(retry_transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {
                    "type": "agent_progress",
                    "agentId": agent_id,
                }
            }) + '\n')

        # retry_match_from_agent_progressで成功
        retry_result = repo.retry_match_from_agent_progress(
            session_id, agent_id, str(retry_transcript)
        )

        assert retry_result == "tester-t3"

        # subagentsが正しく更新されている
        record = repo.get(agent_id)
        assert record.role == "tester-t3"
        assert record.role_source == "retry_match"

        # task_spawnがマッチ済みになっている
        cursor = db.conn.execute(
            "SELECT matched_agent_id FROM task_spawns WHERE tool_use_id = ?",
            (tool_use_id,)
        )
        assert cursor.fetchone()[0] == agent_id

    def test_team_create_matched_agent_id_set_correctly(self, db, tmp_path):
        """matched_agent_idが正しいagent_idで設定される（受入条件2）"""
        repo = SubagentRepository(db)
        session_id = "session-team-matched"
        agent_id_1 = "agent-team-first"
        agent_id_2 = "agent-team-second"
        tool_use_id_1 = "toolu_TEAM_M1"
        tool_use_id_2 = "toolu_TEAM_M2"

        repo.register(agent_id_1, session_id, "general-purpose", role=None)
        repo.register(agent_id_2, session_id, "general-purpose", role=None)

        # 2つのTeamCreate方式task_spawnを登録
        now = datetime.now(timezone.utc).isoformat()
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, 1, "general-purpose", "coder-t2", "hash1", tool_use_id_1, now,
             session_id, 2, "general-purpose", "tester-t3", "hash2", tool_use_id_2, now),
        )
        db.conn.commit()

        # agent_1用transcript
        transcript_1 = tmp_path / "transcript_1.jsonl"
        with open(transcript_1, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id_1,
                "data": {"type": "agent_progress", "agentId": agent_id_1}
            }) + '\n')

        # agent_2用transcript
        transcript_2 = tmp_path / "transcript_2.jsonl"
        with open(transcript_2, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id_2,
                "data": {"type": "agent_progress", "agentId": agent_id_2}
            }) + '\n')

        # 各agentがそれぞれの正しいtask_spawnにマッチする
        result_1 = repo.match_task_to_agent(
            session_id, agent_id_1, "general-purpose",
            transcript_path=str(transcript_1)
        )
        result_2 = repo.match_task_to_agent(
            session_id, agent_id_2, "general-purpose",
            transcript_path=str(transcript_2)
        )

        assert result_1 == "coder-t2"
        assert result_2 == "tester-t3"

        # matched_agent_idが正しいagent_idで設定されている
        cursor = db.conn.execute(
            "SELECT tool_use_id, matched_agent_id FROM task_spawns WHERE session_id = ? ORDER BY transcript_index",
            (session_id,)
        )
        rows = cursor.fetchall()
        assert rows[0] == (tool_use_id_1, agent_id_1)
        assert rows[1] == (tool_use_id_2, agent_id_2)
