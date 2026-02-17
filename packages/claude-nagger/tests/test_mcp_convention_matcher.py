"""McpConventionMatcherのテスト"""

import pytest
from pathlib import Path
import tempfile
import yaml
from src.domain.services.mcp_convention_matcher import (
    McpConventionMatcher,
    McpConventionRule
)


class TestMcpConventionMatcherInit:
    """初期化のテスト"""

    def _create_config_dir(self):
        """テスト用の設定ディレクトリとmcp_conventions.yamlを作成"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        rules_data = {
            'rules': [
                {
                    'name': 'Redmine更新確認',
                    'tool_pattern': 'mcp__redmine_epic_grid__update.*',
                    'severity': 'block',
                    'message': 'Redmine更新操作を確認してください'
                },
                {
                    'name': 'ファイル書込確認',
                    'tool_pattern': 'mcp__filesystem__write.*',
                    'severity': 'warn',
                    'message': 'ファイル書込前に確認してください',
                    'token_threshold': 50000
                }
            ]
        }
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(rules_data, f)
        return Path(tmpdir), path

    def test_init_with_explicit_config_dir(self):
        """明示的な設定ディレクトリで初期化"""
        config_dir, path = self._create_config_dir()
        try:
            matcher = McpConventionMatcher(config_dir=config_dir)
            assert matcher.rules_file == path
            assert len(matcher.rules) == 2
        finally:
            path.unlink(missing_ok=True)

    def test_init_with_debug_flag(self):
        """デバッグフラグ付きで初期化"""
        config_dir, path = self._create_config_dir()
        try:
            matcher = McpConventionMatcher(config_dir=config_dir, debug=True)
            assert matcher.debug is True
        finally:
            path.unlink(missing_ok=True)

    def test_init_nonexistent_dir(self):
        """存在しないディレクトリで初期化"""
        matcher = McpConventionMatcher(config_dir=Path('/nonexistent/dir'))
        assert len(matcher.rules) == 0


class TestLoadRules:
    """ルール読み込みのテスト"""

    def _create_temp_yaml(self, data):
        """一時YAMLファイルを作成してパスを返すヘルパー"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f)
        return Path(tmpdir), path

    def test_load_rules_success(self):
        """ルールファイルの正常読み込み"""
        config_dir, path = self._create_temp_yaml({
            'rules': [
                {
                    'name': 'Test Rule',
                    'tool_pattern': 'mcp__test__.*',
                    'severity': 'warn',
                    'message': 'Test message',
                    'token_threshold': 30000
                }
            ]
        })

        try:
            matcher = McpConventionMatcher(config_dir=config_dir)
            assert len(matcher.rules) == 1
            rule = matcher.rules[0]
            assert rule.name == 'Test Rule'
            assert rule.tool_pattern == 'mcp__test__.*'
            assert rule.severity == 'warn'
            assert rule.message == 'Test message'
            assert rule.token_threshold == 30000
        finally:
            path.unlink()

    def test_load_rules_default_severity(self):
        """severity省略時のデフォルト値"""
        config_dir, path = self._create_temp_yaml({
            'rules': [
                {
                    'name': 'No Severity Rule',
                    'tool_pattern': 'mcp__.*',
                    'message': 'Message without severity'
                }
            ]
        })

        try:
            matcher = McpConventionMatcher(config_dir=config_dir)
            assert matcher.rules[0].severity == 'warn'
        finally:
            path.unlink()

    def test_load_rules_empty_rules(self):
        """空のルールリスト"""
        config_dir, path = self._create_temp_yaml({'rules': []})

        try:
            matcher = McpConventionMatcher(config_dir=config_dir)
            assert len(matcher.rules) == 0
        finally:
            path.unlink()

    def test_load_rules_empty_file(self):
        """空のYAMLファイル（rulesキーなし）"""
        config_dir, path = self._create_temp_yaml({})

        try:
            matcher = McpConventionMatcher(config_dir=config_dir)
            assert len(matcher.rules) == 0
        finally:
            path.unlink()

    def test_load_rules_yaml_error(self):
        """YAML構文エラー"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        with open(path, 'w') as f:
            f.write("invalid: yaml: content:\n  - broken")

        try:
            matcher = McpConventionMatcher(config_dir=Path(tmpdir))
            assert len(matcher.rules) == 0
        finally:
            path.unlink()

    def test_load_rules_missing_required_field(self):
        """必須フィールド欠落"""
        config_dir, path = self._create_temp_yaml({
            'rules': [
                {
                    'name': 'Missing tool_pattern',
                    'message': 'No tool_pattern field'
                }
            ]
        })

        try:
            matcher = McpConventionMatcher(config_dir=config_dir)
            assert len(matcher.rules) == 0
        finally:
            path.unlink()

    def test_load_rules_invalid_regex_skipped(self):
        """無効な正規表現パターンはスキップされる"""
        config_dir, path = self._create_temp_yaml({
            'rules': [
                {
                    'name': 'Invalid Regex',
                    'tool_pattern': '[invalid regex',
                    'severity': 'warn',
                    'message': 'Bad regex rule'
                },
                {
                    'name': 'Valid Rule',
                    'tool_pattern': 'mcp__valid__.*',
                    'severity': 'warn',
                    'message': 'Valid rule'
                }
            ]
        })

        try:
            matcher = McpConventionMatcher(config_dir=config_dir)
            # 無効なregexルールはスキップ、有効なルールのみロード
            assert len(matcher.rules) == 1
            assert matcher.rules[0].name == 'Valid Rule'
        finally:
            path.unlink()


class TestMatchesPattern:
    """パターンマッチングのテスト"""

    @pytest.fixture
    def matcher(self):
        """テスト用マッチャーを作成（空ルール）"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        with open(path, 'w') as f:
            yaml.dump({'rules': []}, f)

        m = McpConventionMatcher(config_dir=Path(tmpdir))
        path.unlink()
        return m

    def test_exact_match(self, matcher):
        """完全一致パターン"""
        assert matcher.matches_pattern('mcp__redmine__update', ['mcp__redmine__update'])

    def test_regex_prefix_match(self, matcher):
        """re.matchによるプレフィックスマッチ"""
        # re.matchは先頭からマッチするため、末尾.*で部分マッチ
        assert matcher.matches_pattern('mcp__redmine__update_issue', ['mcp__redmine__update.*'])

    def test_regex_no_match(self, matcher):
        """マッチしない場合"""
        assert not matcher.matches_pattern('mcp__github__create_pr', ['mcp__redmine__.*'])

    def test_multiple_patterns(self, matcher):
        """複数パターン（List[str]対応）"""
        patterns = ['mcp__redmine__.*', 'mcp__github__.*']
        assert matcher.matches_pattern('mcp__redmine__update', patterns)
        assert matcher.matches_pattern('mcp__github__create_pr', patterns)
        assert not matcher.matches_pattern('mcp__slack__send', patterns)

    def test_regex_character_class(self, matcher):
        """正規表現の文字クラス"""
        assert matcher.matches_pattern('mcp__tool__action1', ['mcp__tool__action[0-9]'])
        assert not matcher.matches_pattern('mcp__tool__actionX', ['mcp__tool__action[0-9]'])

    def test_invalid_regex_returns_false(self, matcher):
        """無効な正規表現はFalseを返す"""
        result = matcher.matches_pattern('mcp__test__tool', ['[invalid'])
        assert result is False

    def test_partial_match_with_re_match(self, matcher):
        """re.matchは先頭からのマッチ（途中マッチはしない確認）"""
        # re.matchは先頭からマッチするため、先頭一致しないパターンはFalse
        assert not matcher.matches_pattern('some_prefix_mcp__test', ['mcp__test'])


