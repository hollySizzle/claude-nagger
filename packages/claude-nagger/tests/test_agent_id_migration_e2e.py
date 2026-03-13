"""agent_id方式移行 E2E + 6カテゴリテスト（issue_7355, issue_7356）

agent_idベースのleader/subagent判定が全フローで正しく機能することを検証。
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.services.leader_detection import is_leader_tool_use, find_caller_agent_id
from src.domain.hooks.implementation_design_hook import ImplementationDesignHook
from src.domain.models.records import SubagentRecord
from src.infrastructure.db.nagger_state_db import NaggerStateDB
from src.infrastructure.db.subagent_repository import SubagentRepository


# テスト用known_roles
_KNOWN_ROLES = {"coder", "tester", "researcher", "tech-lead", "Bash", "Explore", "Plan"}


def _setup_db_with_subagent(tmp_path, agent_id, session_id, role, role_source='task_match'):
    """state.dbにsubagentレコードを登録するヘルパー"""
    db_path = tmp_path / ".claude-nagger" / "state.db"
    db = NaggerStateDB(db_path)
    db.connect()
    repo = SubagentRepository(db)
    repo.register(agent_id, session_id, "task")
    db.conn.execute(
        "UPDATE subagents SET role = ?, role_source = ?, startup_processed = 1 WHERE agent_id = ?",
        (role, role_source, agent_id),
    )
    db.conn.commit()
    return db, repo


# ============================================================
# E2E テスト (#7355): agent_idでDB検索→role取得→scope照合
# ============================================================

class TestAgentIdE2E:
    """agent_idベースE2Eテスト（issue_7355）"""

    def test_agent_id_db_lookup_returns_role(self, tmp_path):
        """E2E-1: agent_idでDB検索→SubagentRecord取得→role一致確認"""
        agent_id = "e2e-test-agent-001"
        session_id = "e2e-session"
        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "coder")

        input_data = {'agent_id': agent_id, 'session_id': session_id, 'tool_name': 'Edit'}

        hook = ImplementationDesignHook()
        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                roles = hook._get_caller_roles(input_data)

        db.close()
        assert roles == {"coder"}

    def test_no_agent_id_leader_skips_db(self):
        """E2E-2: agent_id不在（leader）→DB検索スキップ→leader判定確認"""
        input_data = {'tool_name': 'Edit', 'session_id': 'leader-session'}

        # leader判定
        assert is_leader_tool_use(input_data) is True

        # _get_caller_rolesはagent_id不在→{"leader"}（issue_8118: session_idフォールバック回避）
        hook = ImplementationDesignHook()
        with patch('domain.services.leader_detection.find_caller_agent_id', return_value=None):
            roles = hook._get_caller_roles(input_data)
        assert roles == {"leader"}

    def test_unknown_agent_id_returns_empty(self, tmp_path):
        """E2E-3: 不正agent_id（DB未登録）→None返却→フォールバック動作確認"""
        # DBに何も登録しない
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()

        input_data = {
            'agent_id': 'unknown-agent-999',
            'session_id': 'test-session',
            'tool_name': 'Edit',
        }

        hook = ImplementationDesignHook()
        with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                   return_value=db._db_path):
            roles = hook._get_caller_roles(input_data)

        db.close()
        # DB未登録agent_id → record=None → 空set
        assert roles == set()


# ============================================================
# カテゴリA: 基本判定テスト（leader/subagent/並列subagent）
# ============================================================

class TestCategoryA_BasicDetection:
    """カテゴリA: agent_idベース基本判定"""

    def test_leader_detection(self):
        """leader: agent_id不在 → True"""
        assert is_leader_tool_use({'tool_name': 'Edit'}) is True

    def test_subagent_detection(self):
        """subagent: agent_idあり → False"""
        assert is_leader_tool_use({'agent_id': 'agent-123'}) is False

    def test_parallel_subagent_detection(self):
        """並列subagent: 異なるagent_idでも全てsubagent判定"""
        for agent_id in ['agent-coder', 'agent-tester', 'agent-researcher']:
            assert is_leader_tool_use({'agent_id': agent_id}) is False


# ============================================================
# カテゴリB: エッジケース
# ============================================================

class TestCategoryB_EdgeCases:
    """カテゴリB: エッジケーステスト"""

    def test_agent_id_field_absent(self):
        """agent_idフィールド不在 → leader"""
        assert is_leader_tool_use({'tool_name': 'Edit', 'session_id': 'x'}) is True

    def test_agent_id_empty_string(self):
        """agent_id空文字 → leader（falsy値）"""
        assert is_leader_tool_use({'agent_id': ''}) is True

    def test_agent_id_none(self):
        """agent_id=None → leader（falsy値）"""
        assert is_leader_tool_use({'agent_id': None}) is True

    def test_unregistered_uuid_returns_none(self):
        """DB未登録UUID → find_caller_agent_idは返すがDB検索で空set"""
        input_data = {'agent_id': 'xxxxxxxx-0000-0000-0000-000000000000'}
        # find_caller_agent_idはinput_dataからagent_idを返す
        assert find_caller_agent_id(input_data) == 'xxxxxxxx-0000-0000-0000-000000000000'

    def test_non_dict_input(self):
        """dictでない入力 → subagent扱い（安全側）"""
        assert is_leader_tool_use("string") is False
        assert is_leader_tool_use(None) is False
        assert is_leader_tool_use(42) is False


# ============================================================
# カテゴリC: 限界テスト
# ============================================================

class TestCategoryC_LimitTests:
    """カテゴリC: coygeek方式削除確認、バージョンダウングレード時動作"""

    def test_coygeek_method_removed_from_repository(self):
        """SubagentRepository.is_leader_tool_useが削除されていること"""
        from src.infrastructure.db.subagent_repository import SubagentRepository as Repo
        assert not hasattr(Repo, 'is_leader_tool_use')

    def test_passive_detection_removed(self):
        """パッシブ検出機構が削除されていること"""
        hook = ImplementationDesignHook()
        assert not hasattr(hook, '_consecutive_non_leader_count')

    def test_leader_detection_standalone_accepts_dict_only(self):
        """is_leader_tool_useがdict以外でFalseを返すこと（旧transcript_path引数互換性なし）"""
        # 旧シグネチャ: is_leader_tool_use(transcript_path: str)
        # 新シグネチャ: is_leader_tool_use(input_data: dict)
        # 文字列を渡すとsubagent扱い（安全側フォールバック）
        assert is_leader_tool_use("/some/path.jsonl") is False


# ============================================================
# カテゴリD: 引数変更対応テスト
# ============================================================

class TestCategoryD_SignatureChange:
    """カテゴリD: 各呼出元の新シグネチャ確認"""

    def test_filter_rules_calls_is_leader_with_input_data(self):
        """_filter_rules_by_scopeがis_leader_tool_use(input_data)を呼出"""
        hook = ImplementationDesignHook()
        rules = [{'rule_name': 'r', 'severity': 'deny', 'message': 'm', 'scope': 'leader'}]
        input_data = {'tool_name': 'Edit'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=True) as mock_fn:
            hook._filter_rules_by_scope(rules, input_data)

        mock_fn.assert_called_once_with(input_data)

    def test_get_caller_roles_new_signature(self):
        """_get_caller_roles(input_data)が新シグネチャで動作"""
        hook = ImplementationDesignHook()
        input_data = {'session_id': 'test'}

        with patch('domain.services.leader_detection.find_caller_agent_id', return_value=None):
            result = hook._get_caller_roles(input_data)

        assert result == {"leader"}

    def test_find_caller_agent_id_new_signature(self):
        """find_caller_agent_id(input_data)がdict引数で動作"""
        assert find_caller_agent_id({'agent_id': 'test-123'}) == 'test-123'
        assert find_caller_agent_id({}) is None


# ============================================================
# カテゴリE: 回帰テスト
# ============================================================

class TestCategoryE_Regression:
    """カテゴリE: scope=leader deny発火/非発火、scope=role、E2E"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_scope_leader_deny_fires_for_leader(self, hook):
        """scope=leader deny: leader（agent_id不在）→ 発火"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'leader-deny', 'severity': 'deny',
                'message': 'Leader denied', 'token_threshold': None, 'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/test.py'},
                'session_id': 'test',
            })
        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True

    def test_scope_leader_deny_skips_for_subagent(self, hook):
        """scope=leader deny: subagent（agent_idあり）→ 非発火"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'leader-deny', 'severity': 'deny',
                'message': 'Leader denied', 'token_threshold': None, 'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/test.py'},
                'session_id': 'test',
                'agent_id': 'agent-coder',
            })
        assert result['decision'] == 'approve'

    def test_scope_role_applies_to_matching_role(self, hook):
        """scope=tester: tester subagentに適用"""
        rules = [{'rule_name': 'tester-deny', 'severity': 'deny',
                  'message': 'Tester denied', 'scope': 'tester'}]
        input_data = {'agent_id': 'agent-tester', 'tool_name': 'Edit'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'tester'}):
                result = hook._filter_rules_by_scope(rules, input_data)

        assert len(result) == 1

    def test_e2e_subagent_scope_role_deny(self, hook, tmp_path):
        """E2E: agent_id→DB→role=tester→scope=tester deny発火"""
        agent_id = "e2e-tester-regression"
        db, repo = _setup_db_with_subagent(tmp_path, agent_id, "sess", "tester")

        rules = [{'rule_name': 'tester-deny', 'severity': 'deny',
                  'message': 'Tester denied', 'scope': 'tester'}]
        input_data = {'agent_id': agent_id, 'tool_name': 'Edit'}

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                result = hook._filter_rules_by_scope(rules, input_data)

        db.close()
        assert len(result) == 1


