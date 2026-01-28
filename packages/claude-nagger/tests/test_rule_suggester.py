"""RuleSuggester 単体テスト"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from domain.services.rule_suggester import RuleSuggester, PatternSuggestion


# === フィクスチャ ===

@pytest.fixture
def tmp_log_dir(tmp_path):
    """テスト用ログディレクトリ"""
    log_dir = tmp_path / "log"
    log_dir.mkdir()
    return log_dir


@pytest.fixture
def mock_file_matcher():
    """既存ルールなしのFileConventionMatcherモック"""
    matcher = MagicMock()
    matcher.list_rules.return_value = []
    return matcher


@pytest.fixture
def mock_command_matcher():
    """既存ルールなしのCommandConventionMatcherモック"""
    matcher = MagicMock()
    matcher.list_rules.return_value = []
    return matcher


@pytest.fixture
def suggester(tmp_log_dir, mock_file_matcher, mock_command_matcher):
    """標準テスト用RuleSuggester"""
    return RuleSuggester(
        log_dir=tmp_log_dir,
        cwd=Path("/workspace/vibes/claude_nagger"),
        file_matcher=mock_file_matcher,
        command_matcher=mock_command_matcher,
    )


def _write_hook_input(log_dir: Path, data: dict, index: int = 0) -> Path:
    """hook_input JSONファイルを書き出すヘルパー"""
    filepath = log_dir / f"hook_input_test_{index}.json"
    filepath.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return filepath


# === _load_hook_inputs テスト ===

class TestLoadHookInputs:
    """hook_input JSON読込テスト"""

    def test_空ディレクトリ(self, suggester):
        """ファイルなしの場合は空リスト"""
        result = suggester._load_hook_inputs()
        assert result == []

    def test_正常読込(self, suggester, tmp_log_dir):
        """正常なJSONを読み込める"""
        data = {"tool_name": "Edit", "tool_input": {"file_path": "/workspace/test.py"}}
        _write_hook_input(tmp_log_dir, data)

        result = suggester._load_hook_inputs()
        assert len(result) == 1
        assert result[0]["tool_name"] == "Edit"

    def test_不正JSON_スキップ(self, suggester, tmp_log_dir):
        """不正JSONはスキップして続行"""
        # 正常ファイル
        _write_hook_input(tmp_log_dir, {"tool_name": "Edit", "tool_input": {}}, index=0)
        # 不正ファイル
        bad_file = tmp_log_dir / "hook_input_bad_1.json"
        bad_file.write_text("invalid json{{{", encoding="utf-8")

        result = suggester._load_hook_inputs()
        assert len(result) == 1

    def test_複数ファイル読込(self, suggester, tmp_log_dir):
        """複数ファイルを全件読込"""
        for i in range(5):
            _write_hook_input(tmp_log_dir, {"tool_name": "Bash", "tool_input": {"command": f"cmd{i}"}}, index=i)

        result = suggester._load_hook_inputs()
        assert len(result) == 5

    def test_session_idフィルタ(self, tmp_log_dir, mock_file_matcher, mock_command_matcher):
        """session_id指定時は該当セッションのファイルのみ読込"""
        # セッションA: 3件
        for i in range(3):
            filepath = tmp_log_dir / f"hook_input_sessA_{i:04d}.json"
            filepath.write_text(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": f"/a{i}.py"}}))
        # セッションB: 2件
        for i in range(2):
            filepath = tmp_log_dir / f"hook_input_sessB_{i:04d}.json"
            filepath.write_text(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": f"/b{i}.py"}}))

        # session_id=sessA でフィルタ
        s = RuleSuggester(
            log_dir=tmp_log_dir, cwd=Path("/workspace"),
            file_matcher=mock_file_matcher, command_matcher=mock_command_matcher,
            session_id="sessA",
        )
        result = s._load_hook_inputs()
        assert len(result) == 3

    def test_session_id未指定で全件読込(self, tmp_log_dir, mock_file_matcher, mock_command_matcher):
        """session_id未指定時は全セッションのファイルを読込"""
        for sid, count in [("sessA", 3), ("sessB", 2)]:
            for i in range(count):
                filepath = tmp_log_dir / f"hook_input_{sid}_{i:04d}.json"
                filepath.write_text(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": f"/{sid}{i}.py"}}))

        s = RuleSuggester(
            log_dir=tmp_log_dir, cwd=Path("/workspace"),
            file_matcher=mock_file_matcher, command_matcher=mock_command_matcher,
        )
        result = s._load_hook_inputs()
        assert len(result) == 5


# === _classify_inputs テスト ===

class TestClassifyInputs:
    """入力分類テスト"""

    def test_Edit_はファイル分類(self, suggester):
        """Editツールはファイルパスとして分類"""
        inputs = [{"tool_name": "Edit", "tool_input": {"file_path": "/workspace/test.py"}}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == ["/workspace/test.py"]
        assert commands == []

    def test_Write_はファイル分類(self, suggester):
        """Writeツールはファイルパスとして分類"""
        inputs = [{"tool_name": "Write", "tool_input": {"file_path": "/workspace/new.py"}}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == ["/workspace/new.py"]
        assert commands == []

    def test_Bash_はコマンド分類(self, suggester):
        """Bashツールはコマンドとして分類"""
        inputs = [{"tool_name": "Bash", "tool_input": {"command": "python3 test.py"}}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == []
        assert commands == ["python3 test.py"]

    def test_Read_は除外(self, suggester):
        """Readツールは対象外"""
        inputs = [{"tool_name": "Read", "tool_input": {"file_path": "/workspace/test.py"}}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == []
        assert commands == []

    def test_mcp_は除外(self, suggester):
        """mcp__*ツールは対象外"""
        inputs = [{"tool_name": "mcp__serena__read_file", "tool_input": {"relative_path": "src/test.py"}}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == []
        assert commands == []

    def test_混合入力(self, suggester):
        """複数種別の入力を正しく分類"""
        inputs = [
            {"tool_name": "Edit", "tool_input": {"file_path": "/workspace/a.py"}},
            {"tool_name": "Bash", "tool_input": {"command": "git status"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/workspace/b.py"}},
            {"tool_name": "Read", "tool_input": {"file_path": "/workspace/c.py"}},
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
        ]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert len(file_paths) == 2
        assert len(commands) == 2

    def test_空のtool_input(self, suggester):
        """tool_inputが空の場合はスキップ"""
        inputs = [
            {"tool_name": "Edit", "tool_input": {}},
            {"tool_name": "Bash", "tool_input": {}},
        ]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == []
        assert commands == []


# === _to_relative_path テスト ===

class TestToRelativePath:
    """パス変換テスト"""

    def test_絶対パスを相対変換(self, suggester):
        """cwd配下の絶対パスを相対パスに変換"""
        result = suggester._to_relative_path("/workspace/vibes/claude_nagger/src/domain/hooks/base_hook.py")
        assert result == "src/domain/hooks/base_hook.py"

    def test_cwd外のパスはそのまま(self, suggester):
        """cwd配下にないパスはそのまま返す"""
        result = suggester._to_relative_path("/other/project/file.py")
        assert result == "/other/project/file.py"

    def test_相対パスはそのまま(self, suggester):
        """既に相対パスならそのまま"""
        result = suggester._to_relative_path("src/test.py")
        assert result == "src/test.py"


# === _aggregate_file_patterns テスト ===

class TestAggregateFilePatterns:
    """ファイルパターン集約テスト"""

    def test_同一ディレクトリ同拡張子_集約(self, suggester):
        """同ディレクトリ・同拡張子は1つのglobパターンに集約"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/domain/hooks/base_hook.py",
            "/workspace/vibes/claude_nagger/src/domain/hooks/session_startup_hook.py",
            "/workspace/vibes/claude_nagger/src/domain/hooks/compact_detected_hook.py",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        assert len(suggestions) == 1
        assert suggestions[0].pattern == "src/domain/hooks/**/*.py"
        assert suggestions[0].count == 3
        assert suggestions[0].category == "file"

    def test_異なるディレクトリは別パターン(self, suggester):
        """異なるディレクトリは別パターンとして集約"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/domain/hooks/base_hook.py",
            "/workspace/vibes/claude_nagger/src/domain/services/hook_manager.py",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        patterns = {s.pattern for s in suggestions}
        assert "src/domain/hooks/**/*.py" in patterns
        assert "src/domain/services/**/*.py" in patterns

    def test_異なる拡張子は別パターン(self, suggester):
        """異なる拡張子は別パターンとして集約"""
        file_paths = [
            "/workspace/vibes/claude_nagger/docs/specs/spec.pu",
            "/workspace/vibes/claude_nagger/docs/specs/spec.md",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        patterns = {s.pattern for s in suggestions}
        assert "docs/specs/**/*.pu" in patterns
        assert "docs/specs/**/*.md" in patterns

    def test_examples_最大3件(self, suggester):
        """examplesは最大3件まで"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/a.py",
            "/workspace/vibes/claude_nagger/src/b.py",
            "/workspace/vibes/claude_nagger/src/c.py",
            "/workspace/vibes/claude_nagger/src/d.py",
            "/workspace/vibes/claude_nagger/src/e.py",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        assert len(suggestions[0].examples) == 3

    def test_空リスト(self, suggester):
        """空リストの場合は空結果"""
        suggestions = suggester._aggregate_file_patterns([])
        assert suggestions == []


