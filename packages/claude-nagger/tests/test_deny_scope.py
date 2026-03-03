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
    """is_leader_tool_use()スタンドアロン関数のユニットテスト"""

    def test_leader_tool_use_found(self, tmp_path):
        """transcriptにtool_use_idが存在→True"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "toolu_LEADER_001", "name": "Edit"}
                ]
            }
        }
        transcript.write_text(json.dumps(entry) + "\n")

        assert is_leader_tool_use(str(transcript), "toolu_LEADER_001") is True

    def test_subagent_tool_use_not_found(self, tmp_path):
        """transcriptにtool_use_idが存在しない→False"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "toolu_OTHER_999", "name": "Edit"}
                ]
            }
        }
        transcript.write_text(json.dumps(entry) + "\n")

        assert is_leader_tool_use(str(transcript), "toolu_SUBAGENT_456") is False

    def test_nonexistent_transcript(self):
        """存在しないtranscript→False（安全側フォールバック）"""
        assert is_leader_tool_use("/nonexistent/path.jsonl", "toolu_123") is False

    def test_empty_transcript(self, tmp_path):
        """空のtranscript→False"""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        assert is_leader_tool_use(str(transcript), "toolu_123") is False

    def test_non_assistant_entries_ignored(self, tmp_path):
        """type!=assistantのエントリは無視"""
        transcript = tmp_path / "transcript.jsonl"
        entries = [
            {"type": "user", "message": {"content": [{"type": "tool_use", "id": "toolu_123"}]}},
            {"type": "system", "message": {"content": [{"type": "tool_use", "id": "toolu_123"}]}},
        ]
        transcript.write_text("\n".join(json.dumps(e) for e in entries) + "\n")

        assert is_leader_tool_use(str(transcript), "toolu_123") is False

    def test_multiple_tool_uses(self, tmp_path):
        """複数tool_useの中から正しいIDを検出"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "tool_use", "id": "toolu_AAA", "name": "Read"},
                    {"type": "text", "text": "some text"},
                    {"type": "tool_use", "id": "toolu_BBB", "name": "Edit"},
                ]
            }
        }
        transcript.write_text(json.dumps(entry) + "\n")

        assert is_leader_tool_use(str(transcript), "toolu_BBB") is True
        assert is_leader_tool_use(str(transcript), "toolu_CCC") is False


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

    def test_scope_leader_caller_is_leader(self, hook, tmp_path):
        """scope=leaderのルール、callerがleader→通過"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_L1", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        input_data = {
            'tool_use_id': 'toolu_L1',
            'transcript_path': str(transcript),
        }
        result = hook._filter_rules_by_scope(rules, input_data)
        assert len(result) == 1

    def test_scope_leader_caller_is_subagent(self, hook, tmp_path):
        """scope=leaderのルール、callerがsubagent→フィルタアウト"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        input_data = {
            'tool_use_id': 'toolu_SUBAGENT',
            'transcript_path': str(transcript),
        }
        result = hook._filter_rules_by_scope(rules, input_data)
        assert len(result) == 0

    def test_mixed_scoped_and_unscoped(self, hook, tmp_path):
        """scope付きとscope無しのルール混在"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_SUB", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
            {'rule_name': 'warn-all', 'severity': 'warn', 'message': 'warning', 'scope': None},
        ]
        input_data = {
            'tool_use_id': 'toolu_OTHER',  # subagent
            'transcript_path': str(transcript),
        }
        result = hook._filter_rules_by_scope(rules, input_data)
        # scope=leaderはフィルタアウト、scope=Noneは通過
        assert len(result) == 1
        assert result[0]['rule_name'] == 'warn-all'

    def test_empty_rules(self, hook):
        """空ルールリスト"""
        result = hook._filter_rules_by_scope([], {})
        assert result == []

    def test_no_transcript_path(self, hook):
        """transcript_pathがない場合、leader判定不能→scope=leaderはフィルタアウト"""
        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        result = hook._filter_rules_by_scope(rules, {})
        assert len(result) == 0


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

    def test_deny_leader_scope_from_subagent_edit(self, hook, tmp_path):
        """subagentからのEdit + deny + scope=leader → approve（scope不一致）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Task"}]}
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
                'tool_use_id': 'toolu_SUBAGENT',
                'transcript_path': str(transcript),
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


class TestPassiveDetection:
    """パッシブ異常検出テスト (#7235)"""

    @pytest.fixture
    def hook(self):
        return ImplementationDesignHook()

    def test_consecutive_false_triggers_warning(self, hook, tmp_path, caplog):
        """連続False回数が閾値到達時にwarning出力"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        input_data = {
            'tool_use_id': 'toolu_SUBAGENT',
            'transcript_path': str(transcript),
        }

        # 閾値を小さくしてテスト
        hook._passive_detect_threshold = 3

        import logging
        with caplog.at_level(logging.WARNING):
            # 3回連続Falseで閾値到達
            for i in range(3):
                hook._filter_rules_by_scope(rules, input_data)

        assert any("[passive_detect]" in record.message for record in caplog.records)

    def test_true_resets_counter(self, hook, tmp_path, caplog):
        """caller_is_leader=Trueでカウンタリセット"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_L1", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]

        # subagentとして2回呼出
        sub_input = {
            'tool_use_id': 'toolu_SUBAGENT',
            'transcript_path': str(transcript),
        }
        hook._passive_detect_threshold = 5
        hook._filter_rules_by_scope(rules, sub_input)
        hook._filter_rules_by_scope(rules, sub_input)
        assert hook._consecutive_non_leader_count == 2

        # leaderとして1回呼出 → リセット
        leader_input = {
            'tool_use_id': 'toolu_L1',
            'transcript_path': str(transcript),
        }
        hook._filter_rules_by_scope(rules, leader_input)
        assert hook._consecutive_non_leader_count == 0

    def test_no_warning_when_leader_mixed(self, hook, tmp_path, caplog):
        """leader=True混在時にwarning未出力"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_L1", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        rules = [
            {'rule_name': 'deny-edit', 'severity': 'deny', 'message': 'denied', 'scope': 'leader'},
        ]
        sub_input = {
            'tool_use_id': 'toolu_SUBAGENT',
            'transcript_path': str(transcript),
        }
        leader_input = {
            'tool_use_id': 'toolu_L1',
            'transcript_path': str(transcript),
        }

        hook._passive_detect_threshold = 3

        import logging
        with caplog.at_level(logging.WARNING):
            # sub, sub, leader, sub, sub のパターン → 最大連続2で閾値3未満
            hook._filter_rules_by_scope(rules, sub_input)
            hook._filter_rules_by_scope(rules, sub_input)
            hook._filter_rules_by_scope(rules, leader_input)
            hook._filter_rules_by_scope(rules, sub_input)
            hook._filter_rules_by_scope(rules, sub_input)

        assert not any("[passive_detect]" in record.message for record in caplog.records)
