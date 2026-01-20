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
        # メッセージフォーマット: "⚠️  {rule.message}" (convention_docは含まない)
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


class TestGlobstarPatterns:
    """GLOBSTARパターン(**/)の詳細テスト"""

    @pytest.fixture
    def matcher(self):
        """テスト用マッチャーを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': []}, f)
            temp_path = Path(f.name)
        m = FileConventionMatcher(temp_path)
        temp_path.unlink()
        return m

    def test_double_globstar_directory_all_files(self, matcher):
        """**/test/** - どこにあるtest/でもその中の全ファイル"""
        pattern = ["**/test/**"]
        # test直下
        assert matcher.matches_pattern('test/file.py', pattern)
        # testサブディレクトリ
        assert matcher.matches_pattern('test/subdir/file.py', pattern)
        assert matcher.matches_pattern('test/subdir/deep/file.py', pattern)
        # src/test以下
        assert matcher.matches_pattern('src/test/file.py', pattern)
        assert matcher.matches_pattern('src/test/utils/helper.py', pattern)
        # マッチしないケース
        assert not matcher.matches_pattern('tests/file.py', pattern)  # testsはtestと異なる
        assert not matcher.matches_pattern('src/testing/file.py', pattern)

    def test_globstar_directory_specific_extension(self, matcher):
        """**/apps/**/*.scss - どこにあるapps/でも全階層の.scssファイル"""
        pattern = ["**/apps/**/*.scss"]
        # ルート直下apps
        assert matcher.matches_pattern('apps/style.scss', pattern)
        assert matcher.matches_pattern('apps/components/button.scss', pattern)
        # src/apps
        assert matcher.matches_pattern('src/apps/theme.scss', pattern)
        assert matcher.matches_pattern('packages/ui/apps/styles/main.scss', pattern)
        # 拡張子が異なる
        assert not matcher.matches_pattern('apps/style.css', pattern)
        assert not matcher.matches_pattern('apps/style.sass', pattern)

    def test_single_level_only(self, matcher):
        """src/*.ts - src直下のみ（サブディレクトリ除外）"""
        pattern = ["src/*.ts"]
        # 直下のみマッチ
        assert matcher.matches_pattern('src/index.ts', pattern)
        assert matcher.matches_pattern('src/utils.ts', pattern)
        # サブディレクトリはマッチしない
        assert not matcher.matches_pattern('src/lib/helper.ts', pattern)
        assert not matcher.matches_pattern('src/components/Button.ts', pattern)

    def test_globstar_with_prefix_pattern(self, matcher):
        """**/test_*.py - 全階層のtest_で始まるpyファイル"""
        pattern = ["**/test_*.py"]
        assert matcher.matches_pattern('test_main.py', pattern)
        assert matcher.matches_pattern('tests/test_utils.py', pattern)
        assert matcher.matches_pattern('src/tests/unit/test_handler.py', pattern)
        # マッチしない
        assert not matcher.matches_pattern('tests/utils.py', pattern)
        assert not matcher.matches_pattern('test_main.js', pattern)

    def test_globstar_with_suffix_pattern(self, matcher):
        """**/*_test.go - 全階層の_testで終わるgoファイル"""
        pattern = ["**/*_test.go"]
        assert matcher.matches_pattern('main_test.go', pattern)
        assert matcher.matches_pattern('pkg/handler_test.go', pattern)
        assert matcher.matches_pattern('internal/service/user_test.go', pattern)
        # マッチしない
        assert not matcher.matches_pattern('pkg/handler.go', pattern)
        assert not matcher.matches_pattern('main_test.rs', pattern)

    def test_root_directory_globstar(self, matcher):
        """apps/**/*.tsx - ルート直下apps以下の全階層"""
        pattern = ["apps/**/*.tsx"]
        # ルート直下のapps
        assert matcher.matches_pattern('apps/App.tsx', pattern)
        assert matcher.matches_pattern('apps/components/Button.tsx', pattern)
        assert matcher.matches_pattern('apps/pages/home/index.tsx', pattern)
        # src/appsはマッチしない（ルート直下のappsのみ）
        assert not matcher.matches_pattern('src/apps/App.tsx', pattern)

    def test_all_files_with_extension(self, matcher):
        """**/*.scss - 全階層の.scssファイル"""
        pattern = ["**/*.scss"]
        assert matcher.matches_pattern('style.scss', pattern)
        assert matcher.matches_pattern('src/style.scss', pattern)
        assert matcher.matches_pattern('src/components/button/style.scss', pattern)
        # 拡張子が異なる
        assert not matcher.matches_pattern('style.css', pattern)


class TestAbsolutePathConversion:
    """絶対パス→相対パス変換のテスト（#4074対応）"""

    @pytest.fixture
    def matcher(self):
        """テスト用マッチャーを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': []}, f)
            temp_path = Path(f.name)
        m = FileConventionMatcher(temp_path)
        temp_path.unlink()
        return m

    def test_absolute_path_under_cwd(self, matcher, monkeypatch):
        """CWD配下の絶対パスが相対パスに変換されてマッチする"""
        # CWDを/myapp/Source/railsに設定
        monkeypatch.chdir('/tmp')
        
        # /tmp配下のパスをテスト
        pattern = ["app/views/**/*.erb"]
        
        # 一時的にディレクトリ構造を作成
        test_dir = Path('/tmp/app/views/shared')
        test_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # 絶対パスが相対パスに変換されてマッチする
            assert matcher.matches_pattern('/tmp/app/views/shared/test.erb', pattern)
            # 相対パスも引き続きマッチする
            assert matcher.matches_pattern('app/views/shared/test.erb', pattern)
        finally:
            # クリーンアップ
            import shutil
            shutil.rmtree('/tmp/app', ignore_errors=True)

    def test_absolute_path_not_under_cwd(self, matcher, monkeypatch):
        """CWD外の絶対パスはそのまま使用される（マッチしない）"""
        monkeypatch.chdir('/tmp')
        pattern = ["app/**/*.rb"]
        
        # /other/pathはCWD(/tmp)の配下ではないのでマッチしない
        assert not matcher.matches_pattern('/other/path/app/models/user.rb', pattern)

    def test_relative_path_unchanged(self, matcher):
        """相対パスはそのまま処理される"""
        pattern = ["src/**/*.py"]
        
        assert matcher.matches_pattern('src/main.py', pattern)
        assert matcher.matches_pattern('src/lib/utils.py', pattern)
        assert not matcher.matches_pattern('other/main.py', pattern)


class TestErrorHandling:
    """エラーハンドリングのテスト"""

    def test_load_rules_yaml_error(self):
        """YAML構文エラー"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content:\n  - broken")
            temp_path = Path(f.name)

        try:
            matcher = FileConventionMatcher(rules_file=temp_path)
            assert len(matcher.rules) == 0
        finally:
            temp_path.unlink()

    def test_load_rules_missing_required_field(self):
        """必須フィールド欠落（KeyError）"""
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
            matcher = FileConventionMatcher(rules_file=temp_path)
            assert len(matcher.rules) == 0
        finally:
            temp_path.unlink()

    def test_invalid_pattern_skipped(self):
        """無効なパターンがスキップされる"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'Rule with valid pattern',
                        'patterns': ['valid/*.py'],
                        'severity': 'warn',
                        'message': 'Test message'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        try:
            matcher = FileConventionMatcher(rules_file=temp_path)
            # 無効なパターン（Noneなど）を直接テスト
            # matches_patternは例外をキャッチしてFalseを返す
            result = matcher.matches_pattern('test.py', [None])
            assert result is False
        finally:
            temp_path.unlink()