# === _extract_command_prefix テスト ===

class TestExtractCommandPrefix:
    """コマンドプレフィックス抽出テスト"""

    def test_単純コマンド(self, suggester):
        assert suggester._extract_command_prefix("python3 test.py") == "python3"

    def test_パイプ付きコマンド(self, suggester):
        assert suggester._extract_command_prefix("ls -la | head -30") == "ls"

    def test_gitコマンド(self, suggester):
        assert suggester._extract_command_prefix("git commit -m 'fix'") == "git"

    def test_リダイレクト付き(self, suggester):
        """パイプ前の最初のトークンを取得"""
        assert suggester._extract_command_prefix("python3 scripts/capture_fixture.py --sanitize -n 10 2>&1") == "python3"


# === _aggregate_command_prefixes テスト ===

class TestAggregateCommandPrefixes:
    """コマンドプレフィックス集約テスト"""

    def test_同一プレフィックス集約(self, suggester):
        """同じプレフィックスのコマンドを集約"""
        commands = [
            "python3 test1.py",
            "python3 test2.py",
            "python3 test3.py",
        ]
        suggestions = suggester._aggregate_command_prefixes(commands)
        assert len(suggestions) == 1
        assert suggestions[0].pattern == "python3*"
        assert suggestions[0].count == 3
        assert suggestions[0].category == "command"

    def test_異なるプレフィックスは別集約(self, suggester):
        """異なるプレフィックスは別パターン"""
        commands = [
            "git status",
            "git commit -m 'test'",
            "python3 test.py",
        ]
        suggestions = suggester._aggregate_command_prefixes(commands)
        patterns = {s.pattern for s in suggestions}
        assert "git*" in patterns
        assert "python3*" in patterns

    def test_長いコマンドのexample切り詰め(self, suggester):
        """100文字超のコマンドは...で切り詰め"""
        long_cmd = "python3 " + "a" * 200
        suggestions = suggester._aggregate_command_prefixes([long_cmd])
        assert suggestions[0].examples[0].endswith("...")
        assert len(suggestions[0].examples[0]) == 103  # 100 + "..."

    def test_空リスト(self, suggester):
        suggestions = suggester._aggregate_command_prefixes([])
        assert suggestions == []


