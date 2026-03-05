"""deny/scope拡張のテスト（issue_7027）"""

import json
import os
import tempfile
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.hooks.implementation_design_hook import ImplementationDesignHook
from src.domain.services.file_convention_matcher import FileConventionMatcher, ConventionRule
from src.domain.services.command_convention_matcher import CommandConventionMatcher
from src.domain.services.command_convention_matcher import ConventionRule as CmdConventionRule
from src.domain.services.mcp_convention_matcher import McpConventionMatcher, McpConventionRule
from src.domain.services.leader_detection import is_leader_tool_use


class TestIsLeaderToolUseStandalone:
    """is_leader_tool_use()スタンドアロン関数のユニットテスト（agent_idベース issue_7352）"""

    def test_leader_no_agent_id(self):
        """agent_idなし（leader）→ True"""
        assert is_leader_tool_use({'tool_name': 'Edit'}) is True

    def test_subagent_with_agent_id(self):
        """agent_idあり（subagent）→ False"""
        assert is_leader_tool_use({'agent_id': 'agent-123', 'tool_name': 'Edit'}) is False

    def test_empty_dict(self):
        """空dict → True（agent_id不在=leader）"""
        assert is_leader_tool_use({}) is True

    def test_non_dict_input(self):
        """dictでない入力 → False（安全側フォールバック）"""
        assert is_leader_tool_use("not a dict") is False

    def test_agent_id_empty_string(self):
        """agent_id空文字 → True（falsy=leader扱い）"""
        assert is_leader_tool_use({'agent_id': '', 'tool_name': 'Edit'}) is True

    def test_agent_id_none(self):
        """agent_id=None → True（falsy=leader扱い）"""
        assert is_leader_tool_use({'agent_id': None, 'tool_name': 'Edit'}) is True

    def test_subagent_with_uuid_agent_id(self):
        """UUID形式のagent_id → False"""
        assert is_leader_tool_use({'agent_id': 'aaaaaaaa-1111-2222-3333-444444444444'}) is False


class TestConventionRuleScopeField:
    """ConventionRuleのscopeフィールドのテスト"""

    def test_file_rule_scope_default_none(self):
        """scopeデフォルト=None"""
        rule = ConventionRule(name="test", patterns=["*.py"], severity="block", message="msg")
        assert rule.scope is None

    def test_file_rule_scope_leader(self):
        """scope=leader"""
        rule = ConventionRule(name="test", patterns=["*.py"], severity="deny", message="msg", scope="leader")
        assert rule.scope == "leader"

    def test_file_rule_severity_deny(self):
        """severity=deny"""
        rule = ConventionRule(name="test", patterns=["*.py"], severity="deny", message="msg")
        assert rule.severity == "deny"

    def test_mcp_rule_scope_leader(self):
        """McpConventionRuleもscope対応"""
        rule = McpConventionRule(name="test", tool_pattern="mcp__.*", severity="deny", message="msg", scope="leader")
        assert rule.scope == "leader"

    def test_cmd_rule_scope_leader(self):
        """CommandConventionRuleもscope対応"""
        rule = CmdConventionRule(name="test", patterns=["git push*"], severity="deny", message="msg", scope="leader")
        assert rule.scope == "leader"


