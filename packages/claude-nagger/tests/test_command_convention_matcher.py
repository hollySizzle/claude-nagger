"""CommandConventionMatcherのテスト"""

import pytest
from pathlib import Path
import tempfile
import yaml
from src.domain.services.command_convention_matcher import (
    CommandConventionMatcher,
    ConventionRule
)


class TestCommandConventionMatcherInit:
    """初期化のテスト"""

    @pytest.fixture
    def temp_rules_file(self):
        """テスト用の一時ルールファイルを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Git Push規約',
                        'patterns': ['git push*'],
                        'severity': 'block',
                        'message': 'プッシュ前にテストを実行してください'
                    },
                    {
                        'name': 'Deploy規約',
                        'patterns': ['*deploy*', '*production*'],
                        'severity': 'warn',
                        'message': 'デプロイ前に確認してください',
                        'token_threshold': 50000
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        yield temp_path
        temp_path.unlink()

    def test_init_with_explicit_rules_file(self, temp_rules_file):
        """明示的なルールファイルで初期化"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)
        assert matcher.rules_file == temp_rules_file
        assert len(matcher.rules) == 2

    def test_init_with_debug_flag(self, temp_rules_file):
        """デバッグフラグ付きで初期化"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file, debug=True)
        assert matcher.debug is True

    def test_init_nonexistent_file(self):
        """存在しないファイルで初期化"""
        matcher = CommandConventionMatcher(rules_file=Path('/nonexistent/file.yaml'))
        assert len(matcher.rules) == 0


class TestLoadRules:
    """ルール読み込みのテスト"""

    @pytest.fixture
    def temp_rules_file(self):
        """テスト用の一時ルールファイルを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Test Rule',
                        'patterns': ['test*'],
                        'severity': 'warn',
                        'message': 'Test message',
                        'token_threshold': 30000
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        yield temp_path
        temp_path.unlink()

    def test_load_rules_success(self, temp_rules_file):
        """ルールファイルの正常読み込み"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)

        assert len(matcher.rules) == 1
        rule = matcher.rules[0]
        assert rule.name == 'Test Rule'
        assert rule.patterns == ['test*']
        assert rule.severity == 'warn'
        assert rule.message == 'Test message'
        assert rule.token_threshold == 30000

    def test_load_rules_default_severity(self):
        """severity省略時のデフォルト値"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'No Severity Rule',
                        'patterns': ['cmd*'],
                        'message': 'Message without severity'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        try:
            matcher = CommandConventionMatcher(rules_file=temp_path)
            assert matcher.rules[0].severity == 'warn'
        finally:
            temp_path.unlink()

    def test_load_rules_yaml_error(self):
        """YAML構文エラー"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content:\n  - broken")
            temp_path = Path(f.name)

        try:
            matcher = CommandConventionMatcher(rules_file=temp_path)
            assert len(matcher.rules) == 0
        finally:
            temp_path.unlink()

    def test_load_rules_missing_required_field(self):
        """必須フィールド欠落"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Missing patterns',
                        'message': 'No patterns field'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        try:
            matcher = CommandConventionMatcher(rules_file=temp_path)
            assert len(matcher.rules) == 0
        finally:
            temp_path.unlink()

    def test_load_rules_empty_file(self):
        """空のルールファイル"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({}, f)
            temp_path = Path(f.name)

        try:
            matcher = CommandConventionMatcher(rules_file=temp_path)
            assert len(matcher.rules) == 0
        finally:
            temp_path.unlink()


class TestMatchesPattern:
    """パターンマッチングのテスト"""

    @pytest.fixture
    def matcher(self):
        """テスト用マッチャーを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {'rules': []}
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        m = CommandConventionMatcher(rules_file=temp_path)
        temp_path.unlink()
        return m

    def test_exact_match(self, matcher):
        """完全一致パターン"""
        assert matcher.matches_pattern('git push', ['git push'])
        assert not matcher.matches_pattern('git pull', ['git push'])

    def test_wildcard_suffix(self, matcher):
        """末尾ワイルドカード"""
        assert matcher.matches_pattern('git push origin main', ['git push*'])
        assert matcher.matches_pattern('git push', ['git push*'])
        assert not matcher.matches_pattern('git pull', ['git push*'])

    def test_wildcard_prefix(self, matcher):
        """先頭ワイルドカード"""
        assert matcher.matches_pattern('npm run deploy', ['*deploy*'])
        assert matcher.matches_pattern('deploy-prod', ['*deploy*'])
        assert not matcher.matches_pattern('npm run test', ['*deploy*'])

    def test_command_prefix_match(self, matcher):
        """コマンドプレフィックスマッチ"""
        assert matcher.matches_pattern('git push origin main', ['git'])
        assert matcher.matches_pattern('npm install express', ['npm'])

    def test_multiple_patterns(self, matcher):
        """複数パターン"""
        patterns = ['git push*', 'git commit*']
        assert matcher.matches_pattern('git push origin', patterns)
        assert matcher.matches_pattern('git commit -m "msg"', patterns)
        assert not matcher.matches_pattern('git pull', patterns)

    def test_normalized_command(self, matcher):
        """コマンドの正規化（余分な空白除去）"""
        assert matcher.matches_pattern('git   push   origin', ['git push*'])

    def test_no_match(self, matcher):
        """マッチしない場合"""
        assert not matcher.matches_pattern('ls -la', ['git*'])