class TestCheckTool:
    """check_toolメソッドのテスト"""

    def _create_matcher(self, rules_data):
        """ルール付きマッチャーを作成するヘルパー"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(rules_data, f)
        return McpConventionMatcher(config_dir=Path(tmpdir)), path

    def test_check_tool_single_match(self):
        """単一ルールにマッチ"""
        matcher, path = self._create_matcher({
            'rules': [
                {
                    'name': 'Redmine更新',
                    'tool_pattern': 'mcp__redmine.*update.*',
                    'severity': 'block',
                    'message': 'Redmine更新確認'
                },
                {
                    'name': 'GitHub PR',
                    'tool_pattern': 'mcp__github__create_pr',
                    'severity': 'warn',
                    'message': 'PR作成確認'
                }
            ]
        })

        try:
            rules = matcher.check_tool('mcp__redmine__update_issue')
            assert len(rules) == 1
            assert rules[0].name == 'Redmine更新'
            assert rules[0].severity == 'block'
        finally:
            path.unlink()

    def test_check_tool_multiple_match(self):
        """複数ルールにマッチ"""
        matcher, path = self._create_matcher({
            'rules': [
                {
                    'name': 'Redmine全般',
                    'tool_pattern': 'mcp__redmine.*',
                    'severity': 'info',
                    'message': 'Redmine操作'
                },
                {
                    'name': 'Redmine更新',
                    'tool_pattern': 'mcp__redmine.*update.*',
                    'severity': 'block',
                    'message': 'Redmine更新確認'
                }
            ]
        })

        try:
            rules = matcher.check_tool('mcp__redmine__update_issue')
            assert len(rules) == 2
            assert rules[0].name == 'Redmine全般'
            assert rules[1].name == 'Redmine更新'
        finally:
            path.unlink()

    def test_check_tool_no_match(self):
        """マッチなし"""
        matcher, path = self._create_matcher({
            'rules': [
                {
                    'name': 'Redmine更新',
                    'tool_pattern': 'mcp__redmine.*update.*',
                    'severity': 'block',
                    'message': 'Redmine更新確認'
                }
            ]
        })

        try:
            rules = matcher.check_tool('mcp__github__create_pr')
            assert rules == []
        finally:
            path.unlink()


class TestGetConfirmationMessage:
    """get_confirmation_messageメソッドのテスト"""

    def _create_matcher(self, rules_data):
        """ルール付きマッチャーを作成するヘルパー"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(rules_data, f)
        return McpConventionMatcher(config_dir=Path(tmpdir)), path

    def test_get_confirmation_message_match(self):
        """確認メッセージ生成（マッチ）"""
        matcher, path = self._create_matcher({
            'rules': [
                {
                    'name': 'Test規約',
                    'tool_pattern': 'mcp__test__.*',
                    'severity': 'block',
                    'message': 'テスト確認メッセージ',
                    'token_threshold': 25000
                }
            ]
        })

        try:
            results = matcher.get_confirmation_message('mcp__test__action')
            assert len(results) == 1
            result = results[0]
            assert result['rule_name'] == 'Test規約'
            assert result['severity'] == 'block'
            assert result['tool_name'] == 'mcp__test__action'
            assert result['token_threshold'] == 25000
            assert result['message'] == 'テスト確認メッセージ'
        finally:
            path.unlink()

    def test_get_confirmation_message_no_match(self):
        """確認メッセージ生成（マッチなし）"""
        matcher, path = self._create_matcher({
            'rules': [
                {
                    'name': 'Test規約',
                    'tool_pattern': 'mcp__test__.*',
                    'severity': 'block',
                    'message': 'テスト確認メッセージ'
                }
            ]
        })

        try:
            results = matcher.get_confirmation_message('mcp__unrelated__tool')
            assert results == []
        finally:
            path.unlink()

    def test_get_confirmation_message_severity_types(self):
        """severity別の確認メッセージ"""
        matcher, path = self._create_matcher({
            'rules': [
                {
                    'name': 'Block規約',
                    'tool_pattern': 'mcp__block__.*',
                    'severity': 'block',
                    'message': 'ブロックメッセージ'
                },
                {
                    'name': 'Warn規約',
                    'tool_pattern': 'mcp__warn__.*',
                    'severity': 'warn',
                    'message': '警告メッセージ'
                },
                {
                    'name': 'Info規約',
                    'tool_pattern': 'mcp__info__.*',
                    'severity': 'info',
                    'message': '情報メッセージ'
                }
            ]
        })

        try:
            block_results = matcher.get_confirmation_message('mcp__block__action')
            assert block_results[0]['severity'] == 'block'

            warn_results = matcher.get_confirmation_message('mcp__warn__action')
            assert warn_results[0]['severity'] == 'warn'

            info_results = matcher.get_confirmation_message('mcp__info__action')
            assert info_results[0]['severity'] == 'info'
        finally:
            path.unlink()

    def test_get_confirmation_message_null_threshold(self):
        """token_thresholdがnullの場合"""
        matcher, path = self._create_matcher({
            'rules': [
                {
                    'name': 'No Threshold',
                    'tool_pattern': 'mcp__test__.*',
                    'severity': 'warn',
                    'message': 'Test',
                    'token_threshold': None
                }
            ]
        })

        try:
            results = matcher.get_confirmation_message('mcp__test__action')
            assert results[0]['token_threshold'] is None
        finally:
            path.unlink()