class TestLoadRulesWithScope:
    """_load_rules()でscopeフィールドが読み込まれることのテスト"""

    def test_file_matcher_loads_scope(self):
        """FileConventionMatcherがscopeを読み込む"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': [{
                'name': 'deny-edit',
                'patterns': ['*.md'],
                'severity': 'deny',
                'message': 'Denied',
                'scope': 'leader'
            }]}, f)
            path = Path(f.name)

        try:
            matcher = FileConventionMatcher(path)
            assert len(matcher.rules) == 1
            assert matcher.rules[0].scope == 'leader'
            assert matcher.rules[0].severity == 'deny'
        finally:
            path.unlink()

    def test_file_matcher_scope_default(self):
        """scope未指定→None"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': [{
                'name': 'block-edit',
                'patterns': ['*.md'],
                'severity': 'block',
                'message': 'Blocked'
            }]}, f)
            path = Path(f.name)

        try:
            matcher = FileConventionMatcher(path)
            assert matcher.rules[0].scope is None
        finally:
            path.unlink()

    def test_command_matcher_loads_scope(self):
        """CommandConventionMatcherがscopeを読み込む"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': [{
                'name': 'deny-push',
                'patterns': ['git push*'],
                'severity': 'deny',
                'message': 'Denied',
                'scope': 'leader'
            }]}, f)
            path = Path(f.name)

        try:
            matcher = CommandConventionMatcher(path)
            assert matcher.rules[0].scope == 'leader'
        finally:
            path.unlink()

    def test_mcp_matcher_loads_scope(self, tmp_path):
        """McpConventionMatcherがscopeを読み込む"""
        rules_file = tmp_path / "mcp_conventions.yaml"
        with open(rules_file, 'w') as f:
            yaml.dump({'rules': [{
                'name': 'deny-mcp',
                'tool_pattern': 'mcp__test__.*',
                'severity': 'deny',
                'message': 'Denied',
                'scope': 'leader'
            }]}, f)

        matcher = McpConventionMatcher(tmp_path)
        assert matcher.rules[0].scope == 'leader'


class TestGetConfirmationMessageScope:
    """get_confirmation_messageがscopeを返すことのテスト"""

    def test_file_matcher_returns_scope(self):
        """FileConventionMatcher.get_confirmation_messageがscopeを含む"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': [{
                'name': 'deny-edit',
                'patterns': ['**/*.md'],
                'severity': 'deny',
                'message': 'Denied',
                'scope': 'leader'
            }]}, f)
            path = Path(f.name)

        try:
            matcher = FileConventionMatcher(path)
            results = matcher.get_confirmation_message('/project/README.md')
            assert len(results) == 1
            assert results[0]['scope'] == 'leader'
            assert results[0]['severity'] == 'deny'
        finally:
            path.unlink()

    def test_command_matcher_returns_scope(self):
        """CommandConventionMatcher.get_confirmation_messageがscopeを含む"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': [{
                'name': 'deny-push',
                'patterns': ['git push*'],
                'severity': 'deny',
                'message': 'Denied',
                'scope': 'leader'
            }]}, f)
            path = Path(f.name)

        try:
            matcher = CommandConventionMatcher(path)
            results = matcher.get_confirmation_message('git push origin main')
            assert len(results) == 1
            assert results[0]['scope'] == 'leader'
        finally:
            path.unlink()

    def test_mcp_matcher_returns_scope(self, tmp_path):
        """McpConventionMatcher.get_confirmation_messageがscopeを含む"""
        rules_file = tmp_path / "mcp_conventions.yaml"
        with open(rules_file, 'w') as f:
            yaml.dump({'rules': [{
                'name': 'deny-mcp',
                'tool_pattern': 'mcp__test__.*',
                'severity': 'deny',
                'message': 'Denied',
                'scope': 'leader'
            }]}, f)

        matcher = McpConventionMatcher(tmp_path)
        results = matcher.get_confirmation_message('mcp__test__tool')
        assert len(results) == 1
        assert results[0]['scope'] == 'leader'


class TestFilterRulesByScope:
    """ImplementationDesignHook._filter_rules_by_scopeのテスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_no_scoped_rules_passthrough(self, hook):
        """scope未指定のルールはそのまま通過"""
        rules = [
            {'rule_name': 'r1', 'severity': 'block', 'message': 'msg1', 'scope': None},
            {'rule_name': 'r2', 'severity': 'warn', 'message': 'msg2', 'scope': None},
        ]
        result = hook._filter_rules_by_scope(rules, {})
        assert len(result) == 2

    def test_scope_leader_caller_is_leader(self, hook):
        """scope=leaderのルール、callerがleader（agent_id不在）→通過"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        # agent_id不在 = leader
        input_data = {'tool_name': 'Edit'}
        result = hook._filter_rules_by_scope(rules, input_data)
        assert len(result) == 1

    def test_scope_leader_caller_is_subagent(self, hook):
        """scope=leaderのルール、callerがsubagent（agent_idあり）→フィルタアウト"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        # agent_idあり = subagent
        input_data = {'agent_id': 'agent-sub-001', 'tool_name': 'Edit'}
        result = hook._filter_rules_by_scope(rules, input_data)
        assert len(result) == 0

    def test_mixed_scoped_and_unscoped(self, hook):
        """scope付きとscope無しのルール混在"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
            {'rule_name': 'warn-all', 'severity': 'warn', 'message': 'warning', 'scope': None},
        ]
        # agent_idあり = subagent
        input_data = {'agent_id': 'agent-sub-001', 'tool_name': 'Edit'}
        result = hook._filter_rules_by_scope(rules, input_data)
        # scope=leaderはフィルタアウト、scope=Noneは通過
        assert len(result) == 1
        assert result[0]['rule_name'] == 'warn-all'

    def test_empty_rules(self, hook):
        """空ルールリスト"""
        result = hook._filter_rules_by_scope([], {})
        assert result == []

    def test_no_agent_id_is_leader(self, hook):
        """agent_idがない場合→leader判定→scope=leaderは通過"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        result = hook._filter_rules_by_scope(rules, {})
        assert len(result) == 1


