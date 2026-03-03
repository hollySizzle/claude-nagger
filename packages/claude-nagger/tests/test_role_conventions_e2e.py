"""role別conventions YAML制約のE2Eテスト（issue_7063）

実際のYAMLファイル（rules/file_conventions.yaml, rules/command_conventions.yaml,
rules/mcp_conventions.yaml）を読み込み、ImplementationDesignHook.process()経由で
各role × 各ツール制限の動作を検証する。
"""

import json
from pathlib import Path
import pytest
from unittest.mock import patch

from src.domain.hooks.implementation_design_hook import ImplementationDesignHook
from src.domain.services.file_convention_matcher import FileConventionMatcher
from src.domain.services.command_convention_matcher import CommandConventionMatcher
from src.domain.services.mcp_convention_matcher import McpConventionMatcher

# 実際のrules/ディレクトリのYAMLを使用（.claude-nagger/ではなく）
_RULES_DIR = Path(__file__).parent.parent / "rules"


def _make_input(tool_name, tool_input=None, transcript_path=None):
    """テスト用input_data生成ヘルパー"""
    data = {
        'tool_name': tool_name,
        'tool_input': tool_input or {},
        'session_id': 'test-session-e2e',
        'tool_use_id': 'toolu_E2E_001',
    }
    if transcript_path:
        data['transcript_path'] = transcript_path
    return data


def _mock_leader(hook):
    """leader判定mock: is_leader_tool_use=True"""
    return patch(
        'src.domain.hooks.implementation_design_hook.is_leader_tool_use',
        return_value=True,
    )


def _mock_role(hook, role_name):
    """特定role判定mock: is_leader=False + _get_caller_roles={role_name}"""
    leader_patch = patch(
        'src.domain.hooks.implementation_design_hook.is_leader_tool_use',
        return_value=False,
    )
    roles_patch = patch.object(
        hook, '_get_caller_roles', return_value={role_name},
    )
    return leader_patch, roles_patch


def _mock_unknown_subagent(hook):
    """role不明subagent: is_leader=False + _get_caller_roles=空"""
    leader_patch = patch(
        'src.domain.hooks.implementation_design_hook.is_leader_tool_use',
        return_value=False,
    )
    roles_patch = patch.object(
        hook, '_get_caller_roles', return_value=set(),
    )
    return leader_patch, roles_patch


def _assert_deny(result):
    """deny判定アサート: decision=block + skip_warn_only=True"""
    assert result['decision'] == 'block', f"Expected block but got {result['decision']}"
    assert result.get('skip_warn_only') is True, "Expected skip_warn_only=True for deny"


def _assert_not_deny(result):
    """deny非該当アサート: approveまたはskip_warn_only非True"""
    if result['decision'] == 'approve':
        return  # approve = OK
    # blockでもskip_warn_only=Trueでなければdenyではない
    assert result.get('skip_warn_only') is not True, \
        f"Unexpected deny: decision={result['decision']}, reason={result.get('reason', '')[:100]}"