# === 既存ルール重複除外テスト ===

class TestExcludeExistingRules:
    """重複除外テスト"""

    def test_ファイルルール重複除外(self, mock_file_matcher, tmp_log_dir, mock_command_matcher):
        """既存ファイルルールと一致するパターンを除外"""
        mock_file_matcher.list_rules.return_value = [
            {"name": "既存ルール", "patterns": ["src/domain/hooks/**/*.py"], "message": "test", "severity": "warn"}
        ]
        suggester = RuleSuggester(
            log_dir=tmp_log_dir,
            cwd=Path("/workspace/vibes/claude_nagger"),
            file_matcher=mock_file_matcher,
            command_matcher=mock_command_matcher,
        )

        suggestions = [
            PatternSuggestion(category="file", pattern="src/domain/hooks/**/*.py", count=5),
            PatternSuggestion(category="file", pattern="docs/specs/**/*.pu", count=2),
        ]
        result = suggester._exclude_existing_file_rules(suggestions)
        assert len(result) == 1
        assert result[0].pattern == "docs/specs/**/*.pu"

    def test_コマンドルール重複除外(self, mock_command_matcher, tmp_log_dir, mock_file_matcher):
        """既存コマンドルールと一致するパターンを除外"""
        mock_command_matcher.list_rules.return_value = [
            {"name": "Git操作規約", "patterns": ["git*"], "message": "test", "severity": "block"}
        ]
        suggester = RuleSuggester(
            log_dir=tmp_log_dir,
            cwd=Path("/workspace/vibes/claude_nagger"),
            file_matcher=mock_file_matcher,
            command_matcher=mock_command_matcher,
        )

        suggestions = [
            PatternSuggestion(category="command", pattern="git*", count=10),
            PatternSuggestion(category="command", pattern="python3*", count=3),
        ]
        result = suggester._exclude_existing_command_rules(suggestions)
        assert len(result) == 1
        assert result[0].pattern == "python3*"