class TestDenySeverityProcess:
    """deny severity処理のテスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_file_deny_returns_deny_decision(self, hook):
        """ファイル編集: deny severity → decision='deny'"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-edit',
                'severity': 'deny',
                'message': 'Edit denied',
                'token_threshold': None,
                'scope': None,
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/test/file.md'},
                'session_id': 'test-session',
            })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True
        assert 'Edit denied' in result['reason']

    def test_file_block_returns_block_decision(self, hook):
        """ファイル編集: block severity → decision='block'（従来互換）"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'block-edit',
                'severity': 'block',
                'message': 'Edit blocked',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                result = hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'test-session',
                })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is not True

    def test_deny_skips_marker(self, hook):
        """deny severityはマーカー作成をスキップ"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-edit',
                'severity': 'deny',
                'message': 'Edit denied',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'mark_rule_processed') as mock_marker:
                result = hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'test-session',
                })

        # deny時はマーカーが作成されない
        mock_marker.assert_not_called()

    def test_command_deny_returns_block_with_skip(self, hook):
        """コマンド: deny severity → decision='block' + skip_warn_only=True"""
        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-push',
                'severity': 'deny',
                'message': 'Push denied',
                'token_threshold': None,
                'scope': None,
            }]
            result = hook.process({
                'tool_name': 'Bash',
                'tool_input': {'command': 'git push'},
                'session_id': 'test-session',
            })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True

    def test_mcp_deny_returns_block_with_skip(self, hook):
        """MCPツール: deny severity → decision='block' + skip_warn_only=True"""
        with patch.object(hook.mcp_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-mcp',
                'severity': 'deny',
                'message': 'MCP denied',
                'token_threshold': None,
                'scope': None,
            }]
            result = hook.process({
                'tool_name': 'mcp__test__tool',
                'tool_input': {},
                'session_id': 'test-session',
            })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True


class TestDenyScopeIntegration:
    """deny + scope=leader の統合テスト"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_deny_leader_scope_from_leader_edit(self, hook, tmp_path):
        """leaderからのEdit + deny + scope=leader → deny"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_L1", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-edit',
                'severity': 'deny',
                'message': 'Leader edit denied',
                'token_threshold': None,
                'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/test/file.md'},
                'session_id': 'test-session',
                'tool_use_id': 'toolu_L1',
                'transcript_path': str(transcript),
            })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True
        assert 'Leader edit denied' in result['reason']

    def test_deny_leader_scope_from_subagent_edit(self, hook):
        """subagentからのEdit + deny + scope=leader → approve（scope不一致）"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-edit',
                'severity': 'deny',
                'message': 'Leader edit denied',
                'token_threshold': None,
                'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/test/file.md'},
                'session_id': 'test-session',
                'agent_id': 'agent-sub-001',
            })

        assert result['decision'] == 'approve'

    def test_scope_none_applies_to_all(self, hook):
        """scope=Noneのルールは全agentに適用"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'block-all',
                'severity': 'block',
                'message': 'Blocked for all',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                result = hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'test-session',
                })

        assert result['decision'] == 'block'


class TestDenyWarnOnlyNotConverted:
    """denyはWARN_ONLYモードでも変換されないことのテスト"""

    def test_block_converted_to_approve_in_warn_only(self):
        """blockはWARN_ONLYでapproveに変換される（従来動作確認）"""
        from src.domain.hooks.base_hook import PermissionModeBehavior

        # process()の結果をシミュレート（通常block、skip_warn_onlyなし）
        result = {'decision': 'block', 'reason': 'Blocked'}
        behavior = PermissionModeBehavior.WARN_ONLY
        decision = result['decision']

        # BaseHook.run()内のWARN_ONLY変換ロジックを再現
        if behavior == PermissionModeBehavior.WARN_ONLY and decision == 'block' and not result.get('skip_warn_only'):
            decision = 'approve'

        assert decision == 'approve'

    def test_deny_not_converted_in_warn_only(self):
        """deny(skip_warn_only=True)はWARN_ONLYでもblockのまま（変換されない）"""
        from src.domain.hooks.base_hook import PermissionModeBehavior

        # process()の結果をシミュレート（deny相当: block + skip_warn_only=True）
        result = {'decision': 'block', 'reason': 'Denied', 'skip_warn_only': True}
        behavior = PermissionModeBehavior.WARN_ONLY
        decision = result['decision']

        # BaseHook.run()内のWARN_ONLY変換ロジックを再現
        if behavior == PermissionModeBehavior.WARN_ONLY and decision == 'block' and not result.get('skip_warn_only'):
            decision = 'approve'

        # skip_warn_only=Trueなので変換されない
        assert decision == 'block'