class TestDenyByRole:
    """deny確認テスト: 各role制約がprocess()経由で正しくdeny判定される"""

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    # --- ケース1: leader + Edit → deny（leader全ファイル編集禁止） ---
    def test_leader_edit_deny(self, hook, tmp_path):
        """leader + Edit → deny（file_conventions: leader全ファイル編集禁止, scope=leader）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_E2E_001", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/src/main.py'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはファイル編集が禁止されています' in result['reason']

    # --- ケース2: leader + Bash("npm install") → deny（leader非gitコマンド禁止） ---
    def test_leader_non_git_command_deny(self, hook, tmp_path):
        """leader + Bash(npm install) → deny（command_conventions: leader非gitコマンド禁止, scope=leader）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_E2E_001", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'npm install'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはgitコマンド以外のBash実行が禁止されています' in result['reason']

    # --- ケース3: leader + mcp__redmine_epic_grid__create_epic_tool → deny ---
    def test_leader_redmine_non_allowed_mcp_deny(self, hook, tmp_path):
        """leader + 非許可Redmine MCP → deny（mcp_conventions: leaderRedmine非許可MCP禁止, scope=leader）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001", "name": "mcp__redmine_epic_grid__create_epic_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__create_epic_tool',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはこのRedmineツールの使用が禁止されています' in result['reason']

    # --- ケース4: tech-lead + Bash("rm -rf /tmp") → deny ---
    def test_tech_lead_destructive_command_deny(self, hook, tmp_path):
        """tech-lead + rm -rf → deny（command_conventions: tech-lead破壊的コマンド禁止, scope=tech-lead）"""
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
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'tech-leadは破壊的コマンドが禁止されています' in result['reason']

    # --- ケース5: researcher + Bash("git push --force origin main") → deny ---
    def test_researcher_destructive_command_deny(self, hook, tmp_path):
        """researcher + git push --force → deny（command_conventions: researcher破壊的コマンド禁止, scope=researcher）"""
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
        lp, rp = _mock_role(hook, 'researcher')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'researcherは破壊的コマンドが禁止されています' in result['reason']

    # --- ケース6: tester + Edit("src/main.py") → deny ---
    def test_tester_production_code_edit_deny(self, hook, tmp_path):
        """tester + Edit(src/) → deny（file_conventions: testerプロダクションコード編集禁止, scope=tester）"""
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
        lp, rp = _mock_role(hook, 'tester')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'testerはプロダクションコード(src/**)の編集が禁止されています' in result['reason']


class TestAllowedOperations:
    """正常操作確認: deny制約に該当しない操作がブロックされないことを検証"""

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    # --- ケース7: leader + Bash("git status") → gitコマンドは非gitルールにマッチしない ---
    def test_leader_git_command_not_denied(self, hook, tmp_path):
        """leader + Bash(git status) → leaderのgitコマンドはdenyされない"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_E2E_001", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'git status'},
            str(transcript),
        )
        with _mock_leader(hook):
            # scope=Noneのblock/warnルールは閾値チェックで通過済み扱いにする
            with patch.object(hook, 'is_command_processed', return_value=False):
                result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース8: leader + mcp__redmine_epic_grid__get_issue_detail_tool → 許可リスト内 ---
    def test_leader_allowed_mcp_not_denied(self, hook, tmp_path):
        """leader + 許可リスト内Redmine MCP → denyされない"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__redmine_epic_grid__get_issue_detail_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__get_issue_detail_tool',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        # 許可リスト内MCPは否定先読みでマッチしないためapprove
        assert result['decision'] == 'approve'

    # --- ケース9: coder + Edit("src/main.py") → coderにはdenyルールなし ---
    def test_coder_edit_not_denied(self, hook, tmp_path):
        """coder + Edit(src/) → coderに対するdenyルールは存在しない"""
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
        lp, rp = _mock_role(hook, 'coder')
        with lp, rp:
            # scope=Noneのblock/warnルールはis_rule_processed=Trueでスキップ
            with patch.object(hook, 'is_rule_processed', return_value=True):
                result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース10: tester + Edit("tests/test_main.py") → テストコードは対象外 ---
    def test_tester_test_code_edit_not_denied(self, hook, tmp_path):
        """tester + Edit(tests/) → テストコードはtester制約対象外"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/tests/test_main.py'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tester')
        with lp, rp:
            # scope=Noneのblock/warnルールはis_rule_processedでスキップ
            with patch.object(hook, 'is_rule_processed', return_value=True):
                result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース11: tech-lead + Bash("git commit -m 'test'") → 非破壊的コマンド ---
    def test_tech_lead_non_destructive_command_not_denied(self, hook, tmp_path):
        """tech-lead + git commit → 非破壊的gitコマンドはtech-lead制約対象外"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': "git commit -m 'test'"},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            with patch.object(hook, 'is_command_processed', return_value=False):
                result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース12: subagent（role不明）+ Edit → scope=leaderルールは非leaderに適用されない ---
    def test_unknown_subagent_edit_not_denied_by_leader_rule(self, hook, tmp_path):
        """role不明subagent + Edit → scope=leaderルールは適用されない"""
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
        lp, rp = _mock_unknown_subagent(hook)
        with lp, rp:
            # scope=Noneのblock/warnルールはis_rule_processedでスキップ
            with patch.object(hook, 'is_rule_processed', return_value=True):
                result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース13: leader + 許可リスト内MCPツール追加検証 ---
    def test_leader_allowed_mcp_list_status_tool(self, hook, tmp_path):
        """leader + list_statuses_tool → 許可リスト内"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__redmine_epic_grid__list_statuses_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__list_statuses_tool',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        assert result['decision'] == 'approve'


