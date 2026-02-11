"""LeaderConstraintHook テスト

subagentアクティブ時のleader直接作業ブロックフックの検証。
テスト規約: docs/rules/claude_code_hook_testing.yaml 準拠
"""

import pytest
from unittest.mock import patch, MagicMock

from src.domain.hooks.leader_constraint_hook import LeaderConstraintHook


@pytest.fixture
def hook():
    """テスト用フックインスタンス（デフォルト設定）"""
    with patch(
        "src.domain.hooks.leader_constraint_hook.ConfigManager"
    ) as mock_cm:
        mock_cm.return_value.config = {}
        h = LeaderConstraintHook(debug=False)
    return h


@pytest.fixture
def hook_disabled():
    """テスト用フックインスタンス（無効化設定）"""
    with patch(
        "src.domain.hooks.leader_constraint_hook.ConfigManager"
    ) as mock_cm:
        mock_cm.return_value.config = {
            "leader_constraint": {"enabled": False}
        }
        h = LeaderConstraintHook(debug=False)
    return h


def _make_input(tool_name: str, tool_input: dict, session_id: str = "test-session-001", cwd: str = "/workspace/project") -> dict:
    """テスト用入力データ生成ヘルパー"""
    return {
        "tool_name": tool_name,
        "tool_input": tool_input,
        "session_id": session_id,
        "cwd": cwd,
    }


class TestIsTargetTool:
    """ブロック対象ツール判定テスト"""

    def test_read_is_target(self, hook):
        assert hook.is_target_tool("Read") is True

    def test_edit_is_target(self, hook):
        assert hook.is_target_tool("Edit") is True

    def test_write_is_target(self, hook):
        assert hook.is_target_tool("Write") is True

    def test_grep_is_target(self, hook):
        assert hook.is_target_tool("Grep") is True

    def test_glob_is_target(self, hook):
        assert hook.is_target_tool("Glob") is True

    def test_bash_is_not_target(self, hook):
        assert hook.is_target_tool("Bash") is False

    def test_sendmessage_is_not_target(self, hook):
        assert hook.is_target_tool("SendMessage") is False

    def test_task_is_not_target(self, hook):
        assert hook.is_target_tool("Task") is False


class TestIsSourcePath:
    """ソースコードパス判定テスト"""

    def test_src_relative(self, hook):
        assert hook.is_source_path("src/domain/hooks/base_hook.py") is True

    def test_tests_relative(self, hook):
        assert hook.is_source_path("tests/test_foo.py") is True

    def test_docs_not_source(self, hook):
        assert hook.is_source_path("docs/README.md") is False

    def test_config_not_source(self, hook):
        assert hook.is_source_path("config.yaml") is False

    def test_src_absolute(self, hook):
        """絶対パスでsrc/内のファイル"""
        assert hook.is_source_path(
            "/workspace/project/src/app.py",
            cwd="/workspace/project"
        ) is True

    def test_tests_absolute(self, hook):
        """絶対パスでtests/内のファイル"""
        assert hook.is_source_path(
            "/workspace/project/tests/test_app.py",
            cwd="/workspace/project"
        ) is True

    def test_outside_cwd(self, hook):
        """cwd外の絶対パスは対象外"""
        assert hook.is_source_path(
            "/other/project/src/app.py",
            cwd="/workspace/project"
        ) is False


class TestIsExemptPath:
    """免除パス判定テスト"""

    def test_config_yaml_exempt(self, hook):
        """config.yaml は免除"""
        assert hook.is_exempt_path("config.yaml") is True

    def test_settings_json_exempt(self, hook):
        """settings.json は免除"""
        assert hook.is_exempt_path("settings.json") is True

    def test_docs_dir_exempt(self, hook):
        """docs/ ディレクトリは免除"""
        assert hook.is_exempt_path("docs/README.md") is True

    def test_claude_dir_exempt(self, hook):
        """.claude/ ディレクトリは免除"""
        assert hook.is_exempt_path(".claude/settings.json") is True

    def test_md_glob_exempt(self, hook):
        """*.md パターンは免除"""
        assert hook.is_exempt_path("src/README.md") is True

    def test_md_in_tests_exempt(self, hook):
        """tests/内の.mdファイルも免除"""
        assert hook.is_exempt_path("tests/NOTES.md") is True

    def test_py_not_exempt(self, hook):
        """通常の.pyファイルは免除されない"""
        assert hook.is_exempt_path("src/domain/hooks/base_hook.py") is False

    def test_absolute_docs(self, hook):
        """絶対パスのdocs/も免除"""
        assert hook.is_exempt_path(
            "/workspace/project/docs/api.md",
            cwd="/workspace/project"
        ) is True

    def test_absolute_config_yaml(self, hook):
        """絶対パスのconfig.yamlも免除"""
        assert hook.is_exempt_path(
            "/workspace/project/config.yaml",
            cwd="/workspace/project"
        ) is True


