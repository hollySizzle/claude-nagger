"""find_caller_agent_id() / _get_caller_roles() agent_idベーステスト（issue_7352）"""

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
    """find_caller_agent_id()のユニットテスト（agent_idベース issue_7352）"""

    def test_正常系_agent_idあり(self):
        """input_dataにagent_idあり → agent_id返却"""
        input_data = {'agent_id': 'agent-123', 'tool_name': 'Edit'}
        result = find_caller_agent_id(input_data)
        assert result == 'agent-123'

    def test_agent_id不在(self):
        """input_dataにagent_idなし → None"""
        input_data = {'tool_name': 'Edit', 'session_id': 'test'}
        result = find_caller_agent_id(input_data)
        assert result is None

    def test_空dict(self):
        """空dict → None"""
        result = find_caller_agent_id({})
        assert result is None

    def test_非dict入力(self):
        """dictでない入力 → None"""
        result = find_caller_agent_id("not a dict")
        assert result is None

    def test_UUID形式のagent_id(self):
        """UUID形式のagent_id → そのまま返却"""
        agent_uuid = str(uuid.uuid4())
        input_data = {'agent_id': agent_uuid}
        result = find_caller_agent_id(input_data)
        assert result == agent_uuid


# === 2. _get_caller_roles() 統合テスト ===

class TestGetCallerRolesToolUseId:
    """_get_caller_roles() agent_idベース統合テスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_agent_idベースで単一role返却(self, hook):
        """find_caller_agent_idでagent特定 → SubagentRepository.getでrole返却"""
        input_data = {'agent_id': 'agent-123', 'session_id': 'test-session'}
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

                    result = hook._get_caller_roles(input_data)

        assert result == {'coder'}

    def test_agent_id不在_空set(self, hook):
        """agent_idがない → 空set（leader扱いでrole取得不要）"""
        input_data = {'session_id': 'test-session'}

        with patch('domain.services.leader_detection.find_caller_agent_id', return_value=None):
            result = hook._get_caller_roles(input_data)

        assert result == set()

    def test_後方互換_session_idベースフォールバック(self, hook):
        """agent_idなし、session_idあり → session_idベース既存ロジック"""
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
        input_data = {'tool_name': 'Edit'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=True):
            with patch.object(hook, '_get_caller_roles') as mock_get_roles:
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        # scope=leaderルールが適用される
        assert len(result) == 1
        assert result[0]['rule_name'] == 'leader-deny'
        # _get_caller_rolesは呼ばれない（leaderなのでsubagent role取得不要）
        mock_get_roles.assert_not_called()
