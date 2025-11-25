"""設定管理モジュール"""

import os
import json
try:
    import json5
except ImportError:
    json5 = None
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigManager:
    """設定管理クラス
    
    config.json5の読み込みとパス解決を担当。
    パスは相対パス（main.pyからの相対）と絶対パスの両方をサポート。
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
        self.config_path = config_path or (self.base_dir / "config.json5")
        self.secrets_path = self.base_dir / "secrets.json5"
        self._config: Optional[Dict[str, Any]] = None
        self._secrets: Optional[Dict[str, Any]] = None

    @property
    def config(self) -> Dict[str, Any]:
        """設定を取得（遅延読み込み）"""
        if self._config is None:
            self._config = self._load_config()
        return self._config

    def _load_config(self) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if self.config_path.suffix == '.json5' and json5:
                    return json5.loads(content)
                else:
                    return json.loads(content)
        except FileNotFoundError:
            print(f"⚠️ 設定ファイルが見つかりません: {self.config_path}")
            return self._get_default_config()
        except Exception as e:
            print(f"❌ 設定ファイル読み込みエラー: {e}")
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
                    "rules": "../docs/rules",
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

    def _load_secrets(self) -> Dict[str, Any]:
        """機密情報ファイル（secrets.json5）を読み込み"""
        if self.secrets_path.exists():
            try:
                with open(self.secrets_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if self.secrets_path.suffix == '.json5' and json5:
                        return json5.loads(content)
                    else:
                        return json.loads(content)
            except Exception:
                pass
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