# === analyze 統合テスト ===

class TestAnalyze:
    """analyze メソッド統合テスト"""

    def test_入力なしの場合(self, suggester):
        """hook_inputファイルがない場合"""
        result = suggester.analyze()
        assert result["file_suggestions"] == []
        assert result["command_suggestions"] == []
        assert result["stats"]["total_inputs"] == 0

    def test_ファイル操作の分析(self, suggester, tmp_log_dir):
        """Editツールの入力を分析しパターン候補を返す"""
        for i, path in enumerate([
            "/workspace/vibes/claude_nagger/src/domain/hooks/base_hook.py",
            "/workspace/vibes/claude_nagger/src/domain/hooks/session_startup_hook.py",
            "/workspace/vibes/claude_nagger/docs/specs/spec.pu",
            "/workspace/vibes/claude_nagger/docs/specs/design.pu",
        ]):
            _write_hook_input(tmp_log_dir, {
                "tool_name": "Edit",
                "tool_input": {"file_path": path},
            }, index=i)

        result = suggester.analyze()
        assert result["stats"]["total_inputs"] == 4
        assert result["stats"]["file_inputs"] == 4
        assert len(result["file_suggestions"]) == 2

        # 頻度降順ソート確認
        counts = [s.count for s in result["file_suggestions"]]
        assert counts == sorted(counts, reverse=True)

    def test_コマンド操作の分析(self, suggester, tmp_log_dir):
        """Bashツールの入力を分析しプレフィックス候補を返す"""
        for i, cmd in enumerate([
            "git status",
            "git diff",
            "git log --oneline",
            "python3 test.py",
        ]):
            _write_hook_input(tmp_log_dir, {
                "tool_name": "Bash",
                "tool_input": {"command": cmd},
            }, index=i)

        result = suggester.analyze()
        assert result["stats"]["total_inputs"] == 4
        assert result["stats"]["command_inputs"] == 4
        assert len(result["command_suggestions"]) == 2

    def test_混合入力の分析(self, suggester, tmp_log_dir):
        """Edit/Write/Bash/Read混合入力の分析"""
        inputs = [
            {"tool_name": "Edit", "tool_input": {"file_path": "/workspace/vibes/claude_nagger/src/a.py"}},
            {"tool_name": "Write", "tool_input": {"file_path": "/workspace/vibes/claude_nagger/src/b.py"}},
            {"tool_name": "Bash", "tool_input": {"command": "git status"}},
            {"tool_name": "Read", "tool_input": {"file_path": "/workspace/vibes/claude_nagger/src/c.py"}},
            {"tool_name": "mcp__serena__read_file", "tool_input": {"relative_path": "src/d.py"}},
        ]
        for i, data in enumerate(inputs):
            _write_hook_input(tmp_log_dir, data, index=i)

        result = suggester.analyze()
        assert result["stats"]["total_inputs"] == 5
        assert result["stats"]["file_inputs"] == 2
        assert result["stats"]["command_inputs"] == 1


# === 既存フィクスチャ活用テスト ===

