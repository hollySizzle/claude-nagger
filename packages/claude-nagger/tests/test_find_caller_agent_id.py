"""find_caller_agent_id() / _get_caller_roles() tool_use_idベース改修テスト（issue_7105）"""

import json
import uuid
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.services.leader_detection import find_caller_agent_id
from src.domain.hooks.implementation_design_hook import ImplementationDesignHook
from src.domain.models.records import SubagentRecord


# === 1. find_caller_agent_id() 単体テスト ===

class TestFindCallerAgentId:
    """find_caller_agent_id()のユニットテスト"""

    def _make_agent_jsonl_entry(self, tool_use_id: str, tool_name: str = "Read") -> str:
        """テスト用JSONLエントリを生成"""
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": tool_use_id, "name": tool_name}
                ]
            }
        }
        return json.dumps(entry)

    def test_正常系_subagent_transcriptからtool_use_idマッチ(self, tmp_path):
        """subagentsディレクトリ内のagent-{UUID}.jsonlからtool_use_idマッチ → UUID返却"""
        # leader用transcript（空ファイル）
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        # subagentsディレクトリにagent-{UUID}.jsonlを作成
        subagents_dir = tmp_path / "subagents"
        subagents_dir.mkdir()
        agent_uuid = str(uuid.uuid4())
        agent_file = subagents_dir / f"agent-{agent_uuid}.jsonl"
        agent_file.write_text(self._make_agent_jsonl_entry("target_id") + "\n")

        result = find_caller_agent_id(str(transcript), "target_id")
        assert result == agent_uuid

    def test_複数subagent_正しいagentにマッチ(self, tmp_path):
        """2つのagent-*.jsonlから正しいagentのUUIDを返却"""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        subagents_dir = tmp_path / "subagents"
        subagents_dir.mkdir()

        # agent-aaa: target_idを含む
        agent_a = subagents_dir / "agent-aaa.jsonl"
        agent_a.write_text(self._make_agent_jsonl_entry("target_id") + "\n")

        # agent-bbb: 別のIDを含む
        agent_b = subagents_dir / "agent-bbb.jsonl"
        agent_b.write_text(self._make_agent_jsonl_entry("other_id") + "\n")

        result = find_caller_agent_id(str(transcript), "target_id")
        assert result == "aaa"

    def test_未ヒット_tool_use_id未存在(self, tmp_path):
        """subagent transcriptにtool_use_idが存在しない → None"""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        subagents_dir = tmp_path / "subagents"
        subagents_dir.mkdir()
        agent_file = subagents_dir / "agent-xxx.jsonl"
        agent_file.write_text(self._make_agent_jsonl_entry("different_id") + "\n")

        result = find_caller_agent_id(str(transcript), "target_id")
        assert result is None

    def test_subagentsディレクトリ不在(self, tmp_path):
        """subagentsディレクトリが存在しない → None"""
        # 存在しないパスを指定
        transcript = tmp_path / "nonexistent" / "transcript.jsonl"
        result = find_caller_agent_id(str(transcript), "target_id")
        assert result is None

    def test_壊れたJSONスキップ(self, tmp_path):
        """不正JSON行をスキップし、正常行からマッチ"""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        subagents_dir = tmp_path / "subagents"
        subagents_dir.mkdir()
        agent_file = subagents_dir / "agent-recovered.jsonl"

        # 壊れたJSON行 + 正常なマッチ行
        lines = [
            "{invalid json",
            self._make_agent_jsonl_entry("target_id"),
        ]
        agent_file.write_text("\n".join(lines) + "\n")

        result = find_caller_agent_id(str(transcript), "target_id")
        assert result == "recovered"


# === 2. _get_caller_roles() 統合テスト ===

class TestGetCallerRolesToolUseId:
    """_get_caller_roles() tool_use_idベース統合テスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_tool_use_idベースで単一role返却(self, hook):
        """find_caller_agent_idでagent特定 → SubagentRepository.getでrole返却"""
        input_data = {'session_id': 'test-session'}
        mock_record = SubagentRecord(
            agent_id='agent-123',
            session_id='test-session',
            agent_type='coder',
            role='coder',
            role_source='task_match',
            created_at='2026-01-01T00:00:00Z',
            startup_processed=True,
            startup_processed_at='2026-01-01T00:00:01Z',
            task_match_index=1,
        )

        with patch('domain.services.leader_detection.find_caller_agent_id', return_value='agent-123'):
            with patch('infrastructure.db.SubagentRepository') as MockRepo:
                mock_repo_instance = MagicMock()
                mock_repo_instance.get.return_value = mock_record
                MockRepo.return_value = mock_repo_instance
                with patch('infrastructure.db.NaggerStateDB') as MockDB:
                    mock_db_instance = MagicMock()
                    MockDB.return_value = mock_db_instance
                    MockDB.resolve_db_path.return_value = '/tmp/test.db'

                    result = hook._get_caller_roles(input_data, 'tool_use_id_1', '/tmp/transcript')

        assert result == {'coder'}

    def test_tool_use_idベース失敗_空set(self, hook):
        """find_caller_agent_idがNone → 空set"""
        input_data = {'session_id': 'test-session'}

        with patch('domain.services.leader_detection.find_caller_agent_id', return_value=None):
            result = hook._get_caller_roles(input_data, 'tool_use_id_1', '/tmp/transcript')

        assert result == set()

    def test_後方互換_tool_use_id未指定(self, hook):
        """tool_use_id/transcript_pathなし → session_idベース既存ロジック"""
        input_data = {'session_id': 'test-session'}
        mock_record = SubagentRecord(
            agent_id='agent-456',
            session_id='test-session',
            agent_type='tester',
            role='tester',
            role_source='task_match',
            created_at='2026-01-01T00:00:00Z',
            startup_processed=True,
            startup_processed_at='2026-01-01T00:00:01Z',
            task_match_index=1,
        )

        with patch('infrastructure.db.SubagentRepository') as MockRepo:
            mock_repo_instance = MagicMock()
            mock_repo_instance.get_active.return_value = [mock_record]
            MockRepo.return_value = mock_repo_instance
            with patch('infrastructure.db.NaggerStateDB') as MockDB:
                mock_db_instance = MagicMock()
                MockDB.return_value = mock_db_instance
                MockDB.resolve_db_path.return_value = '/tmp/test.db'

                # tool_use_id/transcript_pathなし → 後方互換パス
                result = hook._get_caller_roles(input_data)

        assert result == {'tester'}


# === 3. 回帰テスト ===

class TestScopeLeaderRegression:
    """scope=leader判定への影響なし回帰テスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_scope_leader判定に影響なし(self, hook):
        """is_leader_tool_use=True時、scope=leaderルールが適用され_get_caller_rolesは呼ばれない"""
        rule_infos = [
            {'rule_name': 'leader-deny', 'severity': 'deny',
             'message': 'Leader only', 'scope': 'leader'},
        ]
        input_data = {'tool_use_id': 'toolu_leader', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=True):
            with patch.object(hook, '_get_caller_roles') as mock_get_roles:
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        # scope=leaderルールが適用される
        assert len(result) == 1
        assert result[0]['rule_name'] == 'leader-deny'
        # _get_caller_rolesは呼ばれない（leaderなのでsubagent role取得不要）
        mock_get_roles.assert_not_called()
