"""role正規化 + scope=role名 deny E2Eテスト（issue_7129）

_normalize_role()がhookフロー全体で正しく機能することを検証。
- 不正規化role値をDBに登録 → _get_caller_roles() → 正規化role返却
- 正規化後のroleでscope=role名 denyルールが正しく適用/スキップされること
- find_caller_agent_id() → SubagentRepository.get() → 正規化 → scope照合の一連フロー
"""

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from src.domain.hooks.implementation_design_hook import ImplementationDesignHook
from src.domain.services.file_convention_matcher import FileConventionMatcher
from src.domain.services.command_convention_matcher import CommandConventionMatcher
from src.domain.services.mcp_convention_matcher import McpConventionMatcher
from src.infrastructure.db.nagger_state_db import NaggerStateDB
from src.infrastructure.db.subagent_repository import SubagentRepository

# 実際のrules/ディレクトリのYAMLを使用
_RULES_DIR = Path(__file__).parent.parent / "rules"

# テスト用known_roles（config.yaml相当）
_KNOWN_ROLES = {"coder", "tester", "researcher", "tech-lead", "Bash", "Explore", "Plan"}


def _make_input(tool_name, tool_input=None, transcript_path=None,
                tool_use_id='toolu_E2E_NORM_001', agent_id=None):
    """テスト用input_data生成ヘルパー"""
    data = {
        'tool_name': tool_name,
        'tool_input': tool_input or {},
        'session_id': 'test-session-norm-e2e',
        'tool_use_id': tool_use_id,
    }
    if transcript_path:
        data['transcript_path'] = transcript_path
    if agent_id:
        data['agent_id'] = agent_id
    return data


def _setup_db_with_subagent(tmp_path, agent_id, session_id, role, role_source='task_match'):
    """state.dbにsubagentレコードを登録するヘルパー"""
    db_path = tmp_path / ".claude-nagger" / "state.db"
    db = NaggerStateDB(db_path)
    db.connect()
    repo = SubagentRepository(db)
    repo.register(agent_id, session_id, "task")
    # roleとstartup_processedを設定
    db.conn.execute(
        "UPDATE subagents SET role = ?, role_source = ?, startup_processed = 1 WHERE agent_id = ?",
        (role, role_source, agent_id),
    )
    db.conn.commit()
    return db, repo


def _setup_subagent_transcript(tmp_path, agent_id, tool_use_id):
    """subagentsディレクトリにagent transcriptを作成するヘルパー"""
    subagents_dir = tmp_path / "subagents"
    subagents_dir.mkdir(parents=True, exist_ok=True)
    agent_file = subagents_dir / f"agent-{agent_id}.jsonl"
    entry = {
        "type": "assistant",
        "message": {"content": [
            {"type": "tool_use", "id": tool_use_id, "name": "Edit"}
        ]}
    }
    agent_file.write_text(json.dumps(entry) + "\n")
    return subagents_dir


def _setup_leader_transcript(tmp_path, tool_use_id, tool_name="Edit"):
    """leader transcriptを作成するヘルパー（Task/Agent tool_use含む=subagent起動済み）

    coygeek方式ではTask/Agent tool_useの存在でleader/subagent判定を行う。
    subagentシナリオのテストではTask tool_useを含める必要がある（issue_7314）。
    """
    transcript = tmp_path / "transcript.jsonl"
    entries = [
        # leaderの操作
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_LEADER_ONLY", "name": tool_name}
        ]}},
        # leaderがsubagentを起動（coygeek方式でsubagent判定に必要）
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_TASK_SPAWN", "name": "Task",
             "input": {"prompt": "subagent起動"}}
        ]}},
    ]
    transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n")
    return transcript


def _assert_deny(result):
    """deny判定アサート"""
    assert result['decision'] == 'block', f"Expected block but got {result['decision']}"
    assert result.get('skip_warn_only') is True, "Expected skip_warn_only=True for deny"


def _assert_not_deny(result):
    """deny非該当アサート"""
    if result['decision'] == 'approve':
        return
    assert result.get('skip_warn_only') is not True, \
        f"Unexpected deny: decision={result['decision']}, reason={result.get('reason', '')[:100]}"