class TestReloadRules:
    """reload_rulesメソッドのテスト"""

    def test_reload_rules(self):
        """ルールのリロード"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump({
                'rules': [
                    {
                        'name': 'Original Rule',
                        'tool_pattern': 'mcp__original__.*',
                        'severity': 'warn',
                        'message': 'Original message'
                    }
                ]
            }, f)

        try:
            matcher = McpConventionMatcher(config_dir=Path(tmpdir))
            assert len(matcher.rules) == 1
            assert matcher.rules[0].name == 'Original Rule'

            # ファイルを更新
            with open(path, 'w', encoding='utf-8') as f:
                yaml.dump({
                    'rules': [
                        {
                            'name': 'Updated Rule',
                            'tool_pattern': 'mcp__updated__.*',
                            'severity': 'block',
                            'message': 'Updated message'
                        },
                        {
                            'name': 'Another Rule',
                            'tool_pattern': 'mcp__another__.*',
                            'severity': 'warn',
                            'message': 'Another message'
                        }
                    ]
                }, f)

            # リロード
            matcher.reload_rules()

            assert len(matcher.rules) == 2
            assert matcher.rules[0].name == 'Updated Rule'
            assert matcher.rules[1].name == 'Another Rule'
        finally:
            path.unlink()


class TestListRules:
    """list_rulesメソッドのテスト"""

    def test_list_rules(self):
        """ルール一覧取得"""
        tmpdir = tempfile.mkdtemp()
        path = Path(tmpdir) / 'mcp_conventions.yaml'
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump({
                'rules': [
                    {
                        'name': 'Rule A',
                        'tool_pattern': 'mcp__a__.*',
                        'severity': 'block',
                        'message': 'Message A'
                    },
                    {
                        'name': 'Rule B',
                        'tool_pattern': 'mcp__b__.*',
                        'severity': 'warn',
                        'message': 'Message B'
                    }
                ]
            }, f)

        try:
            matcher = McpConventionMatcher(config_dir=Path(tmpdir))
            rules = matcher.list_rules()

            assert len(rules) == 2
            assert rules[0].name == 'Rule A'
            assert rules[0].tool_pattern == 'mcp__a__.*'
            assert rules[1].name == 'Rule B'
        finally:
            path.unlink()

    def test_list_rules_empty(self):
        """ルールが空の場合"""
        matcher = McpConventionMatcher(config_dir=Path('/nonexistent/dir'))
        rules = matcher.list_rules()
        assert rules == []


class TestMcpConventionRule:
    """McpConventionRuleデータクラスのテスト"""

    def test_rule_creation(self):
        """ルール作成"""
        rule = McpConventionRule(
            name='Test',
            tool_pattern='mcp__test__.*',
            severity='block',
            message='Test message',
            token_threshold=10000
        )
        assert rule.name == 'Test'
        assert rule.tool_pattern == 'mcp__test__.*'
        assert rule.severity == 'block'
        assert rule.message == 'Test message'
        assert rule.token_threshold == 10000

    def test_rule_default_threshold(self):
        """token_thresholdのデフォルト値"""
        rule = McpConventionRule(
            name='Test',
            tool_pattern='mcp__test__.*',
            severity='warn',
            message='Test message'
        )
        assert rule.token_threshold is None
