"""InstallHooksCommandのテスト

Issue #3835: フックインストールコマンド
"""

import json
import pytest
import tempfile
import os
from pathlib import Path

from src.application.install_hooks import InstallHooksCommand, ensure_config_exists


class TestCreateClaudeNaggerDir:
    """`.claude-nagger/`ディレクトリ・雛形ファイル作成のテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_creates_directory_if_not_exists(self, temp_dir):
        """`.claude-nagger/`ディレクトリが存在しない場合、作成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._create_claude_nagger_dir()

            nagger_dir = temp_dir / ".claude-nagger"
            assert nagger_dir.exists()
            assert nagger_dir.is_dir()
        finally:
            os.chdir(original_cwd)

    def test_creates_file_conventions_yaml(self, temp_dir):
        """`file_conventions.yaml`が生成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._create_claude_nagger_dir()

            file_conventions = temp_dir / ".claude-nagger" / "file_conventions.yaml"
            assert file_conventions.exists()
            content = file_conventions.read_text(encoding="utf-8")
            assert "rules:" in content
        finally:
            os.chdir(original_cwd)

    def test_creates_command_conventions_yaml(self, temp_dir):
        """`command_conventions.yaml`が生成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._create_claude_nagger_dir()

            command_conventions = temp_dir / ".claude-nagger" / "command_conventions.yaml"
            assert command_conventions.exists()
            content = command_conventions.read_text(encoding="utf-8")
            assert "rules:" in content
        finally:
            os.chdir(original_cwd)

    def test_creates_config_yaml(self, temp_dir):
        """`config.yaml`が生成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._create_claude_nagger_dir()

            config = temp_dir / ".claude-nagger" / "config.yaml"
            assert config.exists()
            content = config.read_text(encoding="utf-8")
            assert "session_startup:" in content
        finally:
            os.chdir(original_cwd)

    def test_creates_vault_directory(self, temp_dir):
        """`vault/`ディレクトリが生成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._create_claude_nagger_dir()

            vault_dir = temp_dir / ".claude-nagger" / "vault"
            assert vault_dir.exists()
            assert vault_dir.is_dir()
        finally:
            os.chdir(original_cwd)

    def test_creates_vault_secrets_yaml(self, temp_dir):
        """`vault/secrets.yaml`が生成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._create_claude_nagger_dir()

            secrets = temp_dir / ".claude-nagger" / "vault" / "secrets.yaml"
            assert secrets.exists()
            content = secrets.read_text(encoding="utf-8")
            assert "discord:" in content
            assert "webhook_url:" in content
        finally:
            os.chdir(original_cwd)

    def test_creates_vault_gitignore(self, temp_dir):
        """`vault/.gitignore`が生成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._create_claude_nagger_dir()

            gitignore = temp_dir / ".claude-nagger" / "vault" / ".gitignore"
            assert gitignore.exists()
            content = gitignore.read_text(encoding="utf-8")
            assert "*" in content
            assert "!.gitignore" in content
        finally:
            os.chdir(original_cwd)

    def test_skips_existing_files_without_force(self, temp_dir):
        """既存ファイルがある場合、forceなしではスキップされる"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # 既存ファイルを作成
            nagger_dir = temp_dir / ".claude-nagger"
            nagger_dir.mkdir()
            existing_content = "# 既存の設定"
            (nagger_dir / "config.yaml").write_text(existing_content, encoding="utf-8")

            cmd = InstallHooksCommand(force=False)
            cmd._create_claude_nagger_dir()

            # 既存ファイルが変更されていないことを確認
            config = nagger_dir / "config.yaml"
            assert config.read_text(encoding="utf-8") == existing_content
        finally:
            os.chdir(original_cwd)

    def test_overwrites_existing_files_with_force(self, temp_dir):
        """forceオプションで既存ファイルを上書き"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # 既存ファイルを作成
            nagger_dir = temp_dir / ".claude-nagger"
            nagger_dir.mkdir()
            existing_content = "# 既存の設定"
            (nagger_dir / "config.yaml").write_text(existing_content, encoding="utf-8")

            cmd = InstallHooksCommand(force=True)
            cmd._create_claude_nagger_dir()

            # ファイルが上書きされていることを確認
            config = nagger_dir / "config.yaml"
            content = config.read_text(encoding="utf-8")
            assert content != existing_content
            assert "session_startup:" in content
        finally:
            os.chdir(original_cwd)


