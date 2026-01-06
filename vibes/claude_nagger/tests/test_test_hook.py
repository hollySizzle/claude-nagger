"""test-hookコマンドのテスト"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from application.test_hook import TestHookCommand


class TestTestHookCommand:
    """TestHookCommandのテスト"""

    def test_execute_returns_zero(self, tmp_path, capsys, monkeypatch):
        """正常実行時は0を返す"""
        monkeypatch.chdir(tmp_path)
        cmd = TestHookCommand(tool="Bash", command="git status")
        result = cmd.execute()

        assert result == 0

    def test_displays_test_conditions(self, tmp_path, capsys, monkeypatch):
        """テスト条件を表示する"""
        monkeypatch.chdir(tmp_path)
        cmd = TestHookCommand(tool="Edit", file_path="test.py")
        cmd.execute()

        captured = capsys.readouterr()
        assert "テスト条件" in captured.out
        assert "ツール: Edit" in captured.out
        assert "ファイル: test.py" in captured.out

    def test_detects_missing_settings_json(self, tmp_path, capsys, monkeypatch):
        """settings.jsonが存在しない場合を検出"""
        monkeypatch.chdir(tmp_path)
        cmd = TestHookCommand(tool="Bash", command="ls")
        cmd.execute()

        captured = capsys.readouterr()
        assert "settings.json が存在しません" in captured.out

    def test_matcher_check_with_empty_matcher(self, tmp_path, capsys, monkeypatch):
        """空文字matcherがある場合のチェック"""
        monkeypatch.chdir(tmp_path)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "test-hook"}]
                    }
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        cmd = TestHookCommand(tool="AnyTool")
        cmd.execute()

        captured = capsys.readouterr()
        assert "1 件のフックがマッチ" in captured.out
        assert '""（全ツール）' in captured.out

    def test_matcher_check_with_specific_matcher(self, tmp_path, capsys, monkeypatch):
        """特定ツールのmatcherがある場合のチェック"""
        monkeypatch.chdir(tmp_path)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "bash-hook"}]
                    }
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        cmd = TestHookCommand(tool="Bash")
        cmd.execute()

        captured = capsys.readouterr()
        assert "1 件のフックがマッチ" in captured.out
        assert '"Bash"' in captured.out

    def test_matcher_check_no_match(self, tmp_path, capsys, monkeypatch):
        """matcherがない場合のチェック"""
        monkeypatch.chdir(tmp_path)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "OtherTool",
                        "hooks": [{"type": "command", "command": "other-hook"}]
                    }
                ]
            }
        }
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        cmd = TestHookCommand(tool="Bash")
        cmd.execute()

        captured = capsys.readouterr()
        assert "マッチするmatcherなし" in captured.out

    def test_command_conventions_check(self, tmp_path, capsys, monkeypatch):
        """command_conventions.yamlのチェック"""
        monkeypatch.chdir(tmp_path)

        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        (nagger_dir / "command_conventions.yaml").write_text("""
rules:
  - name: "Git操作規約"
    patterns:
      - "git *"
    severity: "block"
    message: "Git操作には注意が必要です"
""")

        cmd = TestHookCommand(tool="Bash", command="git status")
        cmd.execute()

        captured = capsys.readouterr()
        assert "Git操作規約" in captured.out or "マッチするルールなし" in captured.out

    def test_missing_command_conventions(self, tmp_path, capsys, monkeypatch):
        """command_conventions.yamlがない場合"""
        monkeypatch.chdir(tmp_path)
        cmd = TestHookCommand(tool="Bash", command="ls")
        cmd.execute()

        captured = capsys.readouterr()
        assert "command_conventions.yaml が存在しません" in captured.out


class TestCLITestHook:
    """CLIからのtest-hookコマンドテスト"""

    def test_cli_test_hook_command(self, tmp_path, capsys, monkeypatch):
        """CLIからtest-hookコマンドを実行できる"""
        from application.cli import main

        monkeypatch.chdir(tmp_path)
        with patch.object(sys, 'argv', ['claude-nagger', 'test-hook', '-t', 'Bash', '-c', 'ls']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "フック発火テスト" in captured.out

    def test_cli_test_hook_with_file(self, tmp_path, capsys, monkeypatch):
        """CLIからファイルオプション付きで実行"""
        from application.cli import main

        monkeypatch.chdir(tmp_path)
        with patch.object(sys, 'argv', ['claude-nagger', 'test-hook', '-t', 'Edit', '--file', 'test.py']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "ファイル: test.py" in captured.out
