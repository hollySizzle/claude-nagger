"""SuggestRulesTrigger 単体テスト"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from domain.hooks.suggest_rules_trigger import (
    SuggestRulesTrigger,
    run_background_analysis,
    _build_prompt,
    _extract_yaml_from_output,
    _fallback_yaml,
    _save_suggested_rules,
    main,
)
from domain.services.rule_suggester import PatternSuggestion


# === フィクスチャ ===

@pytest.fixture
def tmp_log_dir(tmp_path):
    """テスト用ログディレクトリ"""
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    return log_dir


def _create_hook_inputs(log_dir: Path, count: int) -> None:
    """hook_input JSONファイルをN件作成"""
    for i in range(count):
        filepath = log_dir / f"hook_input_sess_{i:04d}.json"
        filepath.write_text(json.dumps({
            "tool_name": "Edit",
            "tool_input": {"file_path": f"/path/to/file_{i}.py"},
        }), encoding="utf-8")


# === 初期化テスト ===

class TestInit:
    """初期化のテスト"""

    def test_デフォルト値で初期化(self):
        """デフォルト値が正しく設定される"""
        hook = SuggestRulesTrigger()
        assert hook.min_inputs == 10
        assert hook.model == "sonnet"
        assert hook.debug is True

    def test_カスタム値で初期化(self):
        """カスタム値が正しく反映される"""
        hook = SuggestRulesTrigger(min_inputs=5, model="haiku")
        assert hook.min_inputs == 5
        assert hook.model == "haiku"


# === should_processテスト ===

class TestShouldProcess:
    """should_processメソッドのテスト"""

    def test_閾値未満でFalse(self, tmp_log_dir):
        """hook_input件数が閾値未満の場合False"""
        _create_hook_inputs(tmp_log_dir, 5)
        hook = SuggestRulesTrigger(min_inputs=10)
        hook.log_dir = tmp_log_dir

        result = hook.should_process({})
        assert result is False

    def test_閾値以上でTrue(self, tmp_log_dir):
        """hook_input件数が閾値以上の場合True"""
        _create_hook_inputs(tmp_log_dir, 10)
        hook = SuggestRulesTrigger(min_inputs=10)
        hook.log_dir = tmp_log_dir

        result = hook.should_process({})
        assert result is True

    def test_0件でFalse(self, tmp_log_dir):
        """hook_inputが0件の場合False"""
        hook = SuggestRulesTrigger(min_inputs=10)
        hook.log_dir = tmp_log_dir

        result = hook.should_process({})
        assert result is False

    def test_閾値ちょうどでTrue(self, tmp_log_dir):
        """hook_input件数がちょうど閾値の場合True"""
        _create_hook_inputs(tmp_log_dir, 5)
        hook = SuggestRulesTrigger(min_inputs=5)
        hook.log_dir = tmp_log_dir

        result = hook.should_process({})
        assert result is True


# === _count_hook_inputsテスト ===

class TestCountHookInputs:
    """_count_hook_inputsメソッドのテスト"""

    def test_正確な件数カウント(self, tmp_log_dir):
        """hook_input_*.jsonの正確な件数を返す"""
        _create_hook_inputs(tmp_log_dir, 7)
        hook = SuggestRulesTrigger()
        hook.log_dir = tmp_log_dir

        assert hook._count_hook_inputs() == 7

    def test_非対象ファイルは除外(self, tmp_log_dir):
        """hook_input_*.json以外のファイルは除外"""
        _create_hook_inputs(tmp_log_dir, 3)
        # 無関係なファイルを作成
        (tmp_log_dir / "other_file.json").write_text("{}")
        (tmp_log_dir / "hook_input.txt").write_text("not json")

        hook = SuggestRulesTrigger()
        hook.log_dir = tmp_log_dir

        assert hook._count_hook_inputs() == 3


# === processテスト ===

class TestProcess:
    """processメソッドのテスト"""

    def test_バックグラウンド起動してapprove返却(self):
        """_launch_backgroundを呼びapproveを返す"""
        hook = SuggestRulesTrigger()
        hook._launch_background = MagicMock()

        result = hook.process({})

        hook._launch_background.assert_called_once()
        assert result["decision"] == "approve"


# === _launch_backgroundテスト ===

class TestLaunchBackground:
    """_launch_backgroundメソッドのテスト"""

    @patch("domain.hooks.suggest_rules_trigger.subprocess.Popen")
    def test_nohupでプロセス起動(self, mock_popen):
        """nohupでバックグラウンドプロセスが起動される"""
        hook = SuggestRulesTrigger(model="sonnet")
        hook._launch_background()

        mock_popen.assert_called_once()
        args = mock_popen.call_args
        cmd = args[0][0]
        assert cmd[0] == "nohup"
        assert "--background" in cmd
        assert "--model" in cmd
        assert "sonnet" in cmd
        assert args[1]["start_new_session"] is True
        assert args[1]["stdout"] == subprocess.DEVNULL
        assert args[1]["stderr"] == subprocess.DEVNULL

    @patch("domain.hooks.suggest_rules_trigger.subprocess.Popen", side_effect=Exception("test error"))
    def test_起動失敗時にエラーログ(self, mock_popen):
        """プロセス起動失敗時にエラーをログ出力"""
        hook = SuggestRulesTrigger()
        # 例外が外に伝播しないことを確認
        hook._launch_background()


# === _build_promptテスト ===

class TestBuildPrompt:
    """_build_prompt関数のテスト"""

    def test_ファイル候補を含むプロンプト(self):
        """ファイルパターンがプロンプトに含まれる"""
        suggestions = [
            PatternSuggestion(
                category="file", pattern="src/**/*.py",
                count=15, examples=["src/main.py", "src/app.py"]
            ),
        ]
        stats = {"total_inputs": 20, "file_inputs": 15, "command_inputs": 5}

        prompt = _build_prompt(suggestions, [], stats)

        assert "src/**/*.py" in prompt
        assert "15回" in prompt
        assert "20件" in prompt
        assert "src/main.py" in prompt

    def test_コマンド候補を含むプロンプト(self):
        """コマンドパターンがプロンプトに含まれる"""
        suggestions = [
            PatternSuggestion(
                category="command", pattern="git *",
                count=8, examples=["git status", "git diff"]
            ),
        ]
        stats = {"total_inputs": 10, "file_inputs": 2, "command_inputs": 8}

        prompt = _build_prompt([], suggestions, stats)

        assert "git *" in prompt
        assert "8回" in prompt
        assert "git status" in prompt

    def test_YAML出力形式の指示を含む(self):
        """YAML出力形式の指示がプロンプトに含まれる"""
        stats = {"total_inputs": 5, "file_inputs": 5, "command_inputs": 0}
        prompt = _build_prompt([], [], stats)

        assert "```yaml" in prompt
        assert "rules:" in prompt

    def test_空の候補リストでもプロンプト生成(self):
        """候補が空でもプロンプトが生成される"""
        stats = {"total_inputs": 0, "file_inputs": 0, "command_inputs": 0}
        prompt = _build_prompt([], [], stats)
        assert "統計分析結果" in prompt


# === _extract_yaml_from_outputテスト ===

class TestExtractYamlFromOutput:
    """_extract_yaml_from_output関数のテスト"""

    def test_yamlブロック抽出(self):
        """```yaml ... ``` ブロックからYAMLを抽出"""
        output = """分析結果です。

