"""cli.py のテスト"""

import pytest
import sys
from unittest.mock import patch, MagicMock

from src.application.cli import main


class TestCLI:
    """CLIメインエントリーポイントのテスト"""

    def test_version_flag(self, capsys):
        """--version フラグでバージョンが表示される"""
        with patch.object(sys, 'argv', ['claude-nagger', '--version']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "claude-nagger v" in captured.out

    def test_no_command_shows_help(self, capsys):
        """コマンド未指定時はヘルプが表示される"""
        with patch.object(sys, 'argv', ['claude-nagger']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "claude-nagger" in captured.out
        assert "install-hooks" in captured.out

    def test_install_hooks_command(self, tmp_path, monkeypatch):
        """install-hooks コマンドが正しく実行される"""
        mock_cmd = MagicMock()
        mock_cmd.execute.return_value = 0
        mock_class = MagicMock(return_value=mock_cmd)

        # monkeypatch でモジュールを差し替える
        mock_module = MagicMock()
        mock_module.InstallHooksCommand = mock_class
        monkeypatch.setitem(sys.modules, 'application.install_hooks', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'install-hooks']):
            result = main()

        assert result == 0
        mock_class.assert_called_once_with(force=False, dry_run=False)
        mock_cmd.execute.assert_called_once()

    def test_install_hooks_with_force(self, tmp_path, monkeypatch):
        """install-hooks --force が正しく渡される"""
        mock_cmd = MagicMock()
        mock_cmd.execute.return_value = 0
        mock_class = MagicMock(return_value=mock_cmd)

        mock_module = MagicMock()
        mock_module.InstallHooksCommand = mock_class
        monkeypatch.setitem(sys.modules, 'application.install_hooks', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'install-hooks', '--force']):
            result = main()

        assert result == 0
        mock_class.assert_called_once_with(force=True, dry_run=False)

    def test_install_hooks_with_dry_run(self, tmp_path, monkeypatch):
        """install-hooks --dry-run が正しく渡される"""
        mock_cmd = MagicMock()
        mock_cmd.execute.return_value = 0
        mock_class = MagicMock(return_value=mock_cmd)

        mock_module = MagicMock()
        mock_module.InstallHooksCommand = mock_class
        monkeypatch.setitem(sys.modules, 'application.install_hooks', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'install-hooks', '--dry-run']):
            result = main()

        assert result == 0
        mock_class.assert_called_once_with(force=False, dry_run=True)

    def test_install_hooks_with_force_short(self, tmp_path, monkeypatch):
        """install-hooks -f ショートオプションが正しく動作する"""
        mock_cmd = MagicMock()
        mock_cmd.execute.return_value = 0
        mock_class = MagicMock(return_value=mock_cmd)

        mock_module = MagicMock()
        mock_module.InstallHooksCommand = mock_class
        monkeypatch.setitem(sys.modules, 'application.install_hooks', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'install-hooks', '-f']):
            result = main()

        assert result == 0
        mock_class.assert_called_once_with(force=True, dry_run=False)

    def test_install_hooks_with_both_options(self, tmp_path, monkeypatch):
        """install-hooks --force --dry-run が正しく渡される"""
        mock_cmd = MagicMock()
        mock_cmd.execute.return_value = 0
        mock_class = MagicMock(return_value=mock_cmd)

        mock_module = MagicMock()
        mock_module.InstallHooksCommand = mock_class
        monkeypatch.setitem(sys.modules, 'application.install_hooks', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'install-hooks', '--force', '--dry-run']):
            result = main()

        assert result == 0
        mock_class.assert_called_once_with(force=True, dry_run=True)

    def test_help_flag(self, capsys):
        """--help フラグでヘルプが表示される"""
        with patch.object(sys, 'argv', ['claude-nagger', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "claude-nagger" in captured.out

    def test_install_hooks_help(self, capsys):
        """install-hooks --help でサブコマンドヘルプが表示される"""
        with patch.object(sys, 'argv', ['claude-nagger', 'install-hooks', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "--force" in captured.out
        assert "--dry-run" in captured.out

    def test_install_hooks_returns_command_result(self, tmp_path, monkeypatch):
        """install-hooks コマンドの戻り値が正しく返される"""
        mock_cmd = MagicMock()
        mock_cmd.execute.return_value = 1  # エラーを返す
        mock_class = MagicMock(return_value=mock_cmd)

        mock_module = MagicMock()
        mock_module.InstallHooksCommand = mock_class
        monkeypatch.setitem(sys.modules, 'application.install_hooks', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'install-hooks']):
            result = main()

        assert result == 1


class TestNotifyCommand:
    """notifyコマンドのテスト"""

    def test_notify_command_success(self, monkeypatch, capsys):
        """notify コマンドが正しく実行される（成功時）"""
        mock_notifier = MagicMock()
        mock_notifier.send_sync.return_value = {
            'success': True,
            'agent_name': 'test-agent',
            'message': 'test message'
        }
        mock_class = MagicMock(return_value=mock_notifier)

        mock_module = MagicMock()
        mock_module.DiscordNotifier = mock_class
        monkeypatch.setitem(sys.modules, 'infrastructure.notifiers.discord_notifier', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'notify', 'test message']):
            result = main()

        assert result == 0
        mock_notifier.send_sync.assert_called_once_with('test message')
        captured = capsys.readouterr()
        assert "Message sent to Discord" in captured.err

    def test_notify_command_failure(self, monkeypatch, capsys):
        """notify コマンドが正しく実行される（失敗時）"""
        mock_notifier = MagicMock()
        mock_notifier.send_sync.return_value = {
            'success': False,
            'error': 'Connection failed'
        }
        mock_class = MagicMock(return_value=mock_notifier)

        mock_module = MagicMock()
        mock_module.DiscordNotifier = mock_class
        monkeypatch.setitem(sys.modules, 'infrastructure.notifiers.discord_notifier', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'notify', 'test message']):
            result = main()

        assert result == 0
        captured = capsys.readouterr()
        assert "Failed to send Discord message" in captured.err

    def test_notify_command_default_message(self, monkeypatch, capsys):
        """notify コマンドでメッセージ省略時はデフォルト値が使用される"""
        mock_notifier = MagicMock()
        mock_notifier.send_sync.return_value = {
            'success': True,
            'agent_name': 'test-agent',
            'message': 'hello'
        }
        mock_class = MagicMock(return_value=mock_notifier)

        mock_module = MagicMock()
        mock_module.DiscordNotifier = mock_class
        monkeypatch.setitem(sys.modules, 'infrastructure.notifiers.discord_notifier', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'notify']):
            result = main()

        assert result == 0
        mock_notifier.send_sync.assert_called_once_with('hello')

    def test_notify_help(self, capsys):
        """notify --help でサブコマンドヘルプが表示される"""
        with patch.object(sys, 'argv', ['claude-nagger', 'notify', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "message" in captured.out


class TestHookCompactDetectedCommand:
    """hook compact-detectedコマンドのテスト"""

    def test_hook_compact_detected_help(self, capsys):
        """hook compact-detected がヘルプに表示される"""
        with patch.object(sys, 'argv', ['claude-nagger', 'hook', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "compact-detected" in captured.out

    def test_hook_compact_detected_runs_hook(self, monkeypatch):
        """hook compact-detected がCompactDetectedHookを実行する"""
        mock_hook = MagicMock()
        mock_hook.run.return_value = 0
        mock_class = MagicMock(return_value=mock_hook)

        mock_module = MagicMock()
        mock_module.CompactDetectedHook = mock_class
        monkeypatch.setitem(sys.modules, 'domain.hooks.compact_detected_hook', mock_module)

        with patch.object(sys, 'argv', ['claude-nagger', 'hook', 'compact-detected']):
            result = main()

        assert result == 0
        mock_class.assert_called_once()
        mock_hook.run.assert_called_once()
