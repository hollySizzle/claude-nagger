"""config pathデフォルト解決の統合テスト (#7234)

CLAUDE_PROJECT_DIR環境変数によるパス解決、.claude-nagger/優先、
rules/フォールバックの3パターンをFileConventionMatcher,
CommandConventionMatcher, McpConventionMatcherで検証。
"""

import os
import json
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from domain.services.file_convention_matcher import FileConventionMatcher
from domain.services.command_convention_matcher import CommandConventionMatcher
from domain.services.mcp_convention_matcher import McpConventionMatcher


# --- テスト用YAMLデータ ---

_FILE_RULE = {
    'rules': [{
        'name': 'test-file-rule',
        'patterns': ['*.test'],
        'severity': 'warn',
        'message': 'test file rule'
    }]
}

_COMMAND_RULE = {
    'rules': [{
        'name': 'test-command-rule',
        'patterns': ['test-cmd*'],
        'severity': 'warn',
        'message': 'test command rule'
    }]
}

_MCP_RULE = {
    'rules': [{
        'name': 'test-mcp-rule',
        'tool_pattern': 'TestTool',
        'severity': 'warn',
        'message': 'test mcp rule'
    }]
}

_CUSTOM_FILE_RULE = {
    'rules': [{
        'name': 'custom-file-rule',
        'patterns': ['*.custom'],
        'severity': 'block',
        'message': 'custom file rule'
    }]
}

_CUSTOM_COMMAND_RULE = {
    'rules': [{
        'name': 'custom-command-rule',
        'patterns': ['custom-cmd*'],
        'severity': 'block',
        'message': 'custom command rule'
    }]
}

_CUSTOM_MCP_RULE = {
    'rules': [{
        'name': 'custom-mcp-rule',
        'tool_pattern': 'CustomTool',
        'severity': 'block',
        'message': 'custom mcp rule'
    }]
}


def _write_yaml(path: Path, data: dict):
    """YAMLファイル書き込みヘルパー"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.dump(data, f)


class TestDefaultPathResolution:
    """CLAUDE_PROJECT_DIR設定時のデフォルトパス解決テスト"""

    def test_file_matcher_default_path(self, tmp_path):
        """FileConventionMatcherがrules/フォールバックでルール読み込み"""
        rules_dir = tmp_path / "rules"
        rules_dir.mkdir()
        _write_yaml(rules_dir / "file_conventions.yaml", _FILE_RULE)

        # CLAUDE_PROJECT_DIRを設定、.claude-nagger/不在→rules/フォールバック
        # パッケージ内デフォルトパスをtmp_pathに差し替え
        fake_pkg_rules = tmp_path / "rules" / "file_conventions.yaml"
        with patch.object(Path, '__new__', wraps=Path.__new__):
            with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
                matcher = FileConventionMatcher()

        # CLAUDE_PROJECT_DIR配下に.claude-nagger/がないため
        # __file__ベースのrules/を使用（テスト環境ではプロジェクトルールが読まれる）
        # ルールが正常にロードされることを確認
        assert len(matcher.rules) > 0

    def test_command_matcher_default_path(self, tmp_path):
        """CommandConventionMatcherがrules/フォールバックでルール読み込み"""
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = CommandConventionMatcher()

        # .claude-nagger/不在→パッケージ内rules/フォールバック
        assert len(matcher.rules) > 0

    def test_mcp_matcher_default_path(self, tmp_path):
        """McpConventionMatcherがrules/フォールバックでルール読み込み"""
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = McpConventionMatcher()

        # .claude-nagger/不在→パッケージ内rules/フォールバック
        assert len(matcher.rules) > 0


class TestClaudeNaggerPriority:
    """.claude-nagger/ディレクトリ優先テスト"""

    def test_file_matcher_claude_nagger_priority(self, tmp_path):
        """.claude-nagger/file_conventions.yaml存在時に優先適用"""
        # .claude-nagger/にカスタムルール配置
        _write_yaml(tmp_path / ".claude-nagger" / "file_conventions.yaml", _CUSTOM_FILE_RULE)

        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = FileConventionMatcher()

        assert len(matcher.rules) == 1
        assert matcher.rules[0].name == 'custom-file-rule'
        assert matcher.rules[0].severity == 'block'

    def test_command_matcher_claude_nagger_priority(self, tmp_path):
        """.claude-nagger/command_conventions.yaml存在時に優先適用"""
        _write_yaml(tmp_path / ".claude-nagger" / "command_conventions.yaml", _CUSTOM_COMMAND_RULE)

        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = CommandConventionMatcher()

        assert len(matcher.rules) == 1
        assert matcher.rules[0].name == 'custom-command-rule'
        assert matcher.rules[0].severity == 'block'

    def test_mcp_matcher_claude_nagger_priority(self, tmp_path):
        """.claude-nagger/mcp_conventions.yaml存在時に優先適用"""
        _write_yaml(tmp_path / ".claude-nagger" / "mcp_conventions.yaml", _CUSTOM_MCP_RULE)

        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = McpConventionMatcher()

        assert len(matcher.rules) == 1
        assert matcher.rules[0].name == 'custom-mcp-rule'
        assert matcher.rules[0].severity == 'block'


class TestFallbackPath:
    """.claude-nagger/不在時のrules/フォールバックテスト"""

    def test_file_matcher_fallback_to_package_rules(self, tmp_path):
        """.claude-nagger/不在時にパッケージ内rules/へフォールバック"""
        # tmp_pathに.claude-nagger/を作成しない
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = FileConventionMatcher()

        # パッケージ内rules/file_conventions.yamlのルールがロードされる
        assert matcher.rules_file.name == "file_conventions.yaml"
        assert "rules" in str(matcher.rules_file)
        assert len(matcher.rules) > 0

    def test_command_matcher_fallback_to_package_rules(self, tmp_path):
        """.claude-nagger/不在時にパッケージ内rules/へフォールバック"""
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = CommandConventionMatcher()

        assert matcher.rules_file.name == "command_conventions.yaml"
        assert "rules" in str(matcher.rules_file)
        assert len(matcher.rules) > 0

    def test_mcp_matcher_fallback_to_package_rules(self, tmp_path):
        """.claude-nagger/不在時にパッケージ内rules/へフォールバック"""
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = McpConventionMatcher()

        assert matcher.rules_file.name == "mcp_conventions.yaml"
        assert "rules" in str(matcher.rules_file)
        assert len(matcher.rules) > 0

    def test_fallback_does_not_use_claude_nagger_dir(self, tmp_path):
        """フォールバック時に.claude-nagger/パスを使用しない"""
        with patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            matcher = FileConventionMatcher()

        assert ".claude-nagger" not in str(matcher.rules_file)