# ============================================================
# A. role正規化検証: _get_caller_roles()が正規化roleを返すこと
# ============================================================

class TestRoleNormalizationInGetCallerRoles:
    """_get_caller_roles()がDB上の不正規化roleを正規化して返すE2Eテスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_coder_with_suffix_normalized(self, hook, tmp_path):
        """coder-7097 → coder に正規化されること"""
        agent_id = "aaaaaaaa-1111-2222-3333-444444444444"
        session_id = "test-session-norm-e2e"

        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "coder-7097")

        # agent_idベース: input_dataにagent_idを渡す
        input_data = _make_input('Edit', agent_id=agent_id)

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                roles = hook._get_caller_roles(input_data)

        db.close()
        assert roles == {"coder"}

    def test_researcher_with_suffix_normalized(self, hook, tmp_path):
        """researcher-db → researcher に正規化されること"""
        agent_id = "bbbbbbbb-1111-2222-3333-444444444444"
        session_id = "test-session-norm-e2e"

        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "researcher-db")

        input_data = _make_input('Edit', agent_id=agent_id)

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                roles = hook._get_caller_roles(input_data)

        db.close()
        assert roles == {"researcher"}

    def test_tech_lead_preserved(self, hook, tmp_path):
        """tech-lead → tech-lead のまま（既知roleとの完全一致で壊れない）"""
        agent_id = "cccccccc-1111-2222-3333-444444444444"
        session_id = "test-session-norm-e2e"

        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "tech-lead")

        input_data = _make_input('Edit', agent_id=agent_id)

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                roles = hook._get_caller_roles(input_data)

        db.close()
        assert roles == {"tech-lead"}

    def test_pure_coder_unchanged(self, hook, tmp_path):
        """coder → coder（回帰なし: 既に正規化されたroleはそのまま）"""
        agent_id = "dddddddd-1111-2222-3333-444444444444"
        session_id = "test-session-norm-e2e"

        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "coder")

        input_data = _make_input('Edit', agent_id=agent_id)

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                roles = hook._get_caller_roles(input_data)

        db.close()
        assert roles == {"coder"}

    def test_pure_tester_unchanged(self, hook, tmp_path):
        """tester → tester（回帰なし: 既に正規化されたroleはそのまま）"""
        agent_id = "eeeeeeee-1111-2222-3333-444444444444"
        session_id = "test-session-norm-e2e"

        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "tester")

        input_data = _make_input('Edit', agent_id=agent_id)

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                roles = hook._get_caller_roles(input_data)

        db.close()
        assert roles == {"tester"}


# ============================================================
# B. scope=role名 deny E2E検証
# ============================================================

class TestScopeRoleDenyE2E:
    """正規化後のroleでscope=role名 denyルールが正しく適用されるE2Eテスト

    実際のYAMLルールとprocess()を使用し、正規化roleによるscope照合をテスト。
    """

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    def test_scope_coder_deny_after_normalization(self, hook, tmp_path):
        """scope=tester denyルール: coder-7097→coder正規化後はtester制約にマッチしない"""
        # coder-7097が正規化後coderになった場合、scope=testerのルールは適用されない
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/src/main.py'},
            str(transcript),
        )
        # 正規化後coder → scope=testerルールはスキップされる
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'coder'}):
                with patch.object(hook, 'is_rule_processed', return_value=True):
                    result = hook.process(input_data)

        _assert_not_deny(result)

    def test_scope_tester_deny_with_normalized_role(self, hook, tmp_path):
        """scope=tester denyルール: tester-7129→tester正規化後にsrc/編集がdenyされること"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/src/main.py'},
            str(transcript),
        )
        # _get_caller_rolesが正規化後の'tester'を返す（実際にはtester-7129→tester）
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'tester'}):
                result = hook.process(input_data)

        _assert_deny(result)
        assert 'testerはプロダクションコード(src/**)の編集が禁止されています' in result['reason']

    def test_scope_leader_deny_from_leader(self, hook, tmp_path):
        """scope=leader denyルール: leader tool_useでファイル編集がdenyされること"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_NORM_001", "name": "Edit"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/src/main.py'},
            str(transcript),
        )
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=True):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはファイル編集が禁止されています' in result['reason']

    def test_scope_deny_not_applied_to_different_role(self, hook, tmp_path):
        """異なるroleのsubagentにはdenyが適用されないこと"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        # scope=testerのルール → researcher-dbが正規化後researcherになった場合、適用されない
        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/src/main.py'},
            str(transcript),
        )
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'researcher'}):
                with patch.object(hook, 'is_rule_processed', return_value=True):
                    result = hook.process(input_data)

        _assert_not_deny(result)

    def test_scope_tech_lead_destructive_deny(self, hook, tmp_path):
        """scope=tech-lead denyルール: tech-lead-123→tech-lead正規化後にrm -rfがdenyされること"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'rm -rf /tmp'},
            str(transcript),
        )
        # tech-lead-123が正規化後tech-leadになったことを想定
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'tech-lead'}):
                result = hook.process(input_data)

        _assert_deny(result)
        assert 'tech-leadは破壊的コマンドが禁止されています' in result['reason']

    def test_scope_researcher_destructive_deny(self, hook, tmp_path):
        """scope=researcher denyルール: researcher-db→researcher正規化後にforce pushがdenyされること"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'git push --force origin main'},
            str(transcript),
        )
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'researcher'}):
                result = hook.process(input_data)

        _assert_deny(result)
        assert 'researcherは破壊的コマンドが禁止されています' in result['reason']

    def test_scope_leader_mcp_deny(self, hook, tmp_path):
        """scope=leader denyルール: leader MCP非許可ツール使用がdenyされること"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_NORM_001",
                 "name": "mcp__redmine_epic_grid__create_epic_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__create_epic_tool',
            {},
            str(transcript),
        )
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=True):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはこのRedmineツールの使用が禁止されています' in result['reason']


# ============================================================
# C. 結合検証: find_caller_agent_id→DB→正規化→scope照合 一連フロー
# ============================================================

class TestFullFlowIntegration:
    """find_caller_agent_id() → SubagentRepository.get() → 正規化role → scope照合の
    一連フローをテスト。DBに不正規化roleを登録し、process()までの全経路を通す。
    """

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    def test_full_flow_tester_suffix_deny(self, hook, tmp_path):
        """フルフロー: tester-7129をDBに登録→agent_idベースでDB検索→正規化→scope=tester denyが発動"""
        agent_id = "ffffffff-1111-2222-3333-444444444444"
        session_id = "test-session-full-e2e"

        # DBに不正規化role 'tester-7129' で登録
        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "tester-7129")

        # agent_idベース: input_dataにagent_idを渡す（transcript走査不要）
        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/src/main.py'},
            agent_id=agent_id,
        )

        # find_caller_agent_id → SubagentRepository.get() → _normalize_role の全経路
        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                result = hook.process(input_data)

        db.close()
        # tester-7129 → tester に正規化され、scope=tester denyルールが発動
        _assert_deny(result)
        assert 'testerはプロダクションコード(src/**)の編集が禁止されています' in result['reason']

    def test_full_flow_coder_suffix_no_tester_deny(self, hook, tmp_path):
        """フルフロー: coder-7097をDBに登録→正規化coder→scope=tester denyは適用されない"""
        agent_id = "11111111-aaaa-bbbb-cccc-dddddddddddd"
        session_id = "test-session-full-e2e"

        # DBに不正規化role 'coder-7097' で登録
        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "coder-7097")

        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/src/main.py'},
            agent_id=agent_id,
        )

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                # scope=Noneのblock/warnルールはis_rule_processedでスキップ
                with patch.object(hook, 'is_rule_processed', return_value=True):
                    result = hook.process(input_data)

        db.close()
        # coder-7097 → coder: scope=testerルールは適用されない
        _assert_not_deny(result)

    def test_full_flow_tech_lead_preserved_deny(self, hook, tmp_path):
        """フルフロー: tech-leadをDBに登録→そのまま保持→scope=tech-lead denyが発動"""
        agent_id = "22222222-aaaa-bbbb-cccc-dddddddddddd"
        session_id = "test-session-full-e2e"

        # tech-leadはknown_rolesに完全一致 → そのまま保持
        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "tech-lead")

        input_data = _make_input(
            'Bash',
            {'command': 'rm -rf /tmp'},
            agent_id=agent_id,
        )

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                result = hook.process(input_data)

        db.close()
        _assert_deny(result)
        assert 'tech-leadは破壊的コマンドが禁止されています' in result['reason']

    def test_full_flow_researcher_suffix_deny(self, hook, tmp_path):
        """フルフロー: researcher-db→researcher正規化→scope=researcher denyが発動"""
        agent_id = "33333333-aaaa-bbbb-cccc-dddddddddddd"
        session_id = "test-session-full-e2e"

        db, repo = _setup_db_with_subagent(tmp_path, agent_id, session_id, "researcher-db")

        input_data = _make_input(
            'Bash',
            {'command': 'git push --force origin main'},
            agent_id=agent_id,
        )

        with patch('infrastructure.db.subagent_repository._get_known_roles_from_config',
                   return_value=_KNOWN_ROLES):
            with patch('infrastructure.db.nagger_state_db.NaggerStateDB.resolve_db_path',
                       return_value=db._db_path):
                result = hook.process(input_data)

        db.close()
        _assert_deny(result)
        assert 'researcherは破壊的コマンドが禁止されています' in result['reason']


# ============================================================
# D. _filter_rules_by_scope × 正規化role 統合テスト
# ============================================================

class TestFilterRulesByScopeWithNormalizedRole:
    """_filter_rules_by_scope()が正規化後のroleでscope照合を行う統合テスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_normalized_coder_matches_scope_coder(self, hook):
        """正規化後coder → scope=coderルールにマッチ"""
        rule_infos = [
            {'rule_name': 'coder-deny', 'severity': 'deny',
             'message': 'coder deny', 'scope': 'coder'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            # _get_caller_rolesが正規化後のcoderを返す（coder-7097→coder）
            with patch.object(hook, '_get_caller_roles', return_value={'coder'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 1
        assert result[0]['rule_name'] == 'coder-deny'

    def test_normalized_tester_matches_scope_tester(self, hook):
        """正規化後tester → scope=testerルールにマッチ"""
        rule_infos = [
            {'rule_name': 'tester-deny', 'severity': 'deny',
             'message': 'tester deny', 'scope': 'tester'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'tester'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 1
        assert result[0]['rule_name'] == 'tester-deny'

    def test_normalized_coder_skips_scope_tester(self, hook):
        """正規化後coder → scope=testerルールはスキップ"""
        rule_infos = [
            {'rule_name': 'tester-deny', 'severity': 'deny',
             'message': 'tester deny', 'scope': 'tester'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'coder'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 0

    def test_normalized_tech_lead_matches_scope_tech_lead(self, hook):
        """正規化後tech-lead → scope=tech-leadルールにマッチ"""
        rule_infos = [
            {'rule_name': 'tech-lead-deny', 'severity': 'deny',
             'message': 'tech-lead deny', 'scope': 'tech-lead'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'tech-lead'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 1
        assert result[0]['rule_name'] == 'tech-lead-deny'

    def test_mixed_scope_rules_with_normalized_roles(self, hook):
        """複数scope混合: 正規化roleに対して正しいルールのみ適用"""
        rule_infos = [
            {'rule_name': 'global', 'severity': 'warn', 'message': 'G', 'scope': None},
            {'rule_name': 'coder-deny', 'severity': 'deny', 'message': 'C', 'scope': 'coder'},
            {'rule_name': 'tester-deny', 'severity': 'deny', 'message': 'T', 'scope': 'tester'},
            {'rule_name': 'leader-deny', 'severity': 'deny', 'message': 'L', 'scope': 'leader'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        # 正規化後tester → scope=tester + scope=Noneのみマッチ
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                   return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'tester'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        names = {r['rule_name'] for r in result}
        assert 'global' in names
        assert 'tester-deny' in names
        assert 'coder-deny' not in names
        assert 'leader-deny' not in names