class TestWithExistingFixtures:
    """既存テストフィクスチャ（tests/fixtures/claude_code/pre_tool_use/）を使用したテスト"""

    @pytest.fixture
    def fixture_dir(self):
        return Path(__file__).parent / "fixtures" / "claude_code" / "pre_tool_use"

    @pytest.fixture
    def suggester_with_fixtures(self, tmp_log_dir, mock_file_matcher, mock_command_matcher, fixture_dir):
        """フィクスチャファイルをログディレクトリにコピーしたSuggester"""
        import shutil
        # Edit, Write, Bashのフィクスチャをhook_input_*としてコピー
        idx = 0
        for tool_dir in ["edit", "write", "bash"]:
            src_dir = fixture_dir / tool_dir
            if src_dir.exists():
                for json_file in src_dir.glob("*.json"):
                    dest = tmp_log_dir / f"hook_input_fixture_{idx}.json"
                    shutil.copy2(json_file, dest)
                    idx += 1

        return RuleSuggester(
            log_dir=tmp_log_dir,
            cwd=Path("/workspace/vibes/claude_nagger"),
            file_matcher=mock_file_matcher,
            command_matcher=mock_command_matcher,
        )

    def test_フィクスチャからの分析実行(self, suggester_with_fixtures, fixture_dir):
        """実際のフィクスチャデータで分析が正常に完了する"""
        if not fixture_dir.exists():
            pytest.skip("フィクスチャディレクトリなし")

        result = suggester_with_fixtures.analyze()
        # 分析自体が例外なく完了すること
        assert "file_suggestions" in result
        assert "command_suggestions" in result
        assert "stats" in result
        assert result["stats"]["total_inputs"] > 0

    def test_フィクスチャの分類が正しい(self, suggester_with_fixtures, fixture_dir):
        """EditはファイルにBashはコマンドに正しく分類される"""
        if not fixture_dir.exists():
            pytest.skip("フィクスチャディレクトリなし")

        result = suggester_with_fixtures.analyze()
        # Edit/Writeフィクスチャがあるのでファイル入力 > 0
        assert result["stats"]["file_inputs"] > 0
        # Bashフィクスチャがあるのでコマンド入力 > 0
        assert result["stats"]["command_inputs"] > 0


# === #5642: 拡張子なしファイルのパターン生成テスト ===