class TestDenyWarnOnlyIntegration:
    """BaseHook.run()経由のdeny+WARN_ONLY統合テスト"""

    def test_deny_not_converted_via_run(self):
        """BaseHook.run()経由: deny(skip_warn_only)はWARN_ONLYでもdeny出力"""
        input_data = {
            'hook_event_name': 'PreToolUse',
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/test/file.md'},
            'session_id': 'test-session',
            'permission_mode': 'dontAsk',
        }
        stdin_json = json.dumps(input_data)

        hook = ImplementationDesignHook()

        with patch('sys.stdin', MagicMock(read=MagicMock(return_value=stdin_json))):
            with patch.object(hook, 'should_skip_session', return_value=False):
                with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
                    mock_match.return_value = [{
                        'rule_name': 'deny-edit',
                        'severity': 'deny',
                        'message': 'Denied by rule',
                        'token_threshold': None,
                        'scope': None,
                    }]
                    with patch('builtins.print') as mock_print:
                        exit_code = hook.run()

        # denyなのでexit_code=0（正常終了）、出力にpermissionDecision=denyが含まれる
        assert exit_code == 0
        mock_print.assert_called_once()
        output = mock_print.call_args[0][0]
        output_data = json.loads(output)
        assert output_data['hookSpecificOutput']['permissionDecision'] == 'deny'

    def test_block_converted_via_run(self):
        """BaseHook.run()経由: blockはWARN_ONLYでallow出力に変換"""
        input_data = {
            'hook_event_name': 'PreToolUse',
            'tool_name': 'Edit',
            'tool_input': {'file_path': '/test/file.md'},
            'session_id': 'test-session',
            'permission_mode': 'dontAsk',
        }
        stdin_json = json.dumps(input_data)

        hook = ImplementationDesignHook()

        with patch('sys.stdin', MagicMock(read=MagicMock(return_value=stdin_json))):
            with patch.object(hook, 'should_skip_session', return_value=False):
                with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
                    mock_match.return_value = [{
                        'rule_name': 'block-edit',
                        'severity': 'block',
                        'message': 'Blocked by rule',
                        'token_threshold': None,
                        'scope': None,
                    }]
                    with patch.object(hook, 'is_rule_processed', return_value=False):
                        with patch('builtins.print') as mock_print:
                            exit_code = hook.run()

        # blockはWARN_ONLYでallowに変換される
        assert exit_code == 0
        mock_print.assert_called_once()
        output = mock_print.call_args[0][0]
        output_data = json.loads(output)
        assert output_data['hookSpecificOutput']['permissionDecision'] == 'allow'


