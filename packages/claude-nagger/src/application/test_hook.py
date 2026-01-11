"""フックテストコマンド - 指定ツール・コマンドに対するフック発火をテスト"""

import json
import re
from pathlib import Path
from typing import Any


class TestHookCommand:
    """フック発火テストコマンド"""

    def __init__(self, tool: str, command: str | None = None, file_path: str | None = None):
        self.tool = tool
        self.command = command
        self.file_path = file_path
        self.cwd = Path.cwd()

    def execute(self) -> int:
        """テストを実行"""
        print("=" * 60)
        print("claude-nagger フック発火テスト")
        print("=" * 60)
        print()

        print(f"## テスト条件")
        print(f"ツール: {self.tool}")
        if self.command:
            print(f"コマンド: {self.command}")
        if self.file_path:
            print(f"ファイル: {self.file_path}")
        print()

        # 1. settings.json のmatcherチェック
        self._test_settings_matcher()

        # 2. コマンド規約チェック（Bashツールの場合）
        if self.tool == "Bash" and self.command:
            self._test_command_conventions()

        # 3. ファイル規約チェック（Edit/Writeツールの場合）
        if self.tool in ["Edit", "Write"] and self.file_path:
            self._test_file_conventions()

        return 0

    def _test_settings_matcher(self) -> None:
        """settings.jsonのmatcherチェック"""
        print("## settings.json matcherチェック")

        settings_path = self.cwd / ".claude" / "settings.json"
        if not settings_path.exists():
            print("  ❌ settings.json が存在しません")
            return

        try:
            settings = json.loads(settings_path.read_text())
            hooks = settings.get("hooks", {})
            pretooluse_hooks = hooks.get("PreToolUse", [])

            matched_hooks = []
            for hook_entry in pretooluse_hooks:
                matcher = hook_entry.get("matcher", "")
                if self._matches_tool(matcher, self.tool):
                    for hook in hook_entry.get("hooks", []):
                        cmd = hook.get("command", "")
                        matched_hooks.append({
                            "matcher": matcher,
                            "command": cmd
                        })

            if matched_hooks:
                print(f"  ✅ {len(matched_hooks)} 件のフックがマッチ")
                for i, h in enumerate(matched_hooks, 1):
                    matcher_display = f'"{h["matcher"]}"' if h["matcher"] else '""（全ツール）'
                    print(f"    {i}. matcher: {matcher_display}")
                    print(f"       → {h['command']}")
            else:
                print(f"  ❌ ツール '{self.tool}' にマッチするmatcherなし")
                print("     → install-hooks を再実行してください")

        except Exception as e:
            print(f"  エラー: {e}")
        print()

    def _matches_tool(self, matcher: str, tool: str) -> bool:
        """matcherがツールにマッチするか判定"""
        if not matcher:
            # 空文字matcherは全ツールにマッチ
            return True
        try:
            return bool(re.match(f"^{matcher}$", tool))
        except re.error:
            return matcher == tool

    def _test_command_conventions(self) -> None:
        """コマンド規約チェック"""
        print("## command_conventions.yaml チェック")

        nagger_dir = self.cwd / ".claude-nagger"
        conv_path = nagger_dir / "command_conventions.yaml"

        if not conv_path.exists():
            print("  command_conventions.yaml が存在しません")
            print()
            return

        try:
            from domain.services.command_convention_matcher import CommandConventionMatcher
            matcher = CommandConventionMatcher()
            rule_info = matcher.get_confirmation_message(self.command)

            if rule_info:
                print(f"  ✅ マッチしたルール: {rule_info['rule_name']}")
                print(f"     重要度: {rule_info['severity']}")
                print(f"     メッセージ: {rule_info['message'][:80]}...")
            else:
                print(f"  ❌ コマンド '{self.command}' にマッチするルールなし")

        except Exception as e:
            print(f"  エラー: {e}")
        print()

    def _test_file_conventions(self) -> None:
        """ファイル規約チェック"""
        print("## file_conventions.yaml チェック")

        nagger_dir = self.cwd / ".claude-nagger"
        conv_path = nagger_dir / "file_conventions.yaml"

        if not conv_path.exists():
            print("  file_conventions.yaml が存在しません")
            print()
            return

        try:
            from domain.services.file_convention_matcher import FileConventionMatcher
            matcher = FileConventionMatcher()
            rule_info = matcher.get_confirmation_message(self.file_path)

            if rule_info:
                print(f"  ✅ マッチしたルール: {rule_info['rule_name']}")
                print(f"     重要度: {rule_info['severity']}")
                print(f"     メッセージ: {rule_info['message'][:80]}...")
            else:
                print(f"  ❌ ファイル '{self.file_path}' にマッチするルールなし")

        except Exception as e:
            print(f"  エラー: {e}")
        print()