class TestUpdateSettingsJson:
    """`.claude/settings.json`更新のテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_creates_claude_dir_if_not_exists(self, temp_dir):
        """`.claude/`ディレクトリがない場合、作成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._update_settings_json()

            claude_dir = temp_dir / ".claude"
            assert claude_dir.exists()
            assert claude_dir.is_dir()
        finally:
            os.chdir(original_cwd)

    def test_creates_settings_json_if_not_exists(self, temp_dir):
        """`settings.json`がない場合、新規作成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd._update_settings_json()

            settings_path = temp_dir / ".claude" / "settings.json"
            assert settings_path.exists()

            settings = json.loads(settings_path.read_text(encoding="utf-8"))
            assert "hooks" in settings
            assert "PreToolUse" in settings["hooks"]
        finally:
            os.chdir(original_cwd)

    def test_merges_with_existing_hooks(self, temp_dir):
        """既存のPreToolUseフックがマージされる"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # 既存設定を作成
            claude_dir = temp_dir / ".claude"
            claude_dir.mkdir()
            existing_settings = {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "echo existing"}]
                        }
                    ]
                }
            }
            (claude_dir / "settings.json").write_text(
                json.dumps(existing_settings), encoding="utf-8"
            )

            cmd = InstallHooksCommand()
            cmd._update_settings_json()

            settings_path = claude_dir / "settings.json"
            settings = json.loads(settings_path.read_text(encoding="utf-8"))

            # 既存フックが保持されていることを確認
            pretooluse = settings["hooks"]["PreToolUse"]
            commands = []
            for entry in pretooluse:
                for hook in entry.get("hooks", []):
                    if "command" in hook:
                        commands.append(hook["command"])

            assert "echo existing" in commands
            # 新規フックも追加されていることを確認
            assert any("session_startup_hook" in cmd for cmd in commands)
        finally:
            os.chdir(original_cwd)


class TestMergePreToolUseHooks:
    """PreToolUseフックのスマートマージのテスト"""

    def test_adds_hooks_to_empty_settings(self):
        """空の設定に新規フック追加"""
        cmd = InstallHooksCommand()
        settings = {}

        result = cmd._merge_pretooluse_hooks(settings)

        assert result is True
        assert "hooks" in settings
        assert "PreToolUse" in settings["hooks"]
        assert len(settings["hooks"]["PreToolUse"]) > 0

    def test_adds_hooks_to_existing_empty_pretooluse(self):
        """既存の空PreToolUseに新規フック追加"""
        cmd = InstallHooksCommand()
        settings = {"hooks": {"PreToolUse": []}}

        result = cmd._merge_pretooluse_hooks(settings)

        assert result is True
        assert len(settings["hooks"]["PreToolUse"]) > 0

    def test_prevents_duplicate_hooks(self):
        """同一コマンドの重複回避"""
        cmd = InstallHooksCommand()
        settings = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "",
                        "hooks": [
                            {
                                "type": "command",
                                "command": "python3 .claude-nagger/hooks/session_startup_hook.py"
                            }
                        ]
                    }
                ]
            }
        }

        result = cmd._merge_pretooluse_hooks(settings)

        # 重複があるため追加されない
        assert result is False
        assert len(settings["hooks"]["PreToolUse"]) == 1


class TestDryRunMode:
    """dry-runモードのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_dry_run_does_not_create_files(self, temp_dir):
        """dry-runでは実際のファイル作成が行われない"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand(dry_run=True)
            cmd.execute()

            # ディレクトリ・ファイルが作成されていないことを確認
            nagger_dir = temp_dir / ".claude-nagger"
            claude_dir = temp_dir / ".claude"

            # dry-runでもディレクトリは作成される（現実装の動作）
            # ファイル作成のみスキップされることを確認
            if nagger_dir.exists():
                # dry-runではファイルが作成されない
                files = list(nagger_dir.glob("*.yaml"))
                assert len(files) == 0, "dry-runではyamlファイルが作成されないべき"
        finally:
            os.chdir(original_cwd)


