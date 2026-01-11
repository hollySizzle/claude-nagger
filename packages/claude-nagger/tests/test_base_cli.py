"""base_cli.py のテスト"""

import pytest
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.shared.base.base_cli import BaseCLI


class ConcreteCLI(BaseCLI):
    """テスト用の具象CLIクラス"""

    def show_menu(self) -> str:
        return "Test Menu"

    def run_interactive(self):
        return "Interactive Mode"


class TestBaseCLI:
    """BaseCLIクラスのテスト"""

    def test_init_sets_working_dir(self):
        """初期化時にworking_dirが設定される"""
        cli = ConcreteCLI()
        assert cli.working_dir == Path.cwd()

    def test_init_sets_logger(self):
        """初期化時にloggerが設定される"""
        cli = ConcreteCLI()
        assert cli.logger is not None
        assert isinstance(cli.logger, logging.Logger)
        assert cli.logger.name == "ConcreteCLI"

    def test_logger_level_is_info(self):
        """ロガーのレベルがINFOに設定される"""
        cli = ConcreteCLI()
        assert cli.logger.level == logging.INFO

    def test_logger_has_handler(self):
        """ロガーにハンドラーが追加される"""
        # 一度ロガーをクリアしてテスト
        logger_name = "TestCLI_handler"
        test_logger = logging.getLogger(logger_name)
        test_logger.handlers.clear()

        with patch.object(BaseCLI, '__init__', lambda self: None):
            cli = ConcreteCLI()
            cli.working_dir = Path.cwd()
            cli.logger = cli._setup_logger()

        assert len(cli.logger.handlers) >= 1

    def test_logger_does_not_add_duplicate_handlers(self):
        """ロガーに重複したハンドラーは追加されない"""
        cli1 = ConcreteCLI()
        initial_handler_count = len(cli1.logger.handlers)

        # 2回目の初期化
        cli2 = ConcreteCLI()

        # ハンドラー数が増えていないことを確認
        assert len(cli2.logger.handlers) == initial_handler_count

    def test_show_menu_abstract(self):
        """show_menuは抽象メソッドとして定義されている"""
        cli = ConcreteCLI()
        result = cli.show_menu()
        assert result == "Test Menu"

    def test_run_interactive_abstract(self):
        """run_interactiveは抽象メソッドとして定義されている"""
        cli = ConcreteCLI()
        result = cli.run_interactive()
        assert result == "Interactive Mode"

    def test_print_success(self, capsys):
        """成功メッセージが正しく表示される"""
        cli = ConcreteCLI()
        cli.print_success("テスト成功")

        captured = capsys.readouterr()
        assert "✅ テスト成功" in captured.out

    def test_print_success_logs(self):
        """print_successがログを出力する"""
        cli = ConcreteCLI()
        with patch.object(cli.logger, 'info') as mock_info:
            cli.print_success("テスト成功")
            mock_info.assert_called_once_with("テスト成功")

    def test_print_error(self, capsys):
        """エラーメッセージが正しく表示される"""
        cli = ConcreteCLI()
        cli.print_error("テストエラー")

        captured = capsys.readouterr()
        assert "❌ テストエラー" in captured.out

    def test_print_error_logs(self):
        """print_errorがログを出力する"""
        cli = ConcreteCLI()
        with patch.object(cli.logger, 'error') as mock_error:
            cli.print_error("テストエラー")
            mock_error.assert_called_once_with("テストエラー")

    def test_print_warning(self, capsys):
        """警告メッセージが正しく表示される"""
        cli = ConcreteCLI()
        cli.print_warning("テスト警告")

        captured = capsys.readouterr()
        assert "⚠️  テスト警告" in captured.out

    def test_print_warning_logs(self):
        """print_warningがログを出力する"""
        cli = ConcreteCLI()
        with patch.object(cli.logger, 'warning') as mock_warning:
            cli.print_warning("テスト警告")
            mock_warning.assert_called_once_with("テスト警告")

    def test_print_info(self, capsys):
        """情報メッセージが正しく表示される"""
        cli = ConcreteCLI()
        cli.print_info("テスト情報")

        captured = capsys.readouterr()
        assert "ℹ️  テスト情報" in captured.out

    def test_print_info_logs(self):
        """print_infoがログを出力する"""
        cli = ConcreteCLI()
        with patch.object(cli.logger, 'info') as mock_info:
            cli.print_info("テスト情報")
            mock_info.assert_called_once_with("テスト情報")

    def test_print_progress(self, capsys):
        """進捗メッセージが正しく表示される"""
        cli = ConcreteCLI()
        cli.print_progress("テスト進捗")

        captured = capsys.readouterr()
        assert "🔄 テスト進捗" in captured.out

    def test_print_progress_logs(self):
        """print_progressがログを出力する"""
        cli = ConcreteCLI()
        with patch.object(cli.logger, 'info') as mock_info:
            cli.print_progress("テスト進捗")
            mock_info.assert_called_once_with("テスト進捗")


class TestBaseCLIAbstract:
    """BaseCLIが抽象クラスとして機能することのテスト"""

    def test_cannot_instantiate_directly(self):
        """BaseCLIを直接インスタンス化できない"""
        with pytest.raises(TypeError):
            BaseCLI()

    def test_incomplete_subclass_raises_error(self):
        """抽象メソッドを実装しないサブクラスはインスタンス化できない"""
        class IncompleteCLI(BaseCLI):
            def show_menu(self):
                return "Menu"
            # run_interactiveを実装しない

        with pytest.raises(TypeError):
            IncompleteCLI()
