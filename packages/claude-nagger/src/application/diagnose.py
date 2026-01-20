"""診断コマンド - 環境情報・設定の収集"""

import json
import logging
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DiagnoseCommand:
    """環境診断コマンド"""

    # 診断対象の主要ツール（matcherが登録されるべきツール）
    EXPECTED_TOOL_MATCHERS = [
        ("Edit", "ファイル編集"),
        ("Write", "ファイル書き込み"),
        ("Bash", "コマンド実行"),
        ("mcp__.*__write.*", "MCP書き込み（正規表現）"),
        ("mcp__.*replace.*", "MCP置換（正規表現）"),
        ("mcp__.*insert.*", "MCP挿入（正規表現）"),
    ]

    def __init__(self):
        self.cwd = Path.cwd()
        self.issues: list[str] = []

    def execute(self) -> int:
        """診断を実行"""
        from shared.version import __version__
        print("=" * 60)
        print(f"claude-nagger v{__version__} 診断レポート")
        print("=" * 60)
        print()

        self._print_environment()
        self._print_installation()
        self._print_settings_json()
        self._print_hook_matchers()  # 新規追加
        self._print_nagger_config()
        self._print_convention_status()  # 新規追加
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

        # インストール場所の検出（複数方法を試行）
        install_location = self._detect_install_location()
        if install_location:
            print(f"インストール場所: {install_location}")
        else:
            print("インストール方式: uv tool / pipx（グローバルインストール）")

        # claude-nagger コマンドの存在確認
        try:
            result = subprocess.run(
                ["which", "claude-nagger"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                cmd_path = result.stdout.strip()
                print(f"コマンドパス: {cmd_path}")
            else:
                print("コマンドパス: 未検出")
        except Exception as e:
            logger.debug(f"whichコマンド実行失敗: {e}")
        print()

    def _detect_install_location(self) -> str | None:
        """インストール場所を複数方法で検出"""
        # 1. pip show を試す
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
                        return line.split(': ', 1)[1]
        except Exception as e:
            logger.debug(f"pip show実行失敗: {e}")

        # 2. uv tool list を試す
        try:
            result = subprocess.run(
                ["uv", "tool", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and "claude-nagger" in result.stdout:
                return None  # uv tool でインストールされている
        except Exception as e:
            logger.debug(f"uv tool list実行失敗: {e}")

        # 3. pipx list を試す
        try:
            result = subprocess.run(
                ["pipx", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0 and "claude-nagger" in result.stdout:
                return None  # pipx でインストールされている
        except Exception as e:
            logger.debug(f"pipx list実行失敗: {e}")

        return None

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

    def _print_hook_matchers(self) -> None:
        """フックmatcher登録状況を出力"""
        print("## フック動作チェック")

        settings_path = self.cwd / ".claude" / "settings.json"
        if not settings_path.exists():
            print("  settings.json が存在しないため確認不可")
            print()
            return

        try:
            import re
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})
            pretooluse_hooks = hooks.get("PreToolUse", [])

            # 登録されているmatcherを収集（フック種別で分類）
            registered_matchers: dict[str, list[str]] = {}
            for hook_entry in pretooluse_hooks:
                matcher = hook_entry.get("matcher", "")
                hook_types = []
                for hook in hook_entry.get("hooks", []):
                    cmd = hook.get("command", "")
                    # フック種別を判定
                    if "implementation-design" in cmd or "implementation_design" in cmd:
                        hook_types.append("implementation-design")
                    elif "session-startup" in cmd or "session_startup" in cmd:
                        hook_types.append("session-startup")
                    else:
                        # その他のフック
                        hook_types.append(cmd.split()[-1] if cmd else "unknown")
                if hook_types:
                    registered_matchers[matcher] = hook_types

            # implementation-designが必要なツールを定義
            tools_needing_impl_design = [
                ("Edit", "ファイル編集"),
                ("Write", "ファイル書き込み"),
                ("Bash", "コマンド実行"),
            ]

            print("  [implementation-design フック対応状況]")
            for tool_name, tool_desc in tools_needing_impl_design:
                has_impl_design = False
                matched_via = None

                for matcher, hooks_list in registered_matchers.items():
                    if "implementation-design" not in hooks_list:
                        continue

                    # 完全一致チェック
                    if matcher == tool_name:
                        has_impl_design = True
                        matched_via = f'"{matcher}"'
                        break
                    # 正規表現matcherがツール名にマッチするか
                    elif self._is_regex_pattern(matcher):
                        try:
                            if re.match(f"^{matcher}$", tool_name):
                                has_impl_design = True
                                matched_via = f'"{matcher}"'
                                break
                        except re.error as e:
                            logger.warning(f"正規表現パターン不正（{matcher}）: {e}")

                if has_impl_design:
                    print(f"    {tool_name} ({tool_desc}): ✅ OK (via {matched_via})")
                else:
                    print(f"    {tool_name} ({tool_desc}): ❌ matcher未登録")
                    self.issues.append(f"{tool_name} → implementation-design: matcher未登録")

            # MCP正規表現matcherの状況
            print()
            print("  [MCP系正規表現matcher]")
            mcp_patterns = [
                ("mcp__.*__write.*", "MCP書き込み"),
                ("mcp__.*replace.*", "MCP置換"),
                ("mcp__.*insert.*", "MCP挿入"),
            ]
            for pattern, desc in mcp_patterns:
                if pattern in registered_matchers:
                    hooks_list = registered_matchers[pattern]
                    print(f"    {pattern}: ✅ {', '.join(hooks_list)}")
                else:
                    print(f"    {pattern}: ❌ 未登録")

            # session-startup（全ツール用）
            print()
            print("  [session-startup フック（全ツール）]")
            if "" in registered_matchers and "session-startup" in registered_matchers[""]:
                print("    ✅ 登録済み")
            else:
                print("    ❌ 未登録")
                self.issues.append("session-startup フックが未登録")

            # 登録済みmatcher一覧
            print()
            print("  [登録済みmatcher一覧]")
            for matcher, hooks_list in registered_matchers.items():
                matcher_display = f'"{matcher}"' if matcher else '""（全ツール）'
                print(f"    {matcher_display} → {', '.join(hooks_list)}")

        except json.JSONDecodeError:
            print("  settings.json のパースに失敗")
        except Exception as e:
            print(f"  確認エラー: {e}")
        print()

    def _is_regex_pattern(self, pattern: str) -> bool:
        """パターンが正規表現かどうかを判定"""
        regex_chars = ['*', '+', '?', '[', ']', '(', ')', '{', '}', '|', '^', '$', '.']
        return any(c in pattern for c in regex_chars)

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

    def _print_convention_status(self) -> None:
        """規約ファイルの動作状況を出力"""
        print("## 規約動作状況")

        nagger_dir = self.cwd / ".claude-nagger"

        # file_conventions.yaml の確認
        file_conv_path = nagger_dir / "file_conventions.yaml"
        if file_conv_path.exists():
            try:
                from domain.services.file_convention_matcher import FileConventionMatcher
                matcher = FileConventionMatcher()
                rules = matcher.list_rules()
                print(f"  file_conventions.yaml: {len(rules)} ルール登録")
                for rule in rules[:3]:  # 最大3件表示
                    print(f"    - {rule['name']} ({rule['severity']})")
                if len(rules) > 3:
                    print(f"    ... 他{len(rules) - 3}件")
            except Exception as e:
                print(f"  file_conventions.yaml: 読み込みエラー ({e})")
        else:
            print("  file_conventions.yaml: 未作成（ファイル規約なし）")

        # command_conventions.yaml の確認
        cmd_conv_path = nagger_dir / "command_conventions.yaml"
        if cmd_conv_path.exists():
            try:
                from domain.services.command_convention_matcher import CommandConventionMatcher
                matcher = CommandConventionMatcher()
                rules = matcher.list_rules()
                print(f"  command_conventions.yaml: {len(rules)} ルール登録")
                for rule in rules[:3]:  # 最大3件表示
                    print(f"    - {rule['name']} ({rule['severity']})")
                if len(rules) > 3:
                    print(f"    ... 他{len(rules) - 3}件")

                # Bash matcherが未登録の場合の警告
                settings_path = self.cwd / ".claude" / "settings.json"
                if settings_path.exists():
                    settings = json.loads(settings_path.read_text())
                    hooks = settings.get("hooks", {})
                    pretooluse = hooks.get("PreToolUse", [])
                    bash_registered = any(
                        h.get("matcher") == "Bash"
                        for h in pretooluse
                    )
                    if not bash_registered and rules:
                        print("  ⚠️ 警告: command_conventions.yaml は設定済みですが、")
                        print("          Bash用matcherが未登録のため動作しません")
                        print("          → `claude-nagger install-hooks` を再実行してください")
                        self.issues.append("command_conventions.yaml が設定済みだがBash matcherが未登録")
            except Exception as e:
                print(f"  command_conventions.yaml: 読み込みエラー ({e})")
        else:
            print("  command_conventions.yaml: 未作成（コマンド規約なし）")
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