```yaml
rules:
  - name: "テスト規約"
    patterns:
      - "*.py"
    severity: warn
    message: "テストメッセージ"
```

以上です。"""

        result = _extract_yaml_from_output(output)
        assert result is not None
        assert "rules:" in result
        assert "テスト規約" in result

    def test_ブロックなしでrules検出(self):
        """```ブロックなしでもrules:で始まる内容を抽出"""
        output = """以下が提案です。
rules:
  - name: "規約A"
    severity: warn"""

        result = _extract_yaml_from_output(output)
        assert result is not None
        assert "rules:" in result

    def test_YAML無しでNone返却(self):
        """YAML形式が見つからない場合None"""
        output = "この入力には規約候補が見つかりませんでした。"
        result = _extract_yaml_from_output(output)
        assert result is None

    def test_空文字列でNone(self):
        """空文字列の場合None"""
        result = _extract_yaml_from_output("")
        assert result is None


# === _fallback_yamlテスト ===

class TestFallbackYaml:
    """_fallback_yaml関数のテスト"""

    def test_ファイル規約のフォールバック出力(self):
        """ファイルパターンからフォールバックYAMLを生成"""
        suggestions = [
            PatternSuggestion(
                category="file", pattern="src/**/*.py", count=10, examples=[]
            ),
        ]
        stats = {"total_inputs": 10}

        result = _fallback_yaml(suggestions, [], stats)

        assert "suggest-rules 自動提案（Python統計のみ）" in result
        assert "src/**/*.py 編集規約" in result
        assert "claude CLIが見つからない" in result

    def test_コマンド規約のフォールバック出力(self):
        """コマンドパターンからフォールバックYAMLを生成"""
        suggestions = [
            PatternSuggestion(
                category="command", pattern="npm *", count=5, examples=[]
            ),
        ]
        stats = {"total_inputs": 5}

        result = _fallback_yaml([], suggestions, stats)

        assert "npm * コマンド規約" in result

    def test_0件で空文字列(self):
        """候補が0件の場合空文字列"""
        result = _fallback_yaml([], [], {"total_inputs": 0})
        assert result == ""

    def test_最大10件に制限(self):
        """上位10件に制限"""
        suggestions = [
            PatternSuggestion(
                category="file", pattern=f"pattern_{i}", count=20 - i, examples=[]
            )
            for i in range(15)
        ]
        stats = {"total_inputs": 100}

        result = _fallback_yaml(suggestions, [], stats)

        # 最初の10件は含まれる
        for i in range(10):
            assert f"pattern_{i}" in result
        # 11件目以降は含まれない
        for i in range(10, 15):
            assert f"pattern_{i}" not in result

    def test_ファイルとコマンド混合で合計10件に制限(self):
        """file + command合計で10件に制限（頻度順）"""
        file_suggestions = [
            PatternSuggestion(
                category="file", pattern=f"file_{i}", count=20 - i, examples=[]
            )
            for i in range(8)
        ]
        command_suggestions = [
            PatternSuggestion(
                category="command", pattern=f"cmd_{i}", count=15 - i, examples=[]
            )
            for i in range(8)
        ]
        stats = {"total_inputs": 100}

        result = _fallback_yaml(file_suggestions, command_suggestions, stats)

        # 合計10件に制限されていること
        assert result.count("編集規約") + result.count("コマンド規約") == 10
        # 頻度が高いものが優先されること（file_0=20, file_1=19, ...）
        assert "file_0" in result
        assert "cmd_0" in result


# === _save_suggested_rulesテスト ===

class TestSaveSuggestedRules:
    """_save_suggested_rules関数のテスト"""

    def test_ファイル保存(self, tmp_path):
        """suggested_rules.yamlが正しく保存される"""
        with patch("domain.hooks.suggest_rules_trigger.Path.cwd", return_value=tmp_path):
            content = "rules:\n  - name: test\n"
            path = _save_suggested_rules(content)

            assert path.exists()
            assert path.name == "suggested_rules.yaml"
            assert path.read_text(encoding="utf-8") == content

    def test_ヘッダ付き保存(self, tmp_path):
        """ヘッダ付きで保存される"""
        with patch("domain.hooks.suggest_rules_trigger.Path.cwd", return_value=tmp_path):
            content = "rules:\n  - name: test\n"
            header = "# header\n"
            path = _save_suggested_rules(content, header)

            saved = path.read_text(encoding="utf-8")
            assert saved.startswith("# header")
            assert "rules:" in saved

    def test_claude_naggerディレクトリ自動作成(self, tmp_path):
        """.claude-naggerディレクトリが存在しなくても作成"""
        with patch("domain.hooks.suggest_rules_trigger.Path.cwd", return_value=tmp_path):
            content = "test content"
            path = _save_suggested_rules(content)

            assert (tmp_path / ".claude-nagger").is_dir()
            assert path.exists()


# === run_background_analysisテスト ===

class TestRunBackgroundAnalysis:
    """run_background_analysis関数のテスト"""

    @patch("domain.hooks.suggest_rules_trigger.RuleSuggester")
    def test_候補なしで正常終了(self, MockSuggester):
        """分析結果が空の場合0を返す"""
        mock_instance = MockSuggester.return_value
        mock_instance.analyze.return_value = {
            "file_suggestions": [],
            "command_suggestions": [],
            "stats": {"total_inputs": 5},
        }

        result = run_background_analysis()
        assert result == 0

    @patch("domain.hooks.suggest_rules_trigger._save_suggested_rules")
    @patch("domain.hooks.suggest_rules_trigger.shutil.which", return_value=None)
    @patch("domain.hooks.suggest_rules_trigger.RuleSuggester")
    def test_claude_CLI非存在時フォールバック(
        self, MockSuggester, mock_which, mock_save
    ):
        """claude CLIが見つからない場合フォールバック出力"""
        mock_instance = MockSuggester.return_value
        mock_instance.analyze.return_value = {
            "file_suggestions": [
                PatternSuggestion("file", "*.py", 10, [])
            ],
            "command_suggestions": [],
            "stats": {"total_inputs": 15, "file_inputs": 15, "command_inputs": 0},
        }

        result = run_background_analysis()

        assert result == 0
        mock_save.assert_called_once()
        saved_content = mock_save.call_args[0][0]
        assert "Python統計のみ" in saved_content

    @patch("domain.hooks.suggest_rules_trigger._save_suggested_rules")
    @patch("domain.hooks.suggest_rules_trigger.subprocess.run")
    @patch("domain.hooks.suggest_rules_trigger.shutil.which", return_value="/usr/bin/claude")
    @patch("domain.hooks.suggest_rules_trigger.RuleSuggester")
    def test_claude_print成功時LLM出力保存(
        self, MockSuggester, mock_which, mock_run, mock_save
    ):
        """claude --print成功時にLLM分析結果を保存"""
        mock_instance = MockSuggester.return_value
        mock_instance.analyze.return_value = {
            "file_suggestions": [
                PatternSuggestion("file", "src/*.py", 12, ["src/main.py"])
            ],
            "command_suggestions": [],
            "stats": {"total_inputs": 20, "file_inputs": 20, "command_inputs": 0},
        }

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="""分析結果:

```yaml
rules:
  - name: "Python編集規約"
    patterns:
      - "src/*.py"
    severity: warn
    message: "規約を確認してください"