class TestDenyByRoleExtended:
    """#7145追加分: role別deny制約のE2Eテスト"""

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    # --- ケース14: pmo + Edit → deny（pmo全ファイル編集禁止） ---
    def test_pmo_edit_deny(self, hook, tmp_path):
        """pmo + Edit → deny（file_conventions: pmo全ファイル編集禁止, scope=pmo）"""
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
        lp, rp = _mock_role(hook, 'pmo')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'pmoはファイル編集が禁止されています' in result['reason']

    # --- ケース15: tech-lead + Edit → deny（tech-lead全ファイル編集禁止） ---
    def test_tech_lead_edit_deny(self, hook, tmp_path):
        """tech-lead + Edit → deny（file_conventions: tech-lead全ファイル編集禁止, scope=tech-lead）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Edit"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Edit',
            {'file_path': '/workspace/packages/claude-nagger/tests/test_main.py'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'tech-leadはファイル編集が禁止されています' in result['reason']

    # --- ケース16: leader + Serena replace_symbol_body → deny ---
    def test_leader_serena_edit_mcp_deny(self, hook, tmp_path):
        """leader + Serena編集系MCP → deny（mcp_conventions: leaderSerena全般MCP禁止, #7187で拡張）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__serena__replace_symbol_body"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__replace_symbol_body',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはSerena MCPツールの使用が禁止されています' in result['reason']

    # --- ケース17: pmo + Serena insert_after_symbol → deny ---
    def test_pmo_serena_edit_mcp_deny(self, hook, tmp_path):
        """pmo + Serena編集系MCP → deny（mcp_conventions: pmoSerena編集系MCP禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__serena__insert_after_symbol"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__insert_after_symbol',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'pmo')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'pmoはSerena編集系ツールの使用が禁止されています' in result['reason']

    # --- ケース18: tech-lead + Serena rename_symbol → deny ---
    def test_tech_lead_serena_edit_mcp_deny(self, hook, tmp_path):
        """tech-lead + Serena編集系MCP → deny（mcp_conventions: tech-leadSerena編集系MCP禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__serena__rename_symbol"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__rename_symbol',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'tech-leadはSerena編集系ツールの使用が禁止されています' in result['reason']

    # --- ケース19: tech-lead + Redmine create_epic → deny ---
    def test_tech_lead_redmine_non_allowed_mcp_deny(self, hook, tmp_path):
        """tech-lead + 非許可Redmine MCP → deny（mcp_conventions: tech-leadRedmine非許可MCP禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__create_epic_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__create_epic_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'tech-leadはこのRedmineツールの使用が禁止されています' in result['reason']

    # --- ケース20: coder + Redmine create_task → deny ---
    def test_coder_redmine_non_allowed_mcp_deny(self, hook, tmp_path):
        """coder + 非許可Redmine MCP → deny（mcp_conventions: coderRedmine非許可MCP禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__create_task_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__create_task_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'coder')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'coderはこのRedmineツールの使用が禁止されています' in result['reason']

    # --- ケース28: pmo + Bash("npm install") → deny（制約#14 pmo非gitコマンド禁止） ---
    def test_pmo_non_git_command_deny(self, hook, tmp_path):
        """pmo + Bash(npm install) → deny（command_conventions: pmo非gitコマンド禁止, scope=pmo）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'npm install'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'pmo')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'pmoはgitコマンド以外のBash実行が禁止されています' in result['reason']

    # --- ケース29: tech-lead + Bash("python3 -m pytest") → deny（制約#15 tech-lead非gitコマンド禁止） ---
    def test_tech_lead_non_git_command_deny(self, hook, tmp_path):
        """tech-lead + Bash(python3 -m pytest) → deny（command_conventions: tech-lead非gitコマンド禁止, scope=tech-lead）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'python3 -m pytest'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'tech-leadはgitコマンド以外のBash実行が禁止されています' in result['reason']

    # --- ケース30: tester + Redmine create_task → deny（制約#16 testerRedmine非許可MCP禁止） ---
    def test_tester_redmine_non_allowed_mcp_deny(self, hook, tmp_path):
        """tester + 非許可Redmine MCP → deny（mcp_conventions: testerRedmine非許可MCP禁止, scope=tester）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__create_task_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__create_task_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tester')
        with lp, rp:
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'testerはこのRedmineツールの使用が禁止されています' in result['reason']


class TestAllowedOperationsExtended:
    """#7145追加分: deny制約に該当しない操作の検証"""

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    # --- ケース21: leader + Serena参照系(find_symbol) → 非deny ---
    def test_leader_serena_read_not_denied(self, hook, tmp_path):
        """leader + Serena参照系MCP → deny（#7187: leaderはSerena全般禁止に拡張）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__serena__find_symbol"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__find_symbol',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはSerena MCPツールの使用が禁止されています' in result['reason']

    # --- ケース22: tech-lead + Redmine許可リスト内(get_issue_detail) → 非deny ---
    def test_tech_lead_redmine_allowed_mcp_not_denied(self, hook, tmp_path):
        """tech-lead + 許可リスト内Redmine MCP → denyされない"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__get_issue_detail_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__get_issue_detail_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース23: tech-lead + Redmine許可リスト内(add_issue_comment) → 非deny ---
    def test_tech_lead_redmine_comment_allowed(self, hook, tmp_path):
        """tech-lead + add_issue_comment → 許可リスト内"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__add_issue_comment_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__add_issue_comment_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース24: coder + Redmine許可リスト内(get_issue_detail) → 非deny ---
    def test_coder_redmine_detail_allowed(self, hook, tmp_path):
        """coder + get_issue_detail → 許可リスト内"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__get_issue_detail_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__get_issue_detail_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'coder')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース25: coder + Redmine許可リスト内(add_issue_comment) → 非deny ---
    def test_coder_redmine_comment_allowed(self, hook, tmp_path):
        """coder + add_issue_comment → 許可リスト内"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__add_issue_comment_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__add_issue_comment_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'coder')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース26: coder + Serena編集系 → 非deny（coderにはSerena制約なし） ---
    def test_coder_serena_edit_not_denied(self, hook, tmp_path):
        """coder + Serena編集系MCP → coderにはSerena制約なし"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__serena__replace_symbol_body"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__replace_symbol_body',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'coder')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース27: tech-lead + Serena参照系(get_symbols_overview) → 非deny ---
    def test_tech_lead_serena_read_not_denied(self, hook, tmp_path):
        """tech-lead + Serena参照系MCP → 編集系のみ制約対象"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__serena__get_symbols_overview"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__get_symbols_overview',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース31: pmo + Bash("git status") → 非deny（gitコマンドは許可） ---
    def test_pmo_git_command_not_denied(self, hook, tmp_path):
        """pmo + Bash(git status) → gitコマンドはpmo非gitコマンド禁止ルールにマッチしない"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'git status'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'pmo')
        with lp, rp:
            with patch.object(hook, 'is_command_processed', return_value=False):
                result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース32: tech-lead + Bash("git log") → 非deny（gitコマンドは許可） ---
    def test_tech_lead_git_command_not_denied(self, hook, tmp_path):
        """tech-lead + Bash(git log) → gitコマンドはtech-lead非gitコマンド禁止ルールにマッチしない"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": "toolu_OTHER", "name": "Bash"}]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Bash',
            {'command': 'git log'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tech-lead')
        with lp, rp:
            with patch.object(hook, 'is_command_processed', return_value=False):
                result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース33: tester + Redmine get_issue_detail → 非deny（許可リスト内） ---
    def test_tester_redmine_detail_allowed(self, hook, tmp_path):
        """tester + get_issue_detail → testerRedmine許可リスト内"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "mcp__redmine_epic_grid__get_issue_detail_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__get_issue_detail_tool',
            {},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'tester')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)


