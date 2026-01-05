"""ConfigManagerのテスト - 設定読み込み優先順位

Issue #3876: CI環境での設定読み込み優先順位テスト
"""

import pytest
import tempfile
import os
import json
from pathlib import Path
from unittest.mock import patch

try:
    import json5
    HAS_JSON5 = True
except ImportError:
    HAS_JSON5 = False

from src.infrastructure.config.config_manager import ConfigManager


class TestConfigLoadingPriority:
    """設定読み込み優先順位のテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def valid_config(self):
        """有効な設定データ"""
        return {
            "system": {
                "version": "test-1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }

    def test_explicit_config_path_takes_priority(self, temp_dir, valid_config):
        """明示的にパス指定した場合、そのパスを使用する"""
        # 明示的に指定する設定ファイル
        explicit_config = temp_dir / "explicit_config.json"
        explicit_config.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=explicit_config)
        
        assert manager.config_path == explicit_config
        assert manager.config["system"]["version"] == "test-1.0.0"

    @pytest.mark.skipif(not HAS_JSON5, reason="json5 not installed")
    def test_explicit_json5_config_path(self, temp_dir, valid_config):
        """JSON5形式の明示的パス指定"""
        explicit_config = temp_dir / "explicit_config.json5"
        explicit_config.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=explicit_config)
        
        assert manager.config_path == explicit_config
        assert manager.config["system"]["version"] == "test-1.0.0"


class TestClaudeNaggerDirectoryPriority:
    """.claude-nagger/ディレクトリの優先度テスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def project_config(self):
        """プロジェクト固有の設定データ"""
        return {
            "system": {
                "version": "project-specific-1.0.0",
                "rails_root": "./project",
                "doc_root": "./project/docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }

    def test_claude_nagger_dir_exists_is_used(self, temp_dir, project_config):
        """.claude-nagger/config.json5が存在する場合、それを使用する"""
        # .claude-nagger/ディレクトリを作成
        claude_nagger_dir = temp_dir / ".claude-nagger"
        claude_nagger_dir.mkdir()
        
        config_file = claude_nagger_dir / "config.json5"
        config_file.write_text(json.dumps(project_config), encoding="utf-8")

        # cwd()を一時ディレクトリに変更してテスト
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # config_path=Noneで呼び出し（デフォルト動作をテスト）
            manager = ConfigManager(config_path=None)
            
            # .claude-nagger/config.json5が選択されていることを確認
            assert manager.config_path == config_file
            assert manager.config["system"]["version"] == "project-specific-1.0.0"
        finally:
            os.chdir(original_cwd)

    def test_claude_nagger_dir_not_exists_uses_default(self, temp_dir):
        """.claude-nagger/が存在しない場合、パッケージデフォルトを使用する"""
        # 空の一時ディレクトリ（.claude-nagger/なし）
        
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            manager = ConfigManager(config_path=None)
            
            # パッケージデフォルトのパスが使用される
            # base_dir / "config.json5" が選択される
            assert ".claude-nagger" not in str(manager.config_path)
        finally:
            os.chdir(original_cwd)


class TestDefaultFallback:
    """デフォルトフォールバック動作のテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_file_not_found_fallback(self, temp_dir):
        """設定ファイルが見つからない場合、デフォルト設定にフォールバック"""
        non_existent_path = temp_dir / "non_existent.json"
        
        manager = ConfigManager(config_path=non_existent_path)
        
        # デフォルト設定が使用される
        assert manager.config["system"]["version"] == "1.0.0"
        assert manager.config["system"]["rails_root"] == "../../"
        assert manager.config["system"]["doc_root"] == "../docs"

    def test_default_config_structure(self, temp_dir):
        """デフォルト設定の構造が正しいことを確認"""
        non_existent_path = temp_dir / "non_existent.json"
        
        manager = ConfigManager(config_path=non_existent_path)
        config = manager.config
        
        # 必須キーの存在確認
        assert "system" in config
        assert "document" in config
        
        # system セクション
        assert "version" in config["system"]
        assert "rails_root" in config["system"]
        assert "doc_root" in config["system"]
        assert "scripts_root" in config["system"]
        
        # document セクション
        assert "templates_dir" in config["document"]
        assert "output_dir" in config["document"]
        assert "target_dirs" in config["document"]


class TestSyntaxErrorHandling:
    """構文エラー時のエラーメッセージテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_json_syntax_error_fallback(self, temp_dir, capsys):
        """JSON構文エラー時、エラーメッセージを出力してデフォルトにフォールバック"""
        invalid_json_file = temp_dir / "invalid.json"
        invalid_json_file.write_text("{ invalid json syntax", encoding="utf-8")
        
        manager = ConfigManager(config_path=invalid_json_file)
        
        # デフォルト設定にフォールバック
        assert manager.config["system"]["version"] == "1.0.0"
        
        # エラーメッセージが出力されていることを確認
        captured = capsys.readouterr()
        assert "設定ファイル構文エラー" in captured.out
        assert str(invalid_json_file) in captured.out

    @pytest.mark.skipif(not HAS_JSON5, reason="json5 not installed")
    def test_json5_syntax_error_fallback(self, temp_dir, capsys):
        """JSON5構文エラー時、エラーメッセージを出力してデフォルトにフォールバック"""
        invalid_json5_file = temp_dir / "invalid.json5"
        invalid_json5_file.write_text("{ invalid: json5 syntax {{{{", encoding="utf-8")
        
        manager = ConfigManager(config_path=invalid_json5_file)
        
        # デフォルト設定にフォールバック
        assert manager.config["system"]["version"] == "1.0.0"
        
        # エラーメッセージが出力されている
        captured = capsys.readouterr()
        # json5のエラーはjson.JSONDecodeError以外の可能性があるため
        # 「設定ファイル読み込みエラー」または「設定ファイル構文エラー」のいずれかを確認
        assert ("設定ファイル構文エラー" in captured.out or 
                "設定ファイル読み込みエラー" in captured.out)

    def test_empty_file_fallback(self, temp_dir, capsys):
        """空ファイルの場合、デフォルトにフォールバック"""
        empty_file = temp_dir / "empty.json"
        empty_file.write_text("", encoding="utf-8")
        
        manager = ConfigManager(config_path=empty_file)
        
        # デフォルト設定にフォールバック
        assert manager.config["system"]["version"] == "1.0.0"
        
        # エラーメッセージが出力されている
        captured = capsys.readouterr()
        assert "設定ファイル" in captured.out


class TestCIEnvironmentCompatibility:
    """CI環境での互換性テスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def valid_config(self):
        """有効な設定データ"""
        return {
            "system": {
                "version": "ci-test-1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }

    def test_config_from_environment_variable_path(self, temp_dir, valid_config):
        """環境変数で指定されたパスからの設定読み込み（CI環境シミュレート）"""
        # CI環境でよくある: 設定ファイルを特定のパスに配置
        ci_config_path = temp_dir / "ci" / "config.json"
        ci_config_path.parent.mkdir(parents=True, exist_ok=True)
        ci_config_path.write_text(json.dumps(valid_config), encoding="utf-8")
        
        # 明示的なパスで読み込み（CI環境での典型的な使用法）
        manager = ConfigManager(config_path=ci_config_path)
        
        assert manager.config["system"]["version"] == "ci-test-1.0.0"

    def test_isolation_between_instances(self, temp_dir, valid_config):
        """異なるConfigManagerインスタンスが互いに影響しないことを確認"""
        config1_path = temp_dir / "config1.json"
        config2_path = temp_dir / "config2.json"
        
        valid_config_copy = valid_config.copy()
        valid_config_copy["system"] = valid_config_copy["system"].copy()
        valid_config_copy["system"]["version"] = "instance-2"
        
        config1_path.write_text(json.dumps(valid_config), encoding="utf-8")
        config2_path.write_text(json.dumps(valid_config_copy), encoding="utf-8")
        
        manager1 = ConfigManager(config_path=config1_path)
        manager2 = ConfigManager(config_path=config2_path)
        
        assert manager1.config["system"]["version"] == "ci-test-1.0.0"
        assert manager2.config["system"]["version"] == "instance-2"

    def test_multiple_reads_same_result(self, temp_dir, valid_config):
        """同じインスタンスから複数回読み込んでも同じ結果を返す（キャッシュ動作）"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")
        
        manager = ConfigManager(config_path=config_path)
        
        # 複数回アクセス
        config1 = manager.config
        config2 = manager.config
        
        assert config1 is config2  # 同じオブジェクトが返される（キャッシュ）


class TestYAMLConfigLoading:
    """YAML形式設定ファイルの読み込みテスト
    
    Issue #3889: ConfigManager YAML読み込みテスト追加
    TDD Red Phase: 実装前のテスト（初期状態では失敗する）
    """

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def valid_yaml_config(self):
        """有効なYAML設定データ"""
        return """system:
  version: "yaml-test-1.0.0"
  rails_root: "./"
  doc_root: "./docs"
  scripts_root: "./"

document:
  templates_dir: "templates"
  output_dir: "output"
  target_dirs: {}
"""

    def test_yaml_config_loading(self, temp_dir, valid_yaml_config):
        """YAML形式の設定ファイルを正常に読み込めること"""
        yaml_config_path = temp_dir / "config.yaml"
        yaml_config_path.write_text(valid_yaml_config, encoding="utf-8")
        
        manager = ConfigManager(config_path=yaml_config_path)
        
        assert manager.config["system"]["version"] == "yaml-test-1.0.0"
        assert manager.config["system"]["rails_root"] == "./"
        assert manager.config["document"]["templates_dir"] == "templates"

    def test_yml_extension_loading(self, temp_dir, valid_yaml_config):
        """".yml"拡張子のYAML設定ファイルも読み込めること"""
        yml_config_path = temp_dir / "config.yml"
        yml_config_path.write_text(valid_yaml_config, encoding="utf-8")
        
        manager = ConfigManager(config_path=yml_config_path)
        
        assert manager.config["system"]["version"] == "yaml-test-1.0.0"


class TestClaudeNaggerYAMLPriority:
    """.claude-nagger/config.yaml優先読み込みテスト
    
    Issue #3889: .claude-nagger/config.yaml優先読み込み
    """

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def yaml_project_config(self):
        """プロジェクト固有YAML設定データ"""
        return """system:
  version: "yaml-project-1.0.0"
  rails_root: "./yaml-project"
  doc_root: "./yaml-project/docs"
  scripts_root: "./"

document:
  templates_dir: "templates"
  output_dir: "output"
  target_dirs: {}
"""

    def test_claude_nagger_yaml_priority(self, temp_dir, yaml_project_config):
        """.claude-nagger/config.yamlが存在する場合、それを優先して使用する"""
        # .claude-nagger/ディレクトリを作成
        claude_nagger_dir = temp_dir / ".claude-nagger"
        claude_nagger_dir.mkdir()
        
        yaml_config_file = claude_nagger_dir / "config.yaml"
        yaml_config_file.write_text(yaml_project_config, encoding="utf-8")

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            # config_path=Noneで呼び出し（デフォルト動作をテスト）
            manager = ConfigManager(config_path=None)
            
            # .claude-nagger/config.yamlが選択されていることを確認
            assert manager.config_path == yaml_config_file
            assert manager.config["system"]["version"] == "yaml-project-1.0.0"
        finally:
            os.chdir(original_cwd)

    def test_yaml_priority_over_json5(self, temp_dir, yaml_project_config):
        """YAML形式がJSON5形式より優先されること（両方存在する場合）"""
        claude_nagger_dir = temp_dir / ".claude-nagger"
        claude_nagger_dir.mkdir()
        
        # YAML設定
        yaml_config_file = claude_nagger_dir / "config.yaml"
        yaml_config_file.write_text(yaml_project_config, encoding="utf-8")
        
        # JSON5設定（異なるバージョン）
        json5_config = {
            "system": {
                "version": "json5-project-2.0.0",
                "rails_root": "./json5-project",
                "doc_root": "./json5-project/docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }
        json5_config_file = claude_nagger_dir / "config.json5"
        json5_config_file.write_text(json.dumps(json5_config), encoding="utf-8")

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            
            manager = ConfigManager(config_path=None)
            
            # YAMLが優先される
            assert manager.config_path == yaml_config_file
            assert manager.config["system"]["version"] == "yaml-project-1.0.0"
        finally:
            os.chdir(original_cwd)


class TestYAMLSyntaxErrorHandling:
    """YAML構文エラー時のフォールバックテスト
    
    Issue #3889: YAML構文エラー時のフォールバック
    """

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_yaml_syntax_error_fallback(self, temp_dir, capsys):
        """YAML構文エラー時、エラーメッセージを出力してデフォルトにフォールバック"""
        invalid_yaml_file = temp_dir / "invalid.yaml"
        # 不正なYAML（インデントエラー）
        invalid_yaml_file.write_text("""system:
  version: "test"
    invalid_indent: true
  another: value
""", encoding="utf-8")
        
        manager = ConfigManager(config_path=invalid_yaml_file)
        
        # デフォルト設定にフォールバック
        assert manager.config["system"]["version"] == "1.0.0"
        
        # エラーメッセージが出力されていることを確認
        captured = capsys.readouterr()
        assert "設定ファイル" in captured.out
        assert str(invalid_yaml_file) in captured.out

    def test_yaml_tab_character_error(self, temp_dir, capsys):
        """YAMLでタブ文字使用時のエラーハンドリング"""
        tab_yaml_file = temp_dir / "tab_error.yaml"
        # タブ文字を含むYAML（YAMLではタブはエラー）
        tab_yaml_file.write_text("system:\n\tversion: 'test'", encoding="utf-8")
        
        manager = ConfigManager(config_path=tab_yaml_file)
        
        # デフォルト設定にフォールバック
        assert manager.config["system"]["version"] == "1.0.0"


class TestEmptyYAMLHandling:
    """空YAMLファイルのハンドリングテスト
    
    Issue #3889: 空YAMLファイルのハンドリング
    """

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_empty_yaml_file_fallback(self, temp_dir, capsys):
        """空のYAMLファイルの場合、デフォルト設定にフォールバック"""
        empty_yaml_file = temp_dir / "empty.yaml"
        empty_yaml_file.write_text("", encoding="utf-8")
        
        manager = ConfigManager(config_path=empty_yaml_file)
        
        # デフォルト設定にフォールバック
        assert manager.config["system"]["version"] == "1.0.0"
        assert manager.config["document"]["templates_dir"] == "templates"

    def test_yaml_only_comments_fallback(self, temp_dir, capsys):
        """コメントのみのYAMLファイルの場合、デフォルト設定にフォールバック"""
        comments_only_yaml = temp_dir / "comments_only.yaml"
        comments_only_yaml.write_text("""# This is a comment
# Another comment
# No actual configuration
""", encoding="utf-8")
        
        manager = ConfigManager(config_path=comments_only_yaml)
        
        # デフォルト設定にフォールバック（YAMLパース結果がNone）
        assert manager.config["system"]["version"] == "1.0.0"

    def test_yaml_null_document_fallback(self, temp_dir, capsys):
        """YAMLが明示的にnullの場合、デフォルト設定にフォールバック"""
        null_yaml_file = temp_dir / "null.yaml"
        null_yaml_file.write_text("null", encoding="utf-8")
        
        manager = ConfigManager(config_path=null_yaml_file)
        
        # デフォルト設定にフォールバック
        assert manager.config["system"]["version"] == "1.0.0"

    def test_yaml_empty_dict_handling(self, temp_dir, capsys):
        """空のdict {}の場合の処理"""
        empty_dict_yaml = temp_dir / "empty_dict.yaml"
        empty_dict_yaml.write_text("{}", encoding="utf-8")

        manager = ConfigManager(config_path=empty_dict_yaml)

        # 空のdictなのでデフォルト設定にフォールバック
        # または空dictとして読み込まれる（実装依存）
        # この場合、キーアクセス時にKeyErrorを避けるためデフォルトにフォールバックすべき
        assert manager.config["system"]["version"] == "1.0.0"


class TestResolvePath:
    """resolve_pathメソッドのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def valid_config(self):
        """有効な設定データ"""
        return {
            "system": {
                "version": "1.0.0",
                "rails_root": "../../",
                "doc_root": "../docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }

    def test_resolve_absolute_path(self, temp_dir, valid_config):
        """絶対パスはそのまま返される"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        result = manager.resolve_path("/absolute/path/to/file")
        assert result == Path("/absolute/path/to/file")

    def test_resolve_relative_path(self, temp_dir, valid_config):
        """相対パスはbase_dirからの相対として解決"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        result = manager.resolve_path("./relative/path")
        # base_dir / "./relative/path" が解決される
        assert result.is_absolute()


class TestGetPathMethods:
    """パス取得メソッドのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def valid_config(self):
        """有効な設定データ"""
        return {
            "system": {
                "version": "1.0.0",
                "rails_root": "../../",
                "doc_root": "../docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {
                    "rules": "../docs/rules",
                    "specs": "../docs/specs"
                }
            }
        }

    def test_get_rails_root(self, temp_dir, valid_config):
        """Railsルート取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_rails_root()

        assert result.is_absolute()

    def test_get_doc_root(self, temp_dir, valid_config):
        """ドキュメントルート取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_doc_root()

        assert result.is_absolute()

    def test_get_scripts_root(self, temp_dir, valid_config):
        """スクリプトルート取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_scripts_root()

        assert result.is_absolute()

    def test_get_templates_dir(self, temp_dir, valid_config):
        """テンプレートディレクトリ取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_templates_dir()

        assert result.is_absolute()

    def test_get_output_dir(self, temp_dir, valid_config):
        """出力ディレクトリ取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_output_dir()

        assert result.is_absolute()

    def test_get_target_dir_valid_category(self, temp_dir, valid_config):
        """有効なカテゴリのターゲットディレクトリ取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_target_dir("rules")

        assert result is not None
        assert result.is_absolute()

    def test_get_target_dir_invalid_category(self, temp_dir, valid_config):
        """無効なカテゴリはNoneを返す"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_target_dir("nonexistent")

        assert result is None

    def test_get_all_target_dirs(self, temp_dir, valid_config):
        """全ターゲットディレクトリ取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_all_target_dirs()

        assert "rules" in result
        assert "specs" in result
        assert result["rules"].is_absolute()


class TestGetSettings:
    """設定取得メソッドのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def full_config(self):
        """完全な設定データ"""
        return {
            "system": {
                "version": "1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            },
            "hooks": {
                "enabled": True,
                "timeout": 30
            },
            "convention_hooks": {
                "enabled": True,
                "context_management": {
                    "thresholds": {
                        "light_warning": 25000,
                        "medium_warning": 50000
                    },
                    "marker_management": {
                        "enabled": True,
                        "cleanup_on_exit": True
                    }
                },
                "display_levels": {
                    "verbose": {
                        "show_details": True
                    }
                }
            }
        }

    def test_get_hook_settings(self, temp_dir, full_config):
        """フック設定取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(full_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_hook_settings()

        assert result["enabled"] is True
        assert result["timeout"] == 30

    def test_get_convention_hook_settings(self, temp_dir, full_config):
        """規約Hook設定取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(full_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_convention_hook_settings()

        assert result["enabled"] is True

    def test_get_context_thresholds(self, temp_dir, full_config):
        """コンテキスト閾値設定取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(full_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_context_thresholds()

        assert result["light_warning"] == 25000
        assert result["medium_warning"] == 50000

    def test_get_context_thresholds_default(self, temp_dir):
        """コンテキスト閾値のデフォルト値"""
        # 最小限の設定
        minimal_config = {
            "system": {
                "version": "1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(minimal_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_context_thresholds()

        # デフォルト値が返される
        assert "light_warning" in result
        assert result["light_warning"] == 30000

    def test_get_marker_settings(self, temp_dir, full_config):
        """マーカー設定取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(full_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_marker_settings()

        assert result["enabled"] is True
        assert result["cleanup_on_exit"] is True

    def test_get_display_level_config(self, temp_dir, full_config):
        """表示レベル設定取得"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(full_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_display_level_config("verbose")

        assert result["show_details"] is True


class TestResolveValue:
    """_resolve_valueメソッドのテスト（環境変数展開）"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def valid_config(self):
        """有効な設定データ"""
        return {
            "system": {
                "version": "1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            },
            "notifications": {
                "discord": {
                    "webhook_url": "${DISCORD_WEBHOOK_URL}",
                    "thread_id": "${DISCORD_THREAD_ID}"
                }
            }
        }

    def test_resolve_env_variable(self, temp_dir, valid_config):
        """環境変数が解決される"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        # 環境変数を設定
        with patch.dict(os.environ, {"TEST_VAR": "test_value"}):
            result = manager._resolve_value("${TEST_VAR}")
            assert result == "test_value"

    def test_resolve_missing_env_variable(self, temp_dir, valid_config):
        """存在しない環境変数は空文字列になる"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        result = manager._resolve_value("${NONEXISTENT_VAR}")
        assert result == ""

    def test_resolve_dict_recursively(self, temp_dir, valid_config):
        """辞書内の値が再帰的に解決される"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        with patch.dict(os.environ, {"MY_KEY": "my_value"}):
            result = manager._resolve_value({"key": "${MY_KEY}"})
            assert result["key"] == "my_value"

    def test_resolve_list_recursively(self, temp_dir, valid_config):
        """リスト内の値が再帰的に解決される"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        with patch.dict(os.environ, {"ITEM1": "value1", "ITEM2": "value2"}):
            result = manager._resolve_value(["${ITEM1}", "${ITEM2}"])
            assert result == ["value1", "value2"]

    def test_resolve_plain_value_unchanged(self, temp_dir, valid_config):
        """プレーンな値はそのまま返される"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        result = manager._resolve_value("plain_value")
        assert result == "plain_value"

    def test_get_notification_settings(self, temp_dir, valid_config):
        """通知設定取得（環境変数展開済み）"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        with patch.dict(os.environ, {
            "DISCORD_WEBHOOK_URL": "https://webhook.url",
            "DISCORD_THREAD_ID": "12345"
        }):
            result = manager.get_notification_settings()
            assert result["discord"]["webhook_url"] == "https://webhook.url"
            assert result["discord"]["thread_id"] == "12345"


class TestLoadSecrets:
    """_load_secretsメソッドのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def valid_config(self):
        """有効な設定データ"""
        return {
            "system": {
                "version": "1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }

    def test_load_secrets_nonexistent(self, temp_dir, valid_config):
        """secrets.json5が存在しない場合は空辞書を返す"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        # secrets_pathを存在しないパスに設定
        manager.secrets_path = temp_dir / "nonexistent_secrets.json5"
        result = manager._load_secrets()

        assert result == {}

    def test_load_secrets_yaml(self, temp_dir, valid_config):
        """vault/secrets.yamlからの読み込み"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        # vault/secrets.yamlを作成
        vault_dir = temp_dir / ".claude-nagger" / "vault"
        vault_dir.mkdir(parents=True)
        secrets_yaml = vault_dir / "secrets.yaml"
        secrets_yaml.write_text("""discord:
  webhook_url: "https://test.webhook.url"
  thread_id: "12345"
""", encoding="utf-8")

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            manager = ConfigManager(config_path=config_path)
            # secrets_pathを明示的に設定
            manager.secrets_path = secrets_yaml
            result = manager._load_secrets()

            assert result["discord"]["webhook_url"] == "https://test.webhook.url"
            assert result["discord"]["thread_id"] == "12345"
        finally:
            os.chdir(original_cwd)

    def test_find_secrets_file_vault_priority(self, temp_dir, valid_config):
        """vault/secrets.yamlが優先される"""
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(valid_config), encoding="utf-8")

        # vault/secrets.yamlを作成
        vault_dir = temp_dir / ".claude-nagger" / "vault"
        vault_dir.mkdir(parents=True)
        secrets_yaml = vault_dir / "secrets.yaml"
        secrets_yaml.write_text("discord:\n  webhook_url: test\n", encoding="utf-8")

        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            manager = ConfigManager(config_path=config_path)

            # vault/secrets.yamlが選択される
            assert manager.secrets_path == secrets_yaml
        finally:
            os.chdir(original_cwd)


class TestGetClaudeDir:
    """get_claude_dirメソッドのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_get_claude_dir_configured(self, temp_dir):
        """claude_dirが設定されている場合"""
        config_with_claude_dir = {
            "system": {
                "version": "1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./",
                "claude_dir": "/path/to/.claude"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(config_with_claude_dir), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)
        result = manager.get_claude_dir()

        assert result == Path("/path/to/.claude")

    def test_get_claude_dir_not_configured(self, temp_dir):
        """claude_dirが設定されていない場合はValueError"""
        config_without_claude_dir = {
            "system": {
                "version": "1.0.0",
                "rails_root": "./",
                "doc_root": "./docs",
                "scripts_root": "./"
            },
            "document": {
                "templates_dir": "templates",
                "output_dir": "output",
                "target_dirs": {}
            }
        }
        config_path = temp_dir / "config.json"
        config_path.write_text(json.dumps(config_without_claude_dir), encoding="utf-8")

        manager = ConfigManager(config_path=config_path)

        with pytest.raises(ValueError, match="claude_dirが設定されていません"):
            manager.get_claude_dir()