class TestShouldProcessDenyAlwaysFires:
    """deny severityのルールはマーカーに関わらず常に発火"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_deny_rule_always_unprocessed(self, hook):
        """deny severityのルールはis_rule_processedに関わらず処理対象"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-edit',
                'severity': 'deny',
                'message': 'Always denied',
                'token_threshold': None,
                'scope': None,
            }]
            # マーカーが存在していても関係ない
            with patch.object(hook, 'is_rule_processed', return_value=True):
                result = hook.should_process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'test-session',
                })

        assert result is True

    def test_block_rule_skipped_when_processed(self, hook):
        """block severityのルールはマーカー存在時スキップ可能"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'block-edit',
                'severity': 'block',
                'message': 'Blocked',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_rule_processed', return_value=True):
                with patch.object(hook, 'get_rule_marker_path') as mock_marker_path:
                    mock_path = MagicMock()
                    mock_path.exists.return_value = True
                    mock_marker_path.return_value = mock_path
                    with patch('builtins.open', create=True) as mock_open:
                        mock_open.return_value.__enter__ = lambda s: s
                        mock_open.return_value.__exit__ = MagicMock(return_value=False)
                        mock_open.return_value.read.return_value = json.dumps({'tokens': 100})
                        with patch.object(hook, '_get_current_context_size', return_value=110):
                            with patch.object(hook, '_get_rule_threshold', return_value=50000):
                                result = hook.should_process({
                                    'tool_name': 'Edit',
                                    'tool_input': {'file_path': '/test/file.md'},
                                    'session_id': 'test-session',
                                })

        # 閾値未到達: スキップ可能
        assert result is False


class TestScopeRoleName:
    """scope=role名によるrole別ツール制限テスト（issue_7030 T5）"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_scope_coder_matches_coder_role(self, hook):
        """scope=coderのルールはrole=coderのsubagentに適用"""
        rule_infos = [
            {'rule_name': 'deny-coder-edit', 'severity': 'deny',
             'message': 'Coder deny', 'scope': 'coder'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'coder'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 1
        assert result[0]['rule_name'] == 'deny-coder-edit'

    def test_scope_coder_skips_tester_role(self, hook):
        """scope=coderのルールはrole=testerのsubagentには適用されない"""
        rule_infos = [
            {'rule_name': 'deny-coder-edit', 'severity': 'deny',
             'message': 'Coder deny', 'scope': 'coder'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'tester'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 0

    def test_scope_role_and_none_mixed(self, hook):
        """scope=role名とscope=Noneの混合: roleマッチ+全agent対象の両方が返る"""
        rule_infos = [
            {'rule_name': 'global-rule', 'severity': 'warn',
             'message': 'Global warning', 'scope': None},
            {'rule_name': 'coder-rule', 'severity': 'deny',
             'message': 'Coder deny', 'scope': 'coder'},
            {'rule_name': 'tester-rule', 'severity': 'block',
             'message': 'Tester block', 'scope': 'tester'},
        ]
        input_data = {'tool_use_id': 'toolu_sub', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'coder'}):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 2
        names = {r['rule_name'] for r in result}
        assert 'global-rule' in names
        assert 'coder-rule' in names
        assert 'tester-rule' not in names

    def test_scope_leader_not_affected_by_role(self, hook):
        """scope=leaderはrole名マッチではなくleader判定で処理される"""
        rule_infos = [
            {'rule_name': 'leader-rule', 'severity': 'deny',
             'message': 'Leader only', 'scope': 'leader'},
        ]
        input_data = {'tool_use_id': 'toolu_leader', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=True):
            with patch.object(hook, '_get_caller_roles', return_value=set()):
                result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 1
        assert result[0]['rule_name'] == 'leader-rule'

    def test_scope_role_from_leader_skipped(self, hook):
        """leaderはrole名スコープルールの対象外"""
        rule_infos = [
            {'rule_name': 'coder-rule', 'severity': 'deny',
             'message': 'Coder deny', 'scope': 'coder'},
        ]
        input_data = {'tool_use_id': 'toolu_leader', 'transcript_path': '/test/t.jsonl'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=True):
            result = hook._filter_rules_by_scope(rule_infos, input_data)

        assert len(result) == 0

    def test_scope_none_regression(self, hook):
        """scope=Noneの回帰テスト: 全agent（leader/subagent）に適用"""
        rule_infos = [
            {'rule_name': 'global-rule', 'severity': 'block',
             'message': 'Global', 'scope': None},
        ]
        # leader
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=True):
            result_leader = hook._filter_rules_by_scope(
                rule_infos, {'tool_use_id': 'toolu_l', 'transcript_path': '/t.jsonl'}
            )
        # subagent
        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use', return_value=False):
            with patch.object(hook, '_get_caller_roles', return_value={'coder'}):
                result_sub = hook._filter_rules_by_scope(
                    rule_infos, {'tool_use_id': 'toolu_s', 'transcript_path': '/t.jsonl'}
                )

        assert len(result_leader) == 1
        assert len(result_sub) == 1


class TestDenyPriority:
    """deny優先度テスト（deny > block > warn）（issue_7030 T6）"""

    def test_sort_by_severity(self):
        """_sort_by_severity: deny > block > warn > info の順にソート"""
        from src.domain.hooks.implementation_design_hook import _sort_by_severity
        rules = [
            {'rule_name': 'warn-rule', 'severity': 'warn', 'message': 'W'},
            {'rule_name': 'deny-rule', 'severity': 'deny', 'message': 'D'},
            {'rule_name': 'block-rule', 'severity': 'block', 'message': 'B'},
            {'rule_name': 'info-rule', 'severity': 'info', 'message': 'I'},
        ]
        sorted_rules = _sort_by_severity(rules)
        assert [r['severity'] for r in sorted_rules] == ['deny', 'block', 'warn', 'info']

    def test_deny_plus_block_returns_skip_warn_only(self):
        """deny+blockルール同時マッチ → skip_warn_only=True"""
        hook = ImplementationDesignHook()
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [
                {'rule_name': 'block-rule', 'severity': 'block',
                 'message': 'Block msg', 'token_threshold': None, 'scope': None},
                {'rule_name': 'deny-rule', 'severity': 'deny',
                 'message': 'Deny msg', 'token_threshold': None, 'scope': None},
            ]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                result = hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'test-session',
                })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True
        # deny message appears first (priority sort)
        assert result['reason'].index('Deny msg') < result['reason'].index('Block msg')

    def test_block_only_no_skip_warn_only(self):
        """blockのみ → skip_warn_only未設定"""
        hook = ImplementationDesignHook()
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [
                {'rule_name': 'block-rule', 'severity': 'block',
                 'message': 'Block msg', 'token_threshold': None, 'scope': None},
            ]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                result = hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'test-session',
                })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is not True

    def test_deny_message_first_in_combined(self):
        """複数severity混合時、deny→block→warnの順でメッセージ結合"""
        hook = ImplementationDesignHook()
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [
                {'rule_name': 'warn-rule', 'severity': 'warn',
                 'message': 'WARN_MSG', 'token_threshold': None, 'scope': None},
                {'rule_name': 'deny-rule', 'severity': 'deny',
                 'message': 'DENY_MSG', 'token_threshold': None, 'scope': None},
                {'rule_name': 'block-rule', 'severity': 'block',
                 'message': 'BLOCK_MSG', 'token_threshold': None, 'scope': None},
            ]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                result = hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'test-session',
                })

        reason = result['reason']
        deny_pos = reason.index('DENY_MSG')
        block_pos = reason.index('BLOCK_MSG')
        warn_pos = reason.index('WARN_MSG')
        assert deny_pos < block_pos < warn_pos