class TestCheckCommand:
    """check_commandメソッドのテスト"""

    @pytest.fixture
    def temp_rules_file(self):
        """テスト用の一時ルールファイルを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Git規約',
                        'patterns': ['git push*', 'git commit*'],
                        'severity': 'block',
                        'message': 'Git操作確認'
                    },
                    {
                        'name': 'Deploy規約',
                        'patterns': ['*deploy*'],
                        'severity': 'warn',
                        'message': 'デプロイ確認'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        yield temp_path
        temp_path.unlink()

    def test_check_command_match(self, temp_rules_file):
        """コマンドがルールにマッチ"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)

        rule = matcher.check_command('git push origin main')
        assert rule is not None
        assert rule.name == 'Git規約'
        assert rule.severity == 'block'

    def test_check_command_second_rule_match(self, temp_rules_file):
        """2番目のルールにマッチ"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)

        rule = matcher.check_command('npm run deploy')
        assert rule is not None
        assert rule.name == 'Deploy規約'

    def test_check_command_no_match(self, temp_rules_file):
        """マッチするルールがない"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)

        rule = matcher.check_command('npm install express')
        assert rule is None


class TestGetConfirmationMessage:
    """get_confirmation_messageメソッドのテスト"""

    @pytest.fixture
    def temp_rules_file(self):
        """テスト用の一時ルールファイルを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Test規約',
                        'patterns': ['test*'],
                        'severity': 'block',
                        'message': 'テスト実行確認',
                        'token_threshold': 25000
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        yield temp_path
        temp_path.unlink()

    def test_get_confirmation_message_match(self, temp_rules_file):
        """確認メッセージ生成（マッチ）"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)

        result = matcher.get_confirmation_message('test command')
        assert result is not None
        assert result['rule_name'] == 'Test規約'
        assert result['severity'] == 'block'
        assert result['command'] == 'test command'
        assert result['token_threshold'] == 25000
        assert 'テスト実行確認' in result['message']
        assert '続行しますか？' in result['message']

    def test_get_confirmation_message_no_match(self, temp_rules_file):
        """確認メッセージ生成（マッチなし）"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)

        result = matcher.get_confirmation_message('unrelated command')
        assert result is None


class TestReloadRules:
    """reload_rulesメソッドのテスト"""

    def test_reload_rules(self):
        """ルールのリロード"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Original Rule',
                        'patterns': ['original*'],
                        'severity': 'warn',
                        'message': 'Original message'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        try:
            matcher = CommandConventionMatcher(rules_file=temp_path)
            assert len(matcher.rules) == 1
            assert matcher.rules[0].name == 'Original Rule'

            # ファイルを更新
            with open(temp_path, 'w') as f:
                new_rules = {
                    'rules': [
                        {
                            'name': 'Updated Rule',
                            'patterns': ['updated*'],
                            'severity': 'block',
                            'message': 'Updated message'
                        },
                        {
                            'name': 'Another Rule',
                            'patterns': ['another*'],
                            'severity': 'warn',
                            'message': 'Another message'
                        }
                    ]
                }
                yaml.dump(new_rules, f)

            # リロード
            matcher.reload_rules()

            assert len(matcher.rules) == 2
            assert matcher.rules[0].name == 'Updated Rule'
            assert matcher.rules[1].name == 'Another Rule'
        finally:
            temp_path.unlink()


class TestListRules:
    """list_rulesメソッドのテスト"""

    @pytest.fixture
    def temp_rules_file(self):
        """テスト用の一時ルールファイルを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Rule A',
                        'patterns': ['a*'],
                        'severity': 'block',
                        'message': 'Message A'
                    },
                    {
                        'name': 'Rule B',
                        'patterns': ['b*', 'bb*'],
                        'severity': 'warn',
                        'message': 'Message B'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        yield temp_path
        temp_path.unlink()

    def test_list_rules(self, temp_rules_file):
        """ルール一覧取得"""
        matcher = CommandConventionMatcher(rules_file=temp_rules_file)

        rules = matcher.list_rules()

        assert len(rules) == 2
        assert rules[0]['name'] == 'Rule A'
        assert rules[0]['patterns'] == ['a*']
        assert rules[0]['severity'] == 'block'
        assert rules[0]['message'] == 'Message A'
        assert rules[1]['name'] == 'Rule B'
        assert rules[1]['patterns'] == ['b*', 'bb*']

    def test_list_rules_empty(self):
        """ルールが空の場合"""
        matcher = CommandConventionMatcher(rules_file=Path('/nonexistent/file.yaml'))
        rules = matcher.list_rules()
        assert rules == []


class TestConventionRule:
    """ConventionRuleデータクラスのテスト"""

    def test_convention_rule_creation(self):
        """ルール作成"""
        rule = ConventionRule(
            name='Test',
            patterns=['test*'],
            severity='block',
            message='Test message',
            token_threshold=10000
        )
        assert rule.name == 'Test'
        assert rule.patterns == ['test*']
        assert rule.severity == 'block'
        assert rule.message == 'Test message'
        assert rule.token_threshold == 10000

    def test_convention_rule_default_threshold(self):
        """token_thresholdのデフォルト値"""
        rule = ConventionRule(
            name='Test',
            patterns=['test*'],
            severity='warn',
            message='Test message'
        )
        assert rule.token_threshold is None


class TestInvalidPatternHandling:
    """無効なパターンのハンドリングテスト"""

    @pytest.fixture
    def matcher(self):
        """テスト用マッチャーを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {'rules': []}
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        m = CommandConventionMatcher(rules_file=temp_path)
        temp_path.unlink()
        return m

    def test_invalid_pattern_skipped(self, matcher):
        """無効なパターンがスキップされる"""
        # Noneパターンを渡すと例外がキャッチされてFalseが返る
        result = matcher.matches_pattern('git push', [None])
        assert result is False

    def test_mixed_valid_invalid_patterns(self, matcher):
        """有効・無効パターン混在時、有効パターンでマッチする"""
        # 有効なパターンが含まれていればマッチする
        result = matcher.matches_pattern('git push', [None, 'git push'])
        assert result is True
