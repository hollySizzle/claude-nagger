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

        assert result['decision'] == 'deny'
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

    def test_command_deny_returns_deny_decision(self, hook):
        """コマンド: deny severity → decision='deny'"""
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

        assert result['decision'] == 'deny'

    def test_mcp_deny_returns_deny_decision(self, hook):
        """MCPツール: deny severity → decision='deny'"""
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

        assert result['decision'] == 'deny'


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

        assert result['decision'] == 'deny'
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

        hook = ImplementationDesignHook()
        hook._current_permission_mode_behavior = PermissionModeBehavior.WARN_ONLY

        # process()の結果をシミュレート
        result = {'decision': 'block', 'reason': 'Blocked'}
        behavior = hook._current_permission_mode_behavior
        decision = result['decision']

        # BaseHook.run()内のWARN_ONLY変換ロジックを再現
        if behavior == PermissionModeBehavior.WARN_ONLY and decision == 'block':
            decision = 'approve'

        assert decision == 'approve'

    def test_deny_not_converted_in_warn_only(self):
        """denyはWARN_ONLYでもdenyのまま（変換されない）"""
        from src.domain.hooks.base_hook import PermissionModeBehavior

        hook = ImplementationDesignHook()
        hook._current_permission_mode_behavior = PermissionModeBehavior.WARN_ONLY

        result = {'decision': 'deny', 'reason': 'Denied'}
        behavior = hook._current_permission_mode_behavior
        decision = result['decision']

        # BaseHook.run()内のWARN_ONLY変換ロジックを再現
        if behavior == PermissionModeBehavior.WARN_ONLY and decision == 'block':
            decision = 'approve'

        # denyは'block'ではないので変換されない
        assert decision == 'deny'


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