class TestPassiveDetectionRemoved:
    """パッシブ異常検出機構が削除されたことの検証（issue_7352: agent_idベース移行）"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_passive_detect_attribute_removed(self, hook):
        """_consecutive_non_leader_countアトリビュートが存在しないこと"""
        assert not hasattr(hook, '_consecutive_non_leader_count')


# --- T4: 実transcriptフィクスチャテスト (#7232) ---

class TestIsLeaderToolUseAgentIdBased:
    """agent_idベースのis_leader_tool_use()テスト（issue_7352）

    transcript走査は全廃され、input_data['agent_id']の有無で判定する。
    """

    def test_leader_no_agent_id(self):
        """agent_id不在 → True（leader）"""
        assert is_leader_tool_use({'tool_name': 'Edit', 'session_id': 'test'}) is True

    def test_subagent_with_agent_id(self):
        """agent_idあり → False（subagent）"""
        assert is_leader_tool_use({'agent_id': 'agent-123', 'tool_name': 'Edit'}) is False

    def test_non_dict_input_safe_fallback(self):
        """dictでない入力 → False（安全側=subagent扱い）"""
        assert is_leader_tool_use("string input") is False
        assert is_leader_tool_use(42) is False
        assert is_leader_tool_use(None) is False


# --- T5: transcript形式スキーマ検証テスト (#7233) ---

class TestTranscriptSchemaValidation:
    """transcript JSONL形式のスキーマ検証テスト"""

    FIXTURE_PATH = Path(__file__).parent / "fixtures" / "claude_code" / "transcript" / "real_transcript_sample.jsonl"

    @pytest.fixture
    def entries(self):
        """フィクスチャファイルの全エントリを読み込み"""
        result = []
        with open(self.FIXTURE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    result.append(json.loads(line))
        return result

    def test_assistant_entry_has_message(self, entries):
        """type:assistantエントリにmessageキー存在"""
        assistant_entries = [e for e in entries if e.get("type") == "assistant"]
        assert len(assistant_entries) >= 1, "assistantエントリが存在しない"
        for entry in assistant_entries:
            assert "message" in entry, f"messageキー欠落: uuid={entry.get('uuid')}"

    def test_message_has_content_list(self, entries):
        """messageにcontentリスト存在"""
        assistant_entries = [e for e in entries if e.get("type") == "assistant"]
        for entry in assistant_entries:
            message = entry["message"]
            assert "content" in message, "contentキー欠落"
            assert isinstance(message["content"], list), "contentがリストでない"
            assert len(message["content"]) >= 1, "contentが空"

    def test_tool_use_has_required_fields(self, entries):
        """type:tool_useエントリにid,nameフィールド存在"""
        tool_uses = []
        for entry in entries:
            if entry.get("type") != "assistant":
                continue
            for item in entry.get("message", {}).get("content", []):
                if isinstance(item, dict) and item.get("type") == "tool_use":
                    tool_uses.append(item)

        assert len(tool_uses) >= 1, "tool_useエントリが存在しない"
        for tu in tool_uses:
            assert "id" in tu, f"idフィールド欠落: {tu}"
            assert "name" in tu, f"nameフィールド欠落: {tu}"

    def test_non_assistant_entries_structure(self, entries):
        """type:user等のエントリ形式確認"""
        non_assistant = [e for e in entries if e.get("type") != "assistant"]
        assert len(non_assistant) >= 1, "non-assistantエントリが存在しない"
        for entry in non_assistant:
            assert "type" in entry, "typeキー欠落"
            assert "message" in entry, "messageキー欠落"
            assert "uuid" in entry, "uuidキー欠落"
            assert "timestamp" in entry, "timestampキー欠落"


# ============================================================================
# カテゴリD: tool_use_id引数削除後の呼び出し元テスト (issue_7313)
# ============================================================================

class TestCallSiteAgentIdBased:
    """is_leader_tool_use()がinput_dataで呼ばれることの検証（issue_7352 agent_idベース）

    _filter_rules_by_scopeがis_leader_tool_use(input_data)をdict引数で呼んでいることを確認する。
    """

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_filter_rules_by_scope_calls_with_input_data(self, hook):
        """_filter_rules_by_scopeがis_leader_tool_use(input_data)をdict引数で呼出"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        input_data = {'tool_name': 'Edit', 'session_id': 'test'}

        with patch('src.domain.hooks.implementation_design_hook.is_leader_tool_use',
                    return_value=True) as mock_leader:
            hook._filter_rules_by_scope(rules, input_data)

        # input_data dictで呼ばれていること
        mock_leader.assert_called_once_with(input_data)

    def test_filter_rules_leader_no_agent_id(self, hook):
        """agent_id不在→leader→deny通過"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        # agent_idなし = leader
        input_data = {'tool_name': 'Edit'}

        result = hook._filter_rules_by_scope(rules, input_data)
        assert len(result) == 1, "leader判定でscope=leaderルールが通過すべき"

    def test_filter_rules_subagent_with_agent_id(self, hook):
        """agent_idあり→subagent→denyフィルタアウト"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        # agent_idあり = subagent
        input_data = {'agent_id': 'agent-coder-001', 'tool_name': 'Edit'}

        result = hook._filter_rules_by_scope(rules, input_data)
        assert len(result) == 0, "非leader判定でscope=leaderルールはフィルタアウトすべき"


