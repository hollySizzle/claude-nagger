"""診断コマンドのテスト"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

# srcディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from application.diagnose import DiagnoseCommand


class TestDiagnoseCommand:
    """DiagnoseCommandのテスト"""

    def test_execute_returns_zero(self, tmp_path, capsys, monkeypatch):
        """executeは正常終了時に0を返す"""
        monkeypatch.chdir(tmp_path)
        cmd = DiagnoseCommand()
        result = cmd.execute()
        assert result == 0

    def test_prints_environment_info(self, tmp_path, capsys, monkeypatch):
        """環境情報を出力する"""
        monkeypatch.chdir(tmp_path)
        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "## 環境情報" in captured.out
        assert "OS:" in captured.out
        assert "Python:" in captured.out

    def test_prints_installation_info(self, tmp_path, capsys, monkeypatch):
        """インストール情報を出力する"""
        monkeypatch.chdir(tmp_path)
        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "## インストール状態" in captured.out
        assert "claude-nagger:" in captured.out

    def test_detects_missing_settings_json(self, tmp_path, capsys, monkeypatch):
        """settings.jsonが存在しない場合を検出する"""
        monkeypatch.chdir(tmp_path)
        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "状態: 未作成" in captured.out
        assert ".claude/settings.json が存在しません" in captured.out

    def test_validates_settings_json(self, tmp_path, capsys, monkeypatch):
        """settings.jsonを検証する"""
        monkeypatch.chdir(tmp_path)

        # .claude/settings.jsonを作成
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings = {"hooks": {"PreToolUse": [{"command": "test"}]}}
        (claude_dir / "settings.json").write_text(json.dumps(settings))

        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "状態: OK" in captured.out
        assert "PreToolUse: 1 件" in captured.out

    def test_detects_invalid_json(self, tmp_path, capsys, monkeypatch):
        """不正なJSONを検出する"""
        monkeypatch.chdir(tmp_path)

        # 不正なJSONを作成
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{invalid json")

        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "JSON パースエラー" in captured.out

    def test_detects_missing_nagger_config(self, tmp_path, capsys, monkeypatch):
        """claude-nagger設定ディレクトリがない場合を検出する"""
        monkeypatch.chdir(tmp_path)
        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "ディレクトリなし" in captured.out
        assert ".claude-nagger/ ディレクトリが存在しません" in captured.out

    def test_validates_yaml_configs(self, tmp_path, capsys, monkeypatch):
        """YAML設定ファイルを検証する"""
        monkeypatch.chdir(tmp_path)

        # .claude-nagger/を作成
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        (nagger_dir / "config.yaml").write_text("key: value\n")

        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "config.yaml: OK" in captured.out

    def test_detects_invalid_yaml(self, tmp_path, capsys, monkeypatch):
        """不正なYAMLを検出する"""
        monkeypatch.chdir(tmp_path)

        # 不正なYAMLを作成
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        (nagger_dir / "config.yaml").write_text("key: [invalid yaml")

        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "YAML構文エラー" in captured.out

    def test_prints_issues_summary(self, tmp_path, capsys, monkeypatch):
        """検出した問題のサマリーを出力する"""
        monkeypatch.chdir(tmp_path)
        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "検出された問題" in captured.out

    def test_no_issues_when_all_ok(self, tmp_path, capsys, monkeypatch):
        """問題がない場合は「問題なし」を表示する"""
        monkeypatch.chdir(tmp_path)

        # 全設定を作成（正しいmatcher設定を含む）
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        settings_json = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "",
                        "hooks": [{"type": "command", "command": "claude-nagger hook session-startup"}]
                    },
                    {
                        "matcher": "Edit",
                        "hooks": [{"type": "command", "command": "claude-nagger hook implementation-design"}]
                    },
                    {
                        "matcher": "Write",
                        "hooks": [{"type": "command", "command": "claude-nagger hook implementation-design"}]
                    },
                    {
                        "matcher": "Bash",
                        "hooks": [{"type": "command", "command": "claude-nagger hook implementation-design"}]
                    },
                    {
                        "matcher": "mcp__.*__write.*",
                        "hooks": [{"type": "command", "command": "claude-nagger hook implementation-design"}]
                    },
                    {
                        "matcher": "mcp__.*replace.*",
                        "hooks": [{"type": "command", "command": "claude-nagger hook implementation-design"}]
                    },
                    {
                        "matcher": "mcp__.*insert.*",
                        "hooks": [{"type": "command", "command": "claude-nagger hook implementation-design"}]
                    }
                ]
            }
        }
        import json
        (claude_dir / "settings.json").write_text(json.dumps(settings_json))

        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        (nagger_dir / "config.yaml").write_text("key: value\n")
        (nagger_dir / "file_conventions.yaml").write_text("rules: []\n")
        (nagger_dir / "command_conventions.yaml").write_text("rules: []\n")

        cmd = DiagnoseCommand()
        cmd.execute()

        captured = capsys.readouterr()
        assert "問題は検出されませんでした" in captured.out


class TestCLIDiagnose:
    """CLIからのdiagnoseコマンドテスト"""

    def test_cli_diagnose_command(self, tmp_path, capsys, monkeypatch):
        """CLIからdiagnoseコマンドを実行できる"""
        from application.cli import main

        monkeypatch.chdir(tmp_path)
        with patch.object(sys, 'argv', ['claude-nagger', 'diagnose']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        # バージョン付きフォーマット: "claude-nagger v{version} 診断レポート"
        assert "claude-nagger v" in captured.out
        assert "診断レポート" in captured.out
