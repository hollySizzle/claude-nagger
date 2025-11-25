"""FileConventionMatcherのテスト"""

import pytest
from pathlib import Path
import tempfile
import yaml
from src.domain.services.file_convention_matcher import FileConventionMatcher, ConventionRule


class TestFileConventionMatcher:
    """FileConventionMatcherのテストクラス"""

    @pytest.fixture
    def temp_rules_file(self):
        """テスト用の一時ルールファイルを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Test Rule 1',
                        'patterns': ['**/test.pu', 'test/*.pu'],
                        'convention_doc': '@test/doc1.md',
                        'severity': 'block',
                        'message': 'Test message 1'
                    },
                    {
                        'name': 'Test Rule 2',
                        'patterns': ['app/**/*.rb'],
                        'convention_doc': '@test/doc2.md',
                        'severity': 'warn',
                        'message': 'Test message 2'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)
        
        yield temp_path
        
        # クリーンアップ
        temp_path.unlink()

    def test_load_rules(self, temp_rules_file):
        """ルールファイルの読み込みテスト"""
        matcher = FileConventionMatcher(temp_rules_file)
        
        assert len(matcher.rules) == 2
        assert matcher.rules[0].name == 'Test Rule 1'
        assert matcher.rules[0].severity == 'block'
        assert matcher.rules[1].name == 'Test Rule 2'
        assert matcher.rules[1].severity == 'warn'

    def test_matches_pattern_exact(self, temp_rules_file):
        """完全一致パターンのテスト"""
        matcher = FileConventionMatcher(temp_rules_file)
        
        # test/*.puパターンのテスト
        assert matcher.matches_pattern('test/file.pu', ['test/*.pu'])
        assert not matcher.matches_pattern('other/file.pu', ['test/*.pu'])

    def test_matches_pattern_wildcard(self, temp_rules_file):
        """ワイルドカードパターンのテスト"""
        matcher = FileConventionMatcher(temp_rules_file)
        
        # **パターンのテスト
        assert matcher.matches_pattern('deep/nested/test.pu', ['**/test.pu'])
        assert matcher.matches_pattern('test.pu', ['**/test.pu'])
        assert not matcher.matches_pattern('deep/nested/other.pu', ['**/test.pu'])
        
        # app/**/*.rbパターンのテスト
        assert matcher.matches_pattern('app/models/user.rb', ['app/**/*.rb'])
        assert matcher.matches_pattern('app/controllers/api/v1/users.rb', ['app/**/*.rb'])
        assert not matcher.matches_pattern('lib/tasks/user.rb', ['app/**/*.rb'])

    def test_check_file(self, temp_rules_file):
        """ファイルチェック機能のテスト"""
        matcher = FileConventionMatcher(temp_rules_file)
        
        # マッチするファイル
        rule = matcher.check_file('some/path/test.pu')
        assert rule is not None
        assert rule.name == 'Test Rule 1'
        assert rule.severity == 'block'
        
        # マッチしないファイル
        rule = matcher.check_file('other/file.txt')
        assert rule is None

    def test_get_confirmation_message(self, temp_rules_file):
        """確認メッセージ生成のテスト"""
        matcher = FileConventionMatcher(temp_rules_file)
        
        # マッチするファイルの場合
        result = matcher.get_confirmation_message('test/example.pu')
        assert result is not None
        assert result['rule_name'] == 'Test Rule 1'
        assert result['severity'] == 'block'
        assert '@test/doc1.md' in result['message']
        assert 'Test message 1' in result['message']
        
        # マッチしないファイルの場合
        result = matcher.get_confirmation_message('other.txt')
        assert result is None

    def test_list_rules(self, temp_rules_file):
        """ルール一覧取得のテスト"""
        matcher = FileConventionMatcher(temp_rules_file)
        
        rules = matcher.list_rules()
        assert len(rules) == 2
        assert rules[0]['name'] == 'Test Rule 1'
        assert rules[0]['patterns'] == ['**/test.pu', 'test/*.pu']
        assert rules[1]['name'] == 'Test Rule 2'

    def test_reload_rules(self, temp_rules_file):
        """ルールリロードのテスト"""
        matcher = FileConventionMatcher(temp_rules_file)
        initial_rules = len(matcher.rules)
        
        # ファイルを更新
        with open(temp_rules_file, 'w') as f:
            new_data = {
                'rules': [
                    {
                        'name': 'New Rule',
                        'patterns': ['new/*.txt'],
                        'convention_doc': '@new/doc.md',
                        'severity': 'warn',
                        'message': 'New message'
                    }
                ]
            }
            yaml.dump(new_data, f)
        
        # リロード
        matcher.reload_rules()
        
        assert len(matcher.rules) == 1
        assert matcher.rules[0].name == 'New Rule'

    def test_empty_rules_file(self):
        """空のルールファイルのテスト"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({}, f)
            temp_path = Path(f.name)
        
        try:
            matcher = FileConventionMatcher(temp_path)
            assert len(matcher.rules) == 0
            assert matcher.check_file('any/file.txt') is None
        finally:
            temp_path.unlink()

    def test_nonexistent_rules_file(self):
        """存在しないルールファイルのテスト"""
        matcher = FileConventionMatcher(Path('/nonexistent/file.yaml'))
        assert len(matcher.rules) == 0
        assert matcher.check_file('any/file.txt') is None