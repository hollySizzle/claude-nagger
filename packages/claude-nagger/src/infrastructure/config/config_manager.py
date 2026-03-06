"""設定管理モジュール"""

import os
import json
import logging

logger = logging.getLogger(__name__)

try:
    import json5
except ImportError:
    json5 = None
try:
    import yaml
except ImportError:
    yaml = None
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """設定管理クラス
    
    設定ファイル（YAML/JSON5/JSON）の読み込みとパス解決を担当。
    パスは相対パス（main.pyからの相対）と絶対パスの両方をサポート。
    
    設定ファイル優先順位: config.yaml > config.yml > config.json5
    """

    def __init__(self, config_path: Optional[Path] = None):
        """初期化
        
        Args:
            config_path: 設定ファイルパス（省略時はデフォルト）
        """
        # main.pyの位置を基準とする（scripts/ディレクトリ）
        # __file__ は src/infrastructure/config/config_manager.py
        # parent.parent.parent = src/infrastructure/config -> src/infrastructure -> src
        # parent.parent.parent.parent = scripts/
        self.base_dir = Path(__file__).parent.parent.parent.parent  # scripts/
        
        if config_path is None:
            # 設定ファイル探索順序: yaml > yml > json5
            # プロジェクト固有設定（.claude-nagger/）を優先
            config_path = self._find_config_file()
        
        self.config_path = config_path
        self.secrets_path = self._find_secrets_file()
        self._config: Optional[Dict[str, Any]] = None
        self._secrets: Optional[Dict[str, Any]] = None

    def _find_secrets_file(self) -> Path:
        """secretsファイルを探索
        
        探索順序（優先度高い順）:
        1. .claude-nagger/vault/secrets.yaml
        2. .claude-nagger/vault/secrets.yml
        3. secrets.json5（後方互換）
        
        Returns:
            見つかった機密ファイルパス（見つからない場合はデフォルト）
        """
        # 探索対象の拡張子（優先度順）
        extensions = ['.yaml', '.yml']
        
        # CLAUDE_PROJECT_DIRを優先、フォールバックはcwd
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base_path = Path(project_dir) if project_dir else Path.cwd()
        project_vault_dir = base_path / ".claude-nagger" / "vault"
        for ext in extensions:
            secrets_file = project_vault_dir / f"secrets{ext}"
            if secrets_file.exists():
                return secrets_file
        
        # 後方互換: secrets.json5
        legacy_secrets = self.base_dir / "secrets.json5"
        if legacy_secrets.exists():
            return legacy_secrets
        
        # デフォルトは新しいパス
        return project_vault_dir / "secrets.yaml"

    def _find_config_file(self) -> Path:
        """設定ファイルを探索
        
        探索順序（優先度高い順）:
        1. .claude-nagger/config.yaml
        2. .claude-nagger/config.yml
        3. .claude-nagger/config.json5
        4. base_dir/config.yaml
        5. base_dir/config.yml
        6. base_dir/config.json5
        
        Returns:
            見つかった設定ファイルパス（見つからない場合はデフォルト）
        """
        # 探索対象の拡張子（優先度順）
        extensions = ['.yaml', '.yml', '.json5']
        
        # CLAUDE_PROJECT_DIRを優先、フォールバックはcwd
        project_dir_env = os.environ.get("CLAUDE_PROJECT_DIR")
        base_path = Path(project_dir_env) if project_dir_env else Path.cwd()
        project_dir = base_path / ".claude-nagger"
        for ext in extensions:
            config_file = project_dir / f"config{ext}"
            if config_file.exists():
                return config_file
        
        # パッケージ内デフォルトを探索
        for ext in extensions:
            config_file = self.base_dir / f"config{ext}"
            if config_file.exists():
                return config_file
        
        # どれも見つからない場合はデフォルトパス
        return self.base_dir / "config.json5"

    @property
    def config(self) -> Dict[str, Any]:
        """設定を取得（遅延読み込み）"""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> Dict[str, Any]:
        """設定ファイルを読み込み
        
        対応形式: YAML (.yaml, .yml), JSON5 (.json5), JSON (.json)
        設定が空または不完全な場合はデフォルト設定にフォールバック
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                suffix = self.config_path.suffix.lower()
                
                # YAML形式
                if suffix in ('.yaml', '.yml'):
                    if yaml:
                        config = yaml.safe_load(content)
                    else:
                        raise ImportError("PyYAMLがインストールされていません")
                # JSON5形式
                elif suffix == '.json5' and json5:
                    config = json5.loads(content)
                # JSON形式（フォールバック）
                else:
                    config = json.loads(content)
                
                # 空または不完全な設定の場合はデフォルトにフォールバック
                if not config or not isinstance(config, dict) or "system" not in config:
                    return self._get_default_config()
                
                return config
        except FileNotFoundError:
            print(f"⚠️ 設定ファイルが見つかりません: {self.config_path}")
            return self._get_default_config()
        except (json.JSONDecodeError, yaml.YAMLError if yaml else Exception) as e:
            print(f"❌ 設定ファイル構文エラー ({self.config_path}): {e}")
            return self._get_default_config()
        except Exception as e:
            print(f"❌ 設定ファイル読み込みエラー ({self.config_path}): {e}")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """デフォルト設定を返す"""
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
                    "rules": "vibes/docs/rules",
                    "specs": "../docs/specs",
                    "tasks": "../docs/tasks",
                    "logics": "../docs/logics",
                    "apis": "../docs/apis"
                }
            }
        }

    def resolve_path(self, path_str: str) -> Path:
        """パスを解決
        
        相対パスはmain.pyからの相対として解決。
        絶対パスはそのまま使用。
        
        Args:
            path_str: パス文字列
            
        Returns:
            解決済みのPathオブジェクト
        """
        path = Path(path_str)
        
        # 絶対パスの場合はそのまま返す
        if path.is_absolute():
            return path
        
        # 相対パスの場合はbase_dirからの相対として解決
        return (self.base_dir / path).resolve()

    def get_rails_root(self) -> Path:
        """Railsルートディレクトリを取得"""
        return self.resolve_path(self.config["system"]["rails_root"])

    def get_doc_root(self) -> Path:
        """ドキュメントルートディレクトリを取得"""
        return self.resolve_path(self.config["system"]["doc_root"])

    def get_scripts_root(self) -> Path:
        """スクリプトルートディレクトリを取得"""
        return self.resolve_path(self.config["system"]["scripts_root"])

    def get_templates_dir(self) -> Path:
        """テンプレートディレクトリを取得"""
        return self.resolve_path(self.config["document"]["templates_dir"])

    def get_output_dir(self) -> Path:
        """出力ディレクトリを取得"""
        return self.resolve_path(self.config["document"]["output_dir"])

    def get_target_dir(self, category: str) -> Optional[Path]:
        """カテゴリごとのターゲットディレクトリを取得
        
        Args:
            category: rules, specs, tasks, logics, apis のいずれか
            
        Returns:
            ディレクトリパス（カテゴリが無効な場合はNone）
        """
        target_dirs = self.config["document"].get("target_dirs", {})
        if category in target_dirs:
            return self.resolve_path(target_dirs[category])
        return None

    def get_all_target_dirs(self) -> Dict[str, Path]:
        """全ターゲットディレクトリを取得"""
        target_dirs = self.config["document"].get("target_dirs", {})
        return {
            category: self.resolve_path(path_str)
            for category, path_str in target_dirs.items()
        }

    def get_hook_settings(self) -> Dict[str, Any]:
        """フック設定を取得"""
        return self.config.get("hooks", {})
    
    def get_convention_hook_settings(self) -> Dict[str, Any]:
        """規約Hook設定を取得"""
        return self.config.get("convention_hooks", {})
    
    def get_context_thresholds(self) -> Dict[str, int]:
        """コンテキスト閾値設定を取得"""
        return self.config.get("convention_hooks", {}).get("context_management", {}).get("thresholds", {
            "light_warning": 30000,
            "medium_warning": 60000,
            "critical_warning": 100000,
            "final_warning": 140000,
            "compaction_threshold": 160000
        })
    
    def get_marker_settings(self) -> Dict[str, Any]:
        """マーカー管理設定を取得"""
        return self.config.get("convention_hooks", {}).get("context_management", {}).get("marker_management", {
            "enabled": True
        })
    
    def get_display_level_config(self, level: str) -> Dict[str, bool]:
        """表示レベル設定を取得"""
        return self.config.get("convention_hooks", {}).get("display_levels", {}).get(level, {})

    def get_trusted_prefixes(self) -> Dict[str, str]:
        """role_resolution.trusted_prefixesを取得

        agent_typeの前方一致でroleを確定するためのマッピング。
        未定義時は空dict（フォールバック動作に影響なし）。

        Returns:
            prefix → role のマッピング
        """
        prefixes = self.config.get("role_resolution", {}).get("trusted_prefixes", {})
        if not isinstance(prefixes, dict):
            logger.warning(f"trusted_prefixesの型が不正（dict期待）: {type(prefixes)}")
            return {}
        return prefixes

    def get_permission_mode_behaviors(self) -> Dict[str, str]:
        """permission_mode別の挙動設定を取得

        設定例:
        ```yaml
        permission_mode_behaviors:
          bypassPermissions: skip      # 全スキップ
          dontAsk: warn_only           # 警告のみ（ブロックしない）
          default: normal              # 通常処理
          plan: normal                 # 通常処理
          acceptEdits: normal          # 通常処理
        ```

        Returns:
            モード名 -> 挙動名のマッピング
        """
        return self.config.get("permission_mode_behaviors", {})

    def _load_secrets(self) -> Dict[str, Any]:
        """機密情報ファイルを読み込み
        
        対応形式: YAML (.yaml, .yml), JSON5 (.json5), JSON (.json)
        """
        if self.secrets_path.exists():
            try:
                with open(self.secrets_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    suffix = self.secrets_path.suffix.lower()
                    
                    # YAML形式
                    if suffix in ('.yaml', '.yml'):
                        if yaml:
                            return yaml.safe_load(content) or {}
                        else:
                            raise ImportError("PyYAMLがインストールされていません")
                    # JSON5形式
                    elif suffix == '.json5' and json5:
                        return json5.loads(content)
                    # JSON形式（フォールバック）
                    else:
                        return json.loads(content)
            except Exception as e:
                logger.warning(f"secrets読み込み失敗（{self.secrets_path}）: {e}")
        return {}
    
    def _resolve_value(self, value: Any) -> Any:
        """設定値を解決（環境変数展開）
        
        優先順位:
        1. 環境変数（os.environ）
        2. secrets.json5
        3. デフォルト値
        """
        if isinstance(value, str) and value.startswith('${') and value.endswith('}'):
            var_name = value[2:-1]
            
            # 1. 環境変数から取得
            if var_name in os.environ:
                return os.environ[var_name]
            
            # 2. secrets.json5から取得（ネストされたキーに対応）
            if self._secrets is None:
                self._secrets = self._load_secrets()
            
            # DISCORD_WEBHOOK_URL -> discord.webhook_url のような変換
            if '_' in var_name:
                parts = var_name.lower().split('_')
                if len(parts) >= 2:
                    section = parts[0]  # discord
                    key = '_'.join(parts[1:])  # webhook_url または thread_id
                    if section in self._secrets and key in self._secrets[section]:
                        return self._secrets[section][key]
            
            # 値が見つからない場合は空文字列
            return ''
        
        # 辞書の場合は再帰的に処理
        if isinstance(value, dict):
            return {k: self._resolve_value(v) for k, v in value.items()}
        
        # リストの場合も再帰的に処理
        if isinstance(value, list):
            return [self._resolve_value(item) for item in value]
        
        return value
    
    def get_notification_settings(self) -> Dict[str, Any]:
        """通知設定を取得（環境変数展開済み）"""
        settings = self.config.get("notifications", {})
        return self._resolve_value(settings)
    
    def get_claude_dir(self) -> Path:
        """.claudeディレクトリのパスを取得"""
        # 設定ファイルから取得、なければNone
        claude_dir = self.config.get("system", {}).get("claude_dir", None)
        if claude_dir is None:
            raise ValueError("claude_dirが設定されていません。config.json5で設定してください。")
        return Path(claude_dir)

    def interactive_setup(self):
        """対話的セットアップ"""
        import questionary
        
        print("\n🔧 システム設定")
        print("-" * 40)
        
        # 現在の設定を表示
        print("\n📁 現在のパス設定:")
        print(f"  Rails Root: {self.get_rails_root()}")
        print(f"  Doc Root: {self.get_doc_root()}")
        print(f"  Scripts Root: {self.get_scripts_root()}")
        
        print("\n📚 ドキュメントディレクトリ:")
        for category, path in self.get_all_target_dirs().items():
            print(f"  {category}: {path}")
        
        # 設定変更の確認
        if questionary.confirm("\n設定を変更しますか？", default=False).ask():
            self._update_config_interactive()
        else:
            print("✅ 現在の設定を維持します")

    def _update_config_interactive(self):
        """対話的に設定を更新"""
        print("\n⚠️ 設定変更機能は開発中です")
        print("直接 config.json5 を編集してください")