# ============================================================
# カテゴリF: ブロッカー再発防止テスト
# ============================================================

class TestCategoryF_BlockerPrevention:
    """カテゴリF: coderのEdit/Write/NotebookEditがブロックされない確認"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def _make_leader_deny_rule(self, tool_name):
        return [{
            'rule_name': f'leader-{tool_name.lower()}-deny',
            'severity': 'deny',
            'message': 'leaderはファイル編集が禁止されています',
            'token_threshold': None,
            'scope': 'leader',
        }]

    def test_coder_edit_not_blocked(self, hook):
        """coderのEdit → scope=leader deny非発火"""
        with patch.object(hook.matcher, 'get_confirmation_message',
                         return_value=self._make_leader_deny_rule('Edit')):
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/src/main.py'},
                'session_id': 'test',
                'agent_id': 'agent-coder',
            })
        assert result['decision'] == 'approve'

    def test_coder_write_not_blocked(self, hook):
        """coderのWrite → scope=leader deny非発火"""
        with patch.object(hook.matcher, 'get_confirmation_message',
                         return_value=self._make_leader_deny_rule('Write')):
            result = hook.process({
                'tool_name': 'Write',
                'tool_input': {'file_path': '/src/new.py'},
                'session_id': 'test',
                'agent_id': 'agent-coder',
            })
        assert result['decision'] == 'approve'

    def test_coder_notebook_edit_not_blocked(self, hook):
        """coderのNotebookEdit → scope=leader deny非発火"""
        with patch.object(hook.matcher, 'get_confirmation_message',
                         return_value=self._make_leader_deny_rule('NotebookEdit')):
            result = hook.process({
                'tool_name': 'NotebookEdit',
                'tool_input': {'notebook_path': '/nb.ipynb'},
                'session_id': 'test',
                'agent_id': 'agent-coder',
            })
        assert result['decision'] == 'approve'