class TestLeaderBuiltinToolDeny:
    """leader built-inツール制約テスト（#7187: leader/agent責務分離）"""

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    # --- ケース34: leader + WebFetch → deny ---
    def test_leader_webfetch_deny(self, hook, tmp_path):
        """leader + WebFetch → deny（leaderWebFetchWebSearch禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "WebFetch"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'WebFetch',
            {'url': 'https://example.com', 'prompt': 'test'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはWebFetch/WebSearchの使用が禁止されています' in result['reason']

    # --- ケース35: leader + WebSearch → deny ---
    def test_leader_websearch_deny(self, hook, tmp_path):
        """leader + WebSearch → deny（leaderWebFetchWebSearch禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "WebSearch"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'WebSearch',
            {'query': 'test query'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはWebFetch/WebSearchの使用が禁止されています' in result['reason']

    # --- ケース36: leader + Grep → deny ---
    def test_leader_grep_deny(self, hook, tmp_path):
        """leader + Grep → deny（leaderGrep禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "Grep"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Grep',
            {'pattern': 'test'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはGrepの使用が禁止されています' in result['reason']

    # --- ケース37: leader + Glob → deny ---
    def test_leader_glob_not_denied(self, hook, tmp_path):
        """leader + Glob → 非deny（PMO判断: Globはleader許可ツール）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "Glob"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Glob',
            {'pattern': '**/*.py'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース38: leader + Serena参照系MCP → deny ---
    def test_leader_serena_get_symbols_overview_deny(self, hook, tmp_path):
        """leader + Serena get_symbols_overview → deny（leaderSerena全般MCP禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__serena__get_symbols_overview"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__get_symbols_overview',
            {'relative_path': 'src/main.py'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはSerena MCPツールの使用が禁止されています' in result['reason']

    # --- ケース39: leader + Serena search_for_pattern → deny ---
    def test_leader_serena_search_deny(self, hook, tmp_path):
        """leader + Serena search_for_pattern → deny（leaderSerena全般MCP禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__serena__search_for_pattern"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__search_for_pattern',
            {'substring_pattern': 'test'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'leaderはSerena MCPツールの使用が禁止されています' in result['reason']

    # --- ケース40: leader + Serena read_memory → 非deny（許可リスト内） ---
    def test_leader_serena_read_memory_not_denied(self, hook, tmp_path):
        """leader + Serena read_memory → 非deny（leaderSerena許可リスト内）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__serena__read_memory"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__read_memory',
            {'memory_name': 'test'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース41: leader + Serena list_memories → 非deny（許可リスト内） ---
    def test_leader_serena_list_memories_not_denied(self, hook, tmp_path):
        """leader + Serena list_memories → 非deny（leaderSerena許可リスト内）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__serena__list_memories"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__list_memories',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)


class TestStandaloneAgentDeny:
    """スタンドアロンagent禁止テスト（#7187）"""

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    # --- ケース42: leader + Agent(team_name無し) → deny ---
    def test_leader_standalone_agent_deny(self, hook, tmp_path):
        """leader + Agent(team_name未指定) → deny（スタンドアロンAgent禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "Agent"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Agent',
            {'prompt': 'do something', 'subagent_type': 'coder'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'スタンドアロンagent' in result['reason']

    # --- ケース43: leader + Task(team_name無し) → deny ---
    def test_leader_standalone_task_deny(self, hook, tmp_path):
        """leader + Task(team_name未指定) → deny（スタンドアロンAgent禁止）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "Task"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Task',
            {'prompt': 'do something'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_deny(result)
        assert 'スタンドアロンagent' in result['reason']

    # --- ケース44: leader + Agent(team_name有り) → 非deny ---
    def test_leader_team_agent_not_denied(self, hook, tmp_path):
        """leader + Agent(team_name指定あり) → 非deny"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "Agent"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Agent',
            {'prompt': 'do something', 'team_name': 'my-team', 'name': 'coder'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース45: leader + Task(team_name有り) → 非deny ---
    def test_leader_team_task_not_denied(self, hook, tmp_path):
        """leader + Task(team_name指定あり) → 非deny"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "Task"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Task',
            {'prompt': 'do something', 'team_name': 'my-team', 'name': 'coder'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース46: subagent(coder) + Agent(team_name無し) → スタンドアロン禁止はleaderのみ ---
    def test_coder_standalone_agent_not_denied(self, hook, tmp_path):
        """coder + Agent(team_name未指定) → 非deny（scope=leaderのルール、coderには適用されない）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "Agent"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Agent',
            {'prompt': 'do something', 'subagent_type': 'coder'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'coder')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)


class TestBuiltinToolAllowForSubagents:
    """built-inツールがsubagentに対してdenyされないことの確認（回帰テスト）"""

    @pytest.fixture
    def hook(self):
        """実際のYAMLルール（rules/）を読み込むhook"""
        h = ImplementationDesignHook()
        h.matcher = FileConventionMatcher(_RULES_DIR / "file_conventions.yaml")
        h.command_matcher = CommandConventionMatcher(_RULES_DIR / "command_conventions.yaml")
        h.mcp_matcher = McpConventionMatcher(_RULES_DIR)
        return h

    # --- ケース47: coder + WebSearch → 非deny ---
    def test_coder_websearch_not_denied(self, hook, tmp_path):
        """coder + WebSearch → 非deny（leaderのみ制約対象）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "WebSearch"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'WebSearch',
            {'query': 'test'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'coder')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース48: researcher + Grep → 非deny ---
    def test_researcher_grep_not_denied(self, hook, tmp_path):
        """researcher + Grep → 非deny（leaderのみ制約対象）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_OTHER",
                 "name": "Grep"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Grep',
            {'pattern': 'test'},
            str(transcript),
        )
        lp, rp = _mock_role(hook, 'researcher')
        with lp, rp:
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース49: leader + SendMessage → 非deny（制約対象外） ---
    def test_leader_sendmessage_not_denied(self, hook, tmp_path):
        """leader + SendMessage → 非deny（leaderの許可ツール）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "SendMessage"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'SendMessage',
            {'type': 'message', 'recipient': 'coder', 'content': 'test'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース50: leader + Read → 非deny（leader許可ツール） ---
    def test_leader_task_tools_not_denied(self, hook, tmp_path):
        """leader + TaskCreate → 非deny（leader許可ツール）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "TaskCreate"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'TaskCreate',
            {'subject': 'test task', 'description': 'test'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース51: leader + Redmine参照MCP → 非deny（既存の許可リスト） ---
    def test_leader_redmine_allowed_mcp_still_allowed(self, hook, tmp_path):
        """leader + Redmine get_issue_detail → 非deny（既存回帰テスト）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__redmine_epic_grid__get_issue_detail_tool"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__redmine_epic_grid__get_issue_detail_tool',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)

    # --- ケース52: leader + Read → 非deny（leader許可ツール） ---
    # --- ケース52: leader + Read → allow（Readは読み取り専用、file_conventions対象外） ---
    def test_leader_read_not_denied(self, hook, tmp_path):
        """leader + Read → allow（Readは読み取り専用のため、file_conventions対象外）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "Read"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'Read',
            {'file_path': '/tmp/test.py'},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.should_process(input_data)

        # Readは読み取り専用 → should_process=Falseでfile_conventionsスキップ
        assert result is False

    # --- ケース53: leader + Serena initial_instructions → 非deny（許可リスト内） ---
    def test_leader_serena_initial_instructions_not_denied(self, hook, tmp_path):
        """leader + Serena initial_instructions → 非deny（leaderSerena許可リスト内）"""
        transcript = tmp_path / "transcript.jsonl"
        entry = {
            "type": "assistant",
            "message": {"content": [
                {"type": "tool_use", "id": "toolu_E2E_001",
                 "name": "mcp__serena__initial_instructions"}
            ]}
        }
        transcript.write_text(json.dumps(entry) + "\n")

        input_data = _make_input(
            'mcp__serena__initial_instructions',
            {},
            str(transcript),
        )
        with _mock_leader(hook):
            result = hook.process(input_data)

        _assert_not_deny(result)