# ============================================================================
# カテゴリE: 回帰テスト scope適用/スキップ (issue_7313)
# ============================================================================

class TestScopeApplySkipRegression:
    """agent_idベース切替後のscope適用/スキップ回帰テスト（issue_7352）

    is_leader_tool_use()がagent_idベースに変更された後も、
    scope=leader deny/scope=None/scope=role の動作が正しいことを検証する。
    """

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_scope_leader_deny_fires_for_leader(self, hook):
        """scope=leader deny: agent_id不在（leader）→ ルール適用"""
        rules = [
            {'rule_name': 'leader-edit-deny', 'severity': 'deny',
             'message': 'leaderはファイル編集が禁止されています', 'scope': 'leader'},
        ]
        # agent_id不在 = leader
        result = hook._filter_rules_by_scope(rules, {'tool_name': 'Edit'})
        assert len(result) == 1
        assert result[0]['rule_name'] == 'leader-edit-deny'

    def test_scope_leader_deny_skips_for_subagent(self, hook):
        """scope=leader deny: agent_idあり（subagent）→ ルールスキップ"""
        rules = [
            {'rule_name': 'leader-edit-deny', 'severity': 'deny',
             'message': 'leaderはファイル編集が禁止されています', 'scope': 'leader'},
        ]
        # agent_idあり = subagent
        result = hook._filter_rules_by_scope(rules, {
            'agent_id': 'agent-coder-001', 'tool_name': 'Edit',
        })
        assert len(result) == 0

    def test_scope_none_applies_regardless_of_leader(self, hook):
        """scope=None: leader/subagent両方でルール適用"""
        rules = [
            {'rule_name': 'warn-all', 'severity': 'warn',
             'message': '全agent対象の警告', 'scope': None},
        ]

        # leader（agent_id不在）
        result_leader = hook._filter_rules_by_scope(rules, {'tool_name': 'Edit'})
        assert len(result_leader) == 1

        # subagent（agent_idあり）
        result_sub = hook._filter_rules_by_scope(rules, {
            'agent_id': 'agent-sub', 'tool_name': 'Edit',
        })
        assert len(result_sub) == 1

    def test_mixed_scope_leader_and_none_leader_session(self, hook):
        """leader session: scope=leaderは通過、scope=Noneも通過"""
        rules = [
            {'rule_name': 'deny-leader', 'severity': 'deny',
             'message': 'leader deny', 'scope': 'leader'},
            {'rule_name': 'warn-all', 'severity': 'warn',
             'message': 'all warning', 'scope': None},
        ]
        # agent_id不在 = leader
        result = hook._filter_rules_by_scope(rules, {'tool_name': 'Edit'})
        assert len(result) == 2

    def test_mixed_scope_leader_and_none_subagent_session(self, hook):
        """subagent session: scope=leaderはスキップ、scope=Noneは通過"""
        rules = [
            {'rule_name': 'deny-leader', 'severity': 'deny',
             'message': 'leader deny', 'scope': 'leader'},
            {'rule_name': 'warn-all', 'severity': 'warn',
             'message': 'all warning', 'scope': None},
        ]
        # agent_idあり = subagent
        result = hook._filter_rules_by_scope(rules, {
            'agent_id': 'agent-sub', 'tool_name': 'Edit',
        })
        assert len(result) == 1
        assert result[0]['rule_name'] == 'warn-all'

    def test_empty_input_treated_as_leader(self, hook):
        """空input_data → leader判定（agent_id不在）→ scope=leaderルール適用"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny',
             'message': 'denied', 'scope': 'leader'},
        ]
        result = hook._filter_rules_by_scope(rules, {})
        assert len(result) == 1, "空input_data=leader=scope=leaderルール適用"


# ============================================================================
# カテゴリF: ブロッカー再発防止テスト (issue_7313)
# ============================================================================

class TestBlockerPreventionCoderEdit:
    """coder(subagent)がEdit時にscope=leader denyが発火しないことの検証（agent_idベース）

    issue_7291で発生したブロッカー再発防止:
    coderがEdit/Write/NotebookEditを使用する際に、
    scope=leader deny rules が誤発火しないことを保証する。
    agent_idの有無でleader/subagentを判定する（issue_7352）。
    """

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_coder_edit_not_blocked_by_leader_deny(self, hook):
        """coderのEdit（agent_idあり）→ scope=leader deny非発火 → approve"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'leader-edit-deny',
                'severity': 'deny',
                'message': 'leaderはファイル編集が禁止されています',
                'token_threshold': None,
                'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/src/main.py'},
                'session_id': 'test-session',
                'agent_id': 'agent-coder-001',
            })

        # agent_idあり → subagent → scope=leaderルールスキップ → approve
        assert result['decision'] == 'approve'

    def test_coder_write_not_blocked_by_leader_deny(self, hook):
        """coderのWrite（agent_idあり）→ scope=leader deny非発火 → approve"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'leader-write-deny',
                'severity': 'deny',
                'message': 'leaderはファイル編集が禁止されています',
                'token_threshold': None,
                'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Write',
                'tool_input': {'file_path': '/src/new_file.py'},
                'session_id': 'test-session',
                'agent_id': 'agent-coder-001',
            })

        assert result['decision'] == 'approve'

    def test_coder_notebook_edit_not_blocked(self, hook):
        """coderのNotebookEdit（agent_idあり）→ scope=leader deny非発火 → approve"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'leader-notebook-deny',
                'severity': 'deny',
                'message': 'leaderはファイル編集が禁止されています',
                'token_threshold': None,
                'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'NotebookEdit',
                'tool_input': {'notebook_path': '/notebooks/analysis.ipynb'},
                'session_id': 'test-session',
                'agent_id': 'agent-coder-001',
            })

        assert result['decision'] == 'approve'

    def test_leader_edit_still_blocked(self, hook):
        """対照テスト: leaderのEdit（agent_id不在）→ scope=leader deny発火 → block"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'leader-edit-deny',
                'severity': 'deny',
                'message': 'leaderはファイル編集が禁止されています',
                'token_threshold': None,
                'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/src/main.py'},
                'session_id': 'test-session',
                # agent_id不在 = leader
            })

        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True

    def test_parallel_subagents_no_false_leader(self, hook):
        """並列subagent（agent_idあり）→ どのsubagentのEditもapprove"""
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'leader-edit-deny',
                'severity': 'deny',
                'message': 'leaderはファイル編集が禁止されています',
                'token_threshold': None,
                'scope': 'leader',
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/src/main.py'},
                'session_id': 'test-session',
                'agent_id': 'agent-coder-001',
            })

        assert result['decision'] == 'approve'
