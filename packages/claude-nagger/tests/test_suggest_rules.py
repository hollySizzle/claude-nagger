"""SuggestRulesCommand 単体テスト"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from application.suggest_rules import SuggestRulesCommand
from domain.services.rule_suggester import PatternSuggestion


# === フィクスチャ ===

@pytest.fixture
def tmp_log_dir(tmp_path):
    """テスト用ログディレクトリ"""
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    return log_dir


def _write_hook_input(log_dir: Path, data: dict, session_id: str = "sess1", index: int = 0) -> Path:
    """hook_input JSONファイルを書き出すヘルパー"""
    filepath = log_dir / f"hook_input_{session_id}_{index:04d}.json"
    filepath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return filepath


def _create_file_inputs(log_dir: Path, paths: list[str], session_id: str = "sess1"):
    """ファイル編集のhook_inputを一括作成"""
    for i, path in enumerate(paths):
        _write_hook_input(log_dir, {
            "tool_name": "Edit",
            "tool_input": {"file_path": path},
        }, session_id=session_id, index=i)


def _create_command_inputs(log_dir: Path, commands: list[str], session_id: str = "sess1", start_index: int = 0):
    """コマンド実行のhook_inputを一括作成"""
    for i, cmd in enumerate(commands):
        _write_hook_input(log_dir, {
            "tool_name": "Bash",
            "tool_input": {"command": cmd},
        }, session_id=session_id, index=start_index + i)


# === executeテスト ===

class TestExecute:
    """CLIコマンド実行テスト"""

    def test_0件時のメッセージ(self, tmp_log_dir, capsys):
        """分析対象なしで適切なメッセージ出力"""
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": [],
                "command_suggestions": [],
                "stats": {"total_inputs": 0},
            }
            cmd = SuggestRulesCommand()
            result = cmd.execute()

        assert result == 0
        captured = capsys.readouterr()
        assert "規約候補は見つかりませんでした" in captured.err
        assert "hook入力JSONがありません" in captured.err

    def test_0件_入力ありmin_count未満(self, capsys):
        """入力はあるがmin-count未満で0件"""
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": [
                    PatternSuggestion(category="file", pattern="src/**/*.py", count=2, examples=[]),
                ],
                "command_suggestions": [],
                "stats": {"total_inputs": 5},
            }
            cmd = SuggestRulesCommand(min_count=3)
            result = cmd.execute()

        assert result == 0
        captured = capsys.readouterr()
        assert "規約候補は見つかりませんでした" in captured.err
        assert "min-count=3" in captured.err

    def test_ファイル規約のYAML出力(self, capsys):
        """ファイル規約候補のYAML出力"""
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": [
                    PatternSuggestion(
                        category="file",
                        pattern="src/domain/hooks/**/*.py",
                        count=12,
                        examples=["src/domain/hooks/base_hook.py"],
                    ),
                ],
                "command_suggestions": [],
                "stats": {"total_inputs": 42},
            }
            cmd = SuggestRulesCommand(min_count=3)
            result = cmd.execute()

        assert result == 0
        captured = capsys.readouterr()
        assert "# suggest-rules 出力" in captured.out
        assert "# 分析対象: 42件のhook入力JSON" in captured.out
        assert "src/domain/hooks/**/*.py" in captured.out
        assert "12回の編集を検出" in captured.out
        assert "severity: warn" in captured.out

    def test_コマンド規約のYAML出力(self, capsys):
        """コマンド規約候補のYAML出力"""
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": [],
                "command_suggestions": [
                    PatternSuggestion(
                        category="command",
                        pattern="npm test",
                        count=5,
                        examples=["npm test -- --watch"],
                    ),
                ],
                "stats": {"total_inputs": 20},
            }
            cmd = SuggestRulesCommand(min_count=3)
            result = cmd.execute()

        assert result == 0
        captured = capsys.readouterr()
        assert "npm test コマンド規約" in captured.out
        assert "5回の実行を検出" in captured.out

    def test_typeフィルタ_file(self, capsys):
        """--type file でファイル規約のみ出力"""
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": [
                    PatternSuggestion(category="file", pattern="src/**/*.py", count=10, examples=[]),
                ],
                "command_suggestions": [
                    PatternSuggestion(category="command", pattern="npm", count=8, examples=[]),
                ],
                "stats": {"total_inputs": 30},
            }
            cmd = SuggestRulesCommand(min_count=1, rule_type="file")
            result = cmd.execute()

        assert result == 0
        captured = capsys.readouterr()
        assert "src/**/*.py" in captured.out
        assert "npm" not in captured.out

    def test_typeフィルタ_command(self, capsys):
        """--type command でコマンド規約のみ出力"""
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": [
                    PatternSuggestion(category="file", pattern="src/**/*.py", count=10, examples=[]),
                ],
                "command_suggestions": [
                    PatternSuggestion(category="command", pattern="npm", count=8, examples=[]),
                ],
                "stats": {"total_inputs": 30},
            }
            cmd = SuggestRulesCommand(min_count=1, rule_type="command")
            result = cmd.execute()

        assert result == 0
        captured = capsys.readouterr()
        assert "npm" in captured.out
        assert "src/**/*.py" not in captured.out

    def test_topN制限(self, capsys):
        """--top N で上位N件のみ出力"""
        file_suggestions = [
            PatternSuggestion(category="file", pattern=f"dir{i}/**/*.py", count=100 - i, examples=[])
            for i in range(5)
        ]
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": file_suggestions,
                "command_suggestions": [],
                "stats": {"total_inputs": 50},
            }
            cmd = SuggestRulesCommand(min_count=1, top=2)
            result = cmd.execute()

        assert result == 0
        captured = capsys.readouterr()
        assert "dir0/**/*.py" in captured.out
        assert "dir1/**/*.py" in captured.out
        assert "dir2/**/*.py" not in captured.out

    def test_sessionオプション渡し(self):
        """--session がRuleSuggesterに正しく渡される"""
        with patch("application.suggest_rules.RuleSuggester") as MockSuggester:
            mock_instance = MockSuggester.return_value
            mock_instance.analyze.return_value = {
                "file_suggestions": [],
                "command_suggestions": [],
                "stats": {"total_inputs": 0},
            }
            cmd = SuggestRulesCommand(session_id="abc123")
            cmd.execute()

        MockSuggester.assert_called_once_with(session_id="abc123")


# === _format_yaml テスト ===

class TestFormatYaml:
    """YAML出力フォーマットテスト"""

    def test_ヘッダにメタ情報(self):
        """ヘッダにコメント行でメタ情報を含む"""
        cmd = SuggestRulesCommand()
        result = cmd._format_yaml([], [], {"total_inputs": 42})
        assert "# suggest-rules 出力" in result
        assert "# 生成日:" in result
        assert "# 分析対象: 42件のhook入力JSON" in result

    def test_ファイル規約の構造(self):
        """ファイル規約の出力構造"""
        cmd = SuggestRulesCommand()
        suggestion = PatternSuggestion(
            category="file",
            pattern="src/**/*.py",
            count=10,
            examples=["src/a.py"],
        )
        result = cmd._format_yaml([suggestion], [], {"total_inputs": 10})
        assert "patterns:" in result
        assert "- src/**/*.py" in result
        assert "severity: warn" in result

    def test_コマンド規約の構造(self):
        """コマンド規約の出力構造"""
        cmd = SuggestRulesCommand()
        suggestion = PatternSuggestion(
            category="command",
            pattern="git push",
            count=5,
            examples=["git push origin main"],
        )
        result = cmd._format_yaml([], [suggestion], {"total_inputs": 5})
        assert "commands:" in result
        assert "- git push" in result


# === _suggestion_to_rule テスト ===

class TestSuggestionToRule:
    """PatternSuggestion→ルール辞書変換テスト"""

    def test_ファイル規約変換(self):
        """ファイル規約のルール辞書"""
        suggestion = PatternSuggestion(
            category="file", pattern="src/**/*.py", count=7, examples=[]
        )
        rule = SuggestRulesCommand._suggestion_to_rule(suggestion)
        assert rule["name"] == "src/**/*.py 編集規約"
        assert rule["patterns"] == ["src/**/*.py"]
        assert rule["severity"] == "warn"
        assert "7回の編集を検出" in rule["message"]

    def test_コマンド規約変換(self):
        """コマンド規約のルール辞書"""
        suggestion = PatternSuggestion(
            category="command", pattern="docker", count=4, examples=[]
        )
        rule = SuggestRulesCommand._suggestion_to_rule(suggestion)
        assert rule["name"] == "docker コマンド規約"
        assert rule["commands"] == ["docker"]
        assert "4回の実行を検出" in rule["message"]