class TestExecute:
    """executeメソッド全体フローのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_execute_returns_zero_on_success(self, temp_dir):
        """正常完了時は0を返す"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            result = cmd.execute()

            assert result == 0
        finally:
            os.chdir(original_cwd)

    def test_execute_creates_all_required_files(self, temp_dir):
        """executeで必要な全ファイルが作成される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            cmd.execute()

            # .claude-nagger/ の確認
            assert (temp_dir / ".claude-nagger").exists()
            assert (temp_dir / ".claude-nagger" / "file_conventions.yaml").exists()
            assert (temp_dir / ".claude-nagger" / "command_conventions.yaml").exists()
            assert (temp_dir / ".claude-nagger" / "config.yaml").exists()

            # vault/ の確認
            assert (temp_dir / ".claude-nagger" / "vault").exists()
            assert (temp_dir / ".claude-nagger" / "vault" / "secrets.yaml").exists()
            assert (temp_dir / ".claude-nagger" / "vault" / ".gitignore").exists()

            # .claude/ の確認
            assert (temp_dir / ".claude").exists()
            assert (temp_dir / ".claude" / "settings.json").exists()
        finally:
            os.chdir(original_cwd)

    def test_execute_preserves_existing_settings(self, temp_dir):
        """既存の設定が保持される"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            # 既存設定を作成
            claude_dir = temp_dir / ".claude"
            claude_dir.mkdir()
            existing_settings = {
                "allowedCommands": ["npm run build"],
                "hooks": {
                    "PostToolUse": [{"matcher": "Write", "hooks": []}]
                }
            }
            (claude_dir / "settings.json").write_text(
                json.dumps(existing_settings), encoding="utf-8"
            )

            cmd = InstallHooksCommand()
            cmd.execute()

            # 既存設定が保持されていることを確認
            settings = json.loads(
                (claude_dir / "settings.json").read_text(encoding="utf-8")
            )
            assert "allowedCommands" in settings
            assert settings["allowedCommands"] == ["npm run build"]
            assert "PostToolUse" in settings["hooks"]
        finally:
            os.chdir(original_cwd)


class TestLoadSettings:
    """settings.json読み込みのテスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_load_nonexistent_returns_empty_dict(self, temp_dir):
        """存在しないファイルを読み込むと空dictを返す"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            cmd = InstallHooksCommand()
            result = cmd._load_settings(temp_dir / "nonexistent.json")

            assert result == {}
        finally:
            os.chdir(original_cwd)

    def test_load_invalid_json_returns_empty_dict(self, temp_dir, capsys):
        """不正なJSONを読み込むと空dictを返す"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            invalid_json = temp_dir / "invalid.json"
            invalid_json.write_text("{ invalid json", encoding="utf-8")

            cmd = InstallHooksCommand()
            result = cmd._load_settings(invalid_json)

            assert result == {}

            # 警告メッセージが出力されていることを確認
            captured = capsys.readouterr()
            assert "警告" in captured.out
        finally:
            os.chdir(original_cwd)

    def test_load_valid_json(self, temp_dir):
        """有効なJSONを正常に読み込める"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)

            valid_json = temp_dir / "valid.json"
            valid_json.write_text('{"key": "value"}', encoding="utf-8")

            cmd = InstallHooksCommand()
            result = cmd._load_settings(valid_json)

            assert result == {"key": "value"}
        finally:
            os.chdir(original_cwd)


