"""診断コマンド - 環境情報・設定の収集"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


class DiagnoseCommand:
    """環境診断コマンド"""

    def __init__(self):
        self.cwd = Path.cwd()
        self.issues: list[str] = []

    def execute(self) -> int:
        """診断を実行"""
        print("=" * 60)
        print("claude-nagger 診断レポート")
        print("=" * 60)
        print()

        self._print_environment()
        self._print_installation()
        self._print_settings_json()
        self._print_nagger_config()
        self._print_hook_files()
        self._print_session_files()
        self._print_issues_summary()

        return 0

    def _print_environment(self) -> None:
        """環境情報を出力"""
        print("## 環境情報")
        print(f"OS: {platform.system()} {platform.release()}")
        print(f"Python: {sys.version.split()[0]}")
        print(f"Python Path: {sys.executable}")
        print(f"作業ディレクトリ: {self.cwd}")
        print()

    def _print_installation(self) -> None:
        """インストール情報を出力"""
        print("## インストール状態")

        # claude-nagger バージョン
        try:
            from shared.version import __version__
            print(f"claude-nagger: {__version__}")
        except ImportError:
            print("claude-nagger: バージョン取得失敗")
            self.issues.append("バージョン情報の取得に失敗")

        # インストール場所
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "show", "claude-nagger"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("Location:"):
                        print(f"インストール場所: {line.split(': ', 1)[1]}")
                        break
            else:
                print("インストール場所: 不明（pip show 失敗）")
        except Exception as e:
            print(f"インストール場所: 確認失敗 ({e})")
        print()

    def _print_settings_json(self) -> None:
        """settings.json の状態を出力"""
        print("## .claude/settings.json")

        settings_path = self.cwd / ".claude" / "settings.json"
        if not settings_path.exists():
            print("状態: 未作成")
            self.issues.append(".claude/settings.json が存在しません")
            print()
            return

        try:
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})

            if not hooks:
                print("状態: hooks セクションなし")
                self.issues.append("hooks が設定されていません")
            else:
                print("状態: OK")
                print(f"登録フック数: {sum(len(v) for v in hooks.values())}")
                for hook_type, hook_list in hooks.items():
                    print(f"  - {hook_type}: {len(hook_list)} 件")
        except json.JSONDecodeError as e:
            print(f"状態: JSON パースエラー")
            self.issues.append(f"settings.json のJSON形式が不正: {e}")
        except Exception as e:
            print(f"状態: 読み込みエラー ({e})")
            self.issues.append(f"settings.json の読み込み失敗: {e}")
        print()

    def _print_nagger_config(self) -> None:
        """claude-nagger 設定ファイルの状態を出力"""
        print("## .claude-nagger/ 設定")

        nagger_dir = self.cwd / ".claude-nagger"
        if not nagger_dir.exists():
            print("状態: ディレクトリなし")
            self.issues.append(".claude-nagger/ ディレクトリが存在しません")
            print()
            return

        config_files = [
            "config.yaml",
            "file_conventions.yaml",
            "command_conventions.yaml"
        ]

        for config_file in config_files:
            config_path = nagger_dir / config_file
            if config_path.exists():
                self._validate_yaml(config_path)
            else:
                print(f"  {config_file}: 未作成")
        print()

    def _validate_yaml(self, path: Path) -> None:
        """YAMLファイルを検証"""
        try:
            import yaml
            yaml.safe_load(path.read_text())
            size = path.stat().st_size
            print(f"  {path.name}: OK ({size} bytes)")
        except ImportError:
            print(f"  {path.name}: 存在（YAML検証スキップ）")
        except yaml.YAMLError as e:
            print(f"  {path.name}: YAML構文エラー")
            self.issues.append(f"{path.name} のYAML構文エラー: {e}")
        except Exception as e:
            print(f"  {path.name}: 読み込みエラー ({e})")

    def _print_hook_files(self) -> None:
        """フックスクリプトの状態を出力"""
        print("## フックスクリプト")

        # 主要なフックスクリプトを確認
        hook_patterns = [
            "src/domain/hooks/pre_tool_use_hook.py",
            "src/domain/hooks/session_startup_hook.py",
        ]

        found_any = False
        for pattern in hook_patterns:
            # インストール済みパッケージからの相対パス確認
            try:
                from domain.hooks import pre_tool_use_hook
                print(f"  pre_tool_use_hook: インポート可能")
                found_any = True
            except ImportError:
                pass

            # カレントディレクトリからの確認
            local_path = self.cwd / pattern
            if local_path.exists():
                print(f"  {pattern}: 存在")
                found_any = True

        if not found_any:
            print("  フックスクリプト: 見つかりません")
        print()

    def _print_session_files(self) -> None:
        """セッションファイルの状態を出力"""
        print("## セッション・ログ")

        tmp_claude = Path("/tmp/claude")
        if not tmp_claude.exists():
            print("  /tmp/claude/: なし")
            print()
            return

        session_files = list(tmp_claude.glob("claude_nagger_session_*.json"))
        log_files = list(tmp_claude.glob("claude_nagger_*.log"))

        print(f"  セッションファイル: {len(session_files)} 件")
        print(f"  ログファイル: {len(log_files)} 件")

        # 最新のセッションファイルを表示
        if session_files:
            latest = max(session_files, key=lambda p: p.stat().st_mtime)
            print(f"  最新セッション: {latest.name}")
        print()

    def _print_issues_summary(self) -> None:
        """検出した問題のサマリーを出力"""
        print("=" * 60)
        if self.issues:
            print(f"## 検出された問題 ({len(self.issues)} 件)")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
            print()
            print("詳細は docs/TROUBLESHOOTING.md を参照してください")
        else:
            print("## 問題は検出されませんでした")
        print("=" * 60)
