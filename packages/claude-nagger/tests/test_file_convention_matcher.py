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
        rules = matcher.check_file('some/path/test.pu')
        assert len(rules) == 1
        assert rules[0].name == 'Test Rule 1'
        assert rules[0].severity == 'block'
        
        # マッチしないファイル
        rules = matcher.check_file('other/file.txt')
        assert rules == []

    def test_get_confirmation_message(self, temp_rules_file):
        """確認メッセージ生成のテスト"""
        matcher = FileConventionMatcher(temp_rules_file)

        # マッチするファイルの場合
        results = matcher.get_confirmation_message('test/example.pu')
        assert len(results) == 1
        result = results[0]
        assert result['rule_name'] == 'Test Rule 1'
        assert result['severity'] == 'block'
        # メッセージフォーマット: "⚠️  {rule.message}" (convention_docは含まない)
        assert 'Test message 1' in result['message']

        # マッチしないファイルの場合
        results = matcher.get_confirmation_message('other.txt')
        assert results == []

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
            assert matcher.check_file('any/file.txt') == []
        finally:
            temp_path.unlink()

    def test_nonexistent_rules_file(self):
        """存在しないルールファイルのテスト"""
        matcher = FileConventionMatcher(Path('/nonexistent/file.yaml'))
        assert len(matcher.rules) == 0
        assert matcher.check_file('any/file.txt') == []

    def test_check_file_multiple_rules_match(self):
        """複数ルールにマッチするケース"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'PUファイル規約',
                        'patterns': ['**/*.pu'],
                        'severity': 'block',
                        'message': 'PUファイル変更確認'
                    },
                    {
                        'name': 'テストディレクトリ規約',
                        'patterns': ['test/**/*'],
                        'severity': 'warn',
                        'message': 'テストファイル変更注意'
                    },
                    {
                        'name': '無関係規約',
                        'patterns': ['app/**/*.rb'],
                        'severity': 'warn',
                        'message': 'Rubyファイル注意'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        try:
            matcher = FileConventionMatcher(temp_path)
            rules = matcher.check_file('test/example.pu')
            # PUファイル規約とテストディレクトリ規約の2つにマッチ
            assert len(rules) == 2
            assert rules[0].name == 'PUファイル規約'
            assert rules[1].name == 'テストディレクトリ規約'
        finally:
            temp_path.unlink()


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


class TestExcludePatterns:
    """exclude_patterns（除外パターン）のテスト"""

    @pytest.fixture
    def matcher(self):
        """テスト用マッチャーを作成"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump({'rules': []}, f)
            temp_path = Path(f.name)
        m = FileConventionMatcher(temp_path)
        temp_path.unlink()
        return m

    def test_exclude_pattern_prevents_match(self, matcher):
        """除外パターンにマッチする場合、ルールが非適用になる"""
        patterns = ["**/*"]
        exclude_patterns = ["vibes/docs/**"]

        # 除外パターンにマッチ → False
        assert not matcher.matches_pattern('vibes/docs/rules/test.md', patterns, exclude_patterns)
        assert not matcher.matches_pattern('vibes/docs/README.md', patterns, exclude_patterns)
        assert not matcher.matches_pattern('vibes/docs/specs/arch.md', patterns, exclude_patterns)

    def test_exclude_pattern_non_match_allows_rule(self, matcher):
        """除外パターンにマッチしない場合、ルールが適用される"""
        patterns = ["**/*"]
        exclude_patterns = ["vibes/docs/**"]

        # 除外パターンにマッチしない → True（ルール適用）
        assert matcher.matches_pattern('src/main.py', patterns, exclude_patterns)
        assert matcher.matches_pattern('tests/test_main.py', patterns, exclude_patterns)
        assert matcher.matches_pattern('README.md', patterns, exclude_patterns)

    def test_exclude_patterns_empty_preserves_behavior(self, matcher):
        """exclude_patternsが空リストの場合、既存動作を維持"""
        patterns = ["**/*"]

        assert matcher.matches_pattern('any/file.txt', patterns, [])
        assert matcher.matches_pattern('src/main.py', patterns, [])

    def test_exclude_patterns_none_preserves_behavior(self, matcher):
        """exclude_patternsがNoneの場合、既存動作を維持"""
        patterns = ["**/*"]

        assert matcher.matches_pattern('any/file.txt', patterns, None)
        assert matcher.matches_pattern('src/main.py', patterns, None)

    def test_exclude_patterns_loaded_from_yaml(self):
        """YAMLからexclude_patternsが正しく読み込まれる"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': '全ファイル禁止（例外あり）',
                        'patterns': ['**/*'],
                        'severity': 'deny',
                        'scope': 'pmo',
                        'exclude_patterns': ['vibes/docs/**'],
                        'message': 'ファイル編集禁止（vibes/docs除く）'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        try:
            matcher = FileConventionMatcher(temp_path)
            assert len(matcher.rules) == 1
            assert matcher.rules[0].exclude_patterns == ['vibes/docs/**']

            # 除外パスはルールに非該当
            rules = matcher.check_file('vibes/docs/rules/test.md')
            assert len(rules) == 0

            # 除外外パスはルールに該当
            rules = matcher.check_file('src/main.py')
            assert len(rules) == 1
            assert rules[0].name == '全ファイル禁止（例外あり）'
        finally:
            temp_path.unlink()

    def test_exclude_patterns_default_empty(self):
        """exclude_patterns未指定時はデフォルト空リスト"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            rules_data = {
                'rules': [
                    {
                        'name': 'ルール（exclude未指定）',
                        'patterns': ['**/*.py'],
                        'severity': 'warn',
                        'message': 'テスト'
                    }
                ]
            }
            yaml.dump(rules_data, f)
            temp_path = Path(f.name)

        try:
            matcher = FileConventionMatcher(temp_path)
            assert matcher.rules[0].exclude_patterns == []
            # 既存動作に影響なし
            rules = matcher.check_file('src/main.py')
            assert len(rules) == 1
        finally:
            temp_path.unlink()