class TestExtensionlessFilePatterns:
    """拡張子なしファイル（Makefile, Dockerfile等）のパターン生成"""

    def test_Makefile_パターン生成(self, suggester):
        """Makefileは **/Makefile パターンを生成"""
        file_paths = ["/workspace/vibes/claude_nagger/Makefile"]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        assert len(suggestions) == 1
        assert suggestions[0].pattern == "**/Makefile"

    def test_Dockerfile_ディレクトリ付き(self, suggester):
        """ディレクトリ配下のDockerfileは dir/**/Dockerfile パターン"""
        file_paths = ["/workspace/vibes/claude_nagger/docker/Dockerfile"]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        assert len(suggestions) == 1
        assert suggestions[0].pattern == "docker/**/Dockerfile"

    def test_拡張子なし複数ファイル集約(self, suggester):
        """同名の拡張子なしファイルは1パターンに集約"""
        file_paths = [
            "/workspace/vibes/claude_nagger/Makefile",
            "/workspace/vibes/claude_nagger/sub/Makefile",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        # **/Makefile と sub/**/Makefile → マージされて **/Makefile (2回)
        assert len(suggestions) == 1
        assert suggestions[0].pattern == "**/Makefile"
        assert suggestions[0].count == 2

    def test_拡張子ありとなし混在(self, suggester):
        """拡張子あり/なしファイルが混在する場合は別パターン"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/main.py",
            "/workspace/vibes/claude_nagger/Makefile",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        patterns = {s.pattern for s in suggestions}
        assert "src/**/*.py" in patterns
        assert "**/Makefile" in patterns


# === #5645: チェーンコマンドのプレフィックス抽出テスト ===

class TestChainCommandPrefix:
    """&&/; チェーンコマンドのプレフィックス抽出"""

    def test_AND_チェーン(self, suggester):
        """&&チェーンは先頭コマンドがプレフィックス（仕様）"""
        assert suggester._extract_command_prefix("cd /tmp && git status") == "cd"

    def test_セミコロン_チェーン(self, suggester):
        """；チェーンは先頭コマンドがプレフィックス（仕様）"""
        assert suggester._extract_command_prefix("mkdir -p /tmp/test; cd /tmp/test") == "mkdir"

    def test_パイプとANDの混合(self, suggester):
        """パイプ優先で分割し先頭トークンを取得"""
        assert suggester._extract_command_prefix("ls -la | grep test && echo done") == "ls"


# === #5647: tool_nameキー欠損時の分類テスト ===

class TestMissingToolName:
    """tool_nameキーが存在しない入力データの分類処理"""

    def test_tool_nameキー欠損(self, suggester):
        """tool_nameキーがない場合はスキップ"""
        inputs = [{"tool_input": {"file_path": "/workspace/test.py"}}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == []
        assert commands == []

    def test_tool_name空文字(self, suggester):
        """tool_nameが空文字の場合はスキップ"""
        inputs = [{"tool_name": "", "tool_input": {"file_path": "/workspace/test.py"}}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == []
        assert commands == []

    def test_tool_inputキー欠損(self, suggester):
        """tool_inputキーがない場合はスキップ"""
        inputs = [{"tool_name": "Edit"}]
        file_paths, commands = suggester._classify_inputs(inputs)
        assert file_paths == []
        assert commands == []


# === #5646: サブディレクトリ包含マージテスト ===

class TestPatternContainsMerge:
    """サブディレクトリ跨ぎの冗長パターンマージ"""

    def test_親子ディレクトリのマージ(self, suggester):
        """親ディレクトリパターンが子を包含する場合マージ"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/domain/hooks/base_hook.py",
            "/workspace/vibes/claude_nagger/src/domain/hooks/sub/nested_hook.py",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        # src/domain/hooks/**/*.py が src/domain/hooks/sub/**/*.py を包含
        assert len(suggestions) == 1
        assert suggestions[0].pattern == "src/domain/hooks/**/*.py"
        assert suggestions[0].count == 2

    def test_異なる拡張子はマージしない(self, suggester):
        """拡張子が異なるパターンはマージしない"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/main.py",
            "/workspace/vibes/claude_nagger/src/sub/config.yaml",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        assert len(suggestions) == 2

    def test_兄弟ディレクトリはマージしない(self, suggester):
        """兄弟ディレクトリ（包含関係なし）はマージしない"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/domain/hooks/base_hook.py",
            "/workspace/vibes/claude_nagger/src/domain/services/manager.py",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        assert len(suggestions) == 2

    def test_3段ネストの推移的マージ(self, suggester):
        """src/**/*.py → src/domain/**/*.py → src/domain/hooks/**/*.py が全て1パターンにマージ"""
        file_paths = [
            "/workspace/vibes/claude_nagger/src/main.py",
            "/workspace/vibes/claude_nagger/src/domain/entity.py",
            "/workspace/vibes/claude_nagger/src/domain/hooks/base_hook.py",
        ]
        suggestions = suggester._aggregate_file_patterns(file_paths)
        assert len(suggestions) == 1
        assert suggestions[0].pattern == "src/**/*.py"
        assert suggestions[0].count == 3

    def test_resolve_target_推移的解決(self):
        """_resolve_target が推移的にtargetを辿る"""
        merged_into = {
            "src/domain/hooks/**/*.py": "src/domain/**/*.py",
            "src/domain/**/*.py": "src/**/*.py",
        }
        assert RuleSuggester._resolve_target(merged_into, "src/domain/hooks/**/*.py") == "src/**/*.py"
        assert RuleSuggester._resolve_target(merged_into, "src/domain/**/*.py") == "src/**/*.py"
        assert RuleSuggester._resolve_target(merged_into, "src/**/*.py") == "src/**/*.py"
        # マージ対象外
        assert RuleSuggester._resolve_target(merged_into, "docs/**/*.md") == "docs/**/*.md"

    def test_pattern_contains_判定(self):
        """_pattern_contains の直接テスト"""
        assert RuleSuggester._pattern_contains("src/**/*.py", "src/domain/**/*.py") is True
        assert RuleSuggester._pattern_contains("src/**/*.py", "src/domain/hooks/**/*.py") is True
        assert RuleSuggester._pattern_contains("**/*.py", "src/**/*.py") is True
        # 同一パターンは包含しない
        assert RuleSuggester._pattern_contains("src/**/*.py", "src/**/*.py") is False
        # 拡張子が異なる
        assert RuleSuggester._pattern_contains("src/**/*.py", "src/**/*.yaml") is False
        # 兄弟ディレクトリ
        assert RuleSuggester._pattern_contains("src/hooks/**/*.py", "src/services/**/*.py") is False
        # 拡張子なしパターン
        assert RuleSuggester._pattern_contains("**/Makefile", "sub/**/Makefile") is True