```
""",
            stderr="",
        )

        result = run_background_analysis(model="sonnet")

        assert result == 0
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "/usr/bin/claude" in cmd
        assert "--model" in cmd
        assert "sonnet" in cmd
        mock_save.assert_called_once()

    @patch("domain.hooks.suggest_rules_trigger._save_suggested_rules")
    @patch("domain.hooks.suggest_rules_trigger.subprocess.run")
    @patch("domain.hooks.suggest_rules_trigger.shutil.which", return_value="/usr/bin/claude")
    @patch("domain.hooks.suggest_rules_trigger.RuleSuggester")
    def test_claude_print失敗時フォールバック(
        self, MockSuggester, mock_which, mock_run, mock_save
    ):
        """claude --print失敗時にフォールバック使用"""
        mock_instance = MockSuggester.return_value
        mock_instance.analyze.return_value = {
            "file_suggestions": [
                PatternSuggestion("file", "*.py", 10, [])
            ],
            "command_suggestions": [],
            "stats": {"total_inputs": 15, "file_inputs": 15, "command_inputs": 0},
        }

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="error occurred",
        )

        result = run_background_analysis()

        assert result == 0
        mock_save.assert_called_once()
        saved_content = mock_save.call_args[0][0]
        assert "Python統計のみ" in saved_content

    @patch("domain.hooks.suggest_rules_trigger._save_suggested_rules")
    @patch("domain.hooks.suggest_rules_trigger.subprocess.run")
    @patch("domain.hooks.suggest_rules_trigger.shutil.which", return_value="/usr/bin/claude")
    @patch("domain.hooks.suggest_rules_trigger.RuleSuggester")
    def test_YAML抽出失敗時フォールバック(
        self, MockSuggester, mock_which, mock_run, mock_save
    ):
        """claude出力からYAML抽出できない場合フォールバック使用"""
        mock_instance = MockSuggester.return_value
        mock_instance.analyze.return_value = {
            "file_suggestions": [
                PatternSuggestion("file", "*.py", 10, [])
            ],
            "command_suggestions": [],
            "stats": {"total_inputs": 15, "file_inputs": 15, "command_inputs": 0},
        }

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="規約候補が見つかりませんでした。",
            stderr="",
        )

        result = run_background_analysis()

        assert result == 0
        mock_save.assert_called_once()
        saved_content = mock_save.call_args[0][0]
        assert "Python統計のみ" in saved_content

    @patch("domain.hooks.suggest_rules_trigger._save_suggested_rules")
    @patch("domain.hooks.suggest_rules_trigger.subprocess.run")
    @patch("domain.hooks.suggest_rules_trigger.shutil.which", return_value="/usr/bin/claude")
    @patch("domain.hooks.suggest_rules_trigger.RuleSuggester")
    def test_不正YAML時フォールバック(
        self, MockSuggester, mock_which, mock_run, mock_save
    ):
        """抽出YAMLが構文不正の場合フォールバック使用"""
        mock_instance = MockSuggester.return_value
        mock_instance.analyze.return_value = {
            "file_suggestions": [
                PatternSuggestion("file", "*.py", 10, [])
            ],
            "command_suggestions": [],
            "stats": {"total_inputs": 15, "file_inputs": 15, "command_inputs": 0},
        }

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="""```yaml
rules:
  - name: "テスト
    invalid: [yaml
```
""",
            stderr="",
        )

        result = run_background_analysis()

        assert result == 0
        mock_save.assert_called_once()
        saved_content = mock_save.call_args[0][0]
        assert "Python統計のみ" in saved_content

    @patch("domain.hooks.suggest_rules_trigger.RuleSuggester")
    def test_例外発生時エラー返却(self, MockSuggester):
        """予期しない例外発生時に1を返す"""
        MockSuggester.side_effect = Exception("unexpected error")

        result = run_background_analysis()
        assert result == 1


# === mainテスト ===

class TestMain:
    """mainエントリーポイントのテスト"""

    @patch("domain.hooks.suggest_rules_trigger.SuggestRulesTrigger")
    def test_通常モードでhook実行(self, MockTrigger):
        """引数なしの場合Stopフックとして実行"""
        mock_instance = MockTrigger.return_value
        mock_instance.run.return_value = 0

        with patch("sys.argv", ["suggest_rules_trigger"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            mock_instance.run.assert_called_once()
            assert exc_info.value.code == 0

    @patch("domain.hooks.suggest_rules_trigger.run_background_analysis", return_value=0)
    def test_backgroundモードで分析実行(self, mock_bg):
        """--backgroundフラグでバックグラウンド処理実行"""
        with patch("sys.argv", ["suggest_rules_trigger", "--background", "--model", "haiku"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            mock_bg.assert_called_once_with(model="haiku")
            assert exc_info.value.code == 0
