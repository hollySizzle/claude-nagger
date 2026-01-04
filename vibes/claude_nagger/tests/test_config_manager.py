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