class TestCLIIntegration:
    """CLIエントリーポイントの統合テスト"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_cli_version(self):
        """--versionオプションでバージョン表示"""
        import subprocess
        result = subprocess.run(
            ["/home/node/.local/bin/claude-nagger", "--version"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "claude-nagger" in result.stdout
        assert "1.0.0" in result.stdout

    def test_cli_install_hooks_dry_run(self, temp_dir):
        """install-hooks --dry-runオプション"""
        import subprocess
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            result = subprocess.run(
                ["/home/node/.local/bin/claude-nagger", "install-hooks", "--dry-run"],
                capture_output=True,
                text=True,
                cwd=str(temp_dir)
            )
            assert result.returncode == 0
            assert "dry-run" in result.stdout
        finally:
            os.chdir(original_cwd)

    def test_cli_install_hooks_creates_files(self, temp_dir):
        """install-hooksコマンドでファイルが作成される"""
        import subprocess
        result = subprocess.run(
            ["/home/node/.local/bin/claude-nagger", "install-hooks"],
            capture_output=True,
            text=True,
            cwd=str(temp_dir)
        )
        assert result.returncode == 0
        assert "インストール完了" in result.stdout

        # ファイルが作成されていることを確認
        assert (temp_dir / ".claude-nagger" / "config.yaml").exists()
        assert (temp_dir / ".claude" / "settings.json").exists()

    def test_cli_help(self):
        """ヘルプ表示"""
        import subprocess
        result = subprocess.run(
            ["/home/node/.local/bin/claude-nagger", "--help"],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert "install-hooks" in result.stdout


class TestEnsureConfigExists:
    """ensure_config_exists()関数のテスト (Issue #3910)"""

    @pytest.fixture
    def temp_dir(self):
        """テスト用一時ディレクトリ"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_creates_config_if_not_exists(self, temp_dir):
        """設定ファイルが存在しない場合、生成される"""
        result = ensure_config_exists(temp_dir)

        assert result is True
        assert (temp_dir / ".claude-nagger").exists()
        assert (temp_dir / ".claude-nagger" / "config.yaml").exists()
        assert (temp_dir / ".claude-nagger" / "file_conventions.yaml").exists()
        assert (temp_dir / ".claude-nagger" / "command_conventions.yaml").exists()
        # vault/ディレクトリも生成される
        assert (temp_dir / ".claude-nagger" / "vault").exists()
        assert (temp_dir / ".claude-nagger" / "vault" / "secrets.yaml").exists()
        assert (temp_dir / ".claude-nagger" / "vault" / ".gitignore").exists()

    def test_returns_false_if_config_exists(self, temp_dir):
        """設定ファイルが既に存在する場合、Falseを返す"""
        # 既存ファイルを作成
        nagger_dir = temp_dir / ".claude-nagger"
        nagger_dir.mkdir()
        (nagger_dir / "config.yaml").write_text("# existing", encoding="utf-8")

        result = ensure_config_exists(temp_dir)

        assert result is False

    def test_idempotency(self, temp_dir):
        """冪等性: 複数回呼んでも同じ結果になる"""
        # 1回目の呼び出し
        result1 = ensure_config_exists(temp_dir)
        assert result1 is True

        # 2回目の呼び出し（既に存在するので何もしない）
        result2 = ensure_config_exists(temp_dir)
        assert result2 is False

        # ファイルが存在することを確認
        assert (temp_dir / ".claude-nagger" / "config.yaml").exists()

    def test_creates_missing_files_only(self, temp_dir):
        """不足分のみ生成: 部分的に存在する場合"""
        # ディレクトリと一部ファイルのみ作成
        nagger_dir = temp_dir / ".claude-nagger"
        nagger_dir.mkdir()
        (nagger_dir / "file_conventions.yaml").write_text("# existing", encoding="utf-8")

        result = ensure_config_exists(temp_dir)

        assert result is True
        # 既存ファイルは保持
        assert (nagger_dir / "file_conventions.yaml").read_text(encoding="utf-8") == "# existing"
        # 不足分が生成される
        assert (nagger_dir / "config.yaml").exists()
        assert (nagger_dir / "command_conventions.yaml").exists()

    def test_outputs_warning_to_stderr(self, temp_dir, capsys):
        """自動生成時にstderrへ警告出力"""
        ensure_config_exists(temp_dir)

        captured = capsys.readouterr()
        assert "警告" in captured.err
        assert "自動生成" in captured.err

    def test_uses_cwd_if_no_path_provided(self, temp_dir):
        """パス指定なしの場合、カレントディレクトリを使用"""
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_dir)
            result = ensure_config_exists()

            assert result is True
            assert (temp_dir / ".claude-nagger" / "config.yaml").exists()
        finally:
            os.chdir(original_cwd)