class TestShouldProcess:
    """should_process 統合判定テスト"""

    def _patch_subagents(self, active: bool):
        """subagentアクティブ状態をモック"""
        return patch.object(
            LeaderConstraintHook, "has_active_subagents", return_value=active
        )

    def test_block_src_read_with_active_subagent(self, hook):
        """subagentアクティブ時にsrc/内Readでブロック"""
        input_data = _make_input("Read", {"file_path": "src/app.py"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is True

    def test_exempt_config_yaml_read_with_active_subagent(self, hook):
        """subagentアクティブ時にconfig.yaml Readで免除"""
        input_data = _make_input("Read", {"file_path": "config.yaml"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is False

    def test_exempt_docs_read_with_active_subagent(self, hook):
        """subagentアクティブ時にdocs/内Readで免除"""
        input_data = _make_input("Read", {"file_path": "docs/api.md"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is False

    def test_allow_src_read_without_subagent(self, hook):
        """subagentなし時にsrc/内Readで免除"""
        input_data = _make_input("Read", {"file_path": "src/app.py"})
        with self._patch_subagents(False):
            assert hook.should_process(input_data) is False

    def test_block_edit_with_active_subagent(self, hook):
        """subagentアクティブ時にsrc/内Editでブロック"""
        input_data = _make_input("Edit", {"file_path": "src/domain/hooks/base_hook.py"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is True

    def test_block_write_with_active_subagent(self, hook):
        """subagentアクティブ時にsrc/内Writeでブロック"""
        input_data = _make_input("Write", {"file_path": "src/new_file.py"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is True

    def test_block_grep_with_active_subagent(self, hook):
        """subagentアクティブ時にsrc/内Grepでブロック"""
        input_data = _make_input("Grep", {"path": "src/", "pattern": "def foo"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is True

    def test_block_glob_with_active_subagent(self, hook):
        """subagentアクティブ時にtests/内Globでブロック"""
        input_data = _make_input("Glob", {"path": "tests/", "pattern": "*.py"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is True

    def test_disabled_config_allows_all(self, hook_disabled):
        """leader_constraint.enabled=falseで全免除"""
        input_data = _make_input("Read", {"file_path": "src/app.py"})
        with self._patch_subagents(True):
            assert hook_disabled.should_process(input_data) is False

    def test_md_pattern_exempt(self, hook):
        """*.mdパターンの免除確認"""
        input_data = _make_input("Read", {"file_path": "src/README.md"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is False

    def test_non_target_tool_skipped(self, hook):
        """ブロック対象外ツール（Bash）はスキップ"""
        input_data = _make_input("Bash", {"command": "ls"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is False

    def test_no_session_id_skipped(self, hook):
        """session_idなしはスキップ"""
        input_data = _make_input("Read", {"file_path": "src/app.py"}, session_id="")
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is False

    def test_absolute_path_src_blocked(self, hook):
        """絶対パスのsrc/内ファイルもブロック"""
        input_data = _make_input(
            "Read",
            {"file_path": "/workspace/project/src/app.py"},
            cwd="/workspace/project",
        )
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is True

    def test_grep_no_path_blocked(self, hook):
        """Grepでpath未指定（全体検索）はブロック"""
        input_data = _make_input("Grep", {"pattern": "def foo"})
        with self._patch_subagents(True):
            assert hook.should_process(input_data) is True


class TestProcess:
    """process メソッドのテスト"""

    def test_block_decision(self, hook):
        """ブロック時にdecision=blockを返す"""
        input_data = _make_input("Read", {"file_path": "src/app.py"})
        result = hook.process(input_data)
        assert result["decision"] == "block"

    def test_block_message_content(self, hook):
        """ブロックメッセージに委譲先情報が含まれる"""
        input_data = _make_input("Read", {"file_path": "src/app.py"})
        result = hook.process(input_data)
        assert "subagent" in result["reason"]
        assert "researcher" in result["reason"]
        assert "coder" in result["reason"]
        assert "tester" in result["reason"]


class TestExtractPath:
    """パス抽出ロジックのテスト"""

    def test_file_path_key(self, hook):
        """file_pathキーから抽出"""
        path = hook._extract_path("Read", {"file_path": "src/app.py"})
        assert path == "src/app.py"

    def test_path_key(self, hook):
        """pathキーから抽出（Grep/Glob用）"""
        path = hook._extract_path("Grep", {"path": "src/", "pattern": "foo"})
        assert path == "src/"

    def test_no_path(self, hook):
        """パスなしの場合None"""
        path = hook._extract_path("Grep", {"pattern": "foo"})
        assert path is None
