"""プロジェクトセットアップオーケストレータ（スタブ実装）"""

from shared.base.base_cli import BaseCLI
import questionary


class ProjectSetupCLI(BaseCLI):
    """プロジェクトセットアップオーケストレータ"""

    def show_menu(self) -> str:
        """サブメニュー表示"""
        choices = [
            "🚀 初期セットアップ",
            "🔙 メインメニューに戻る"
        ]

        return questionary.select(
            "セットアップ機能を選択:",
            choices=choices
        ).ask()

    def run_interactive(self):
        """対話的実行"""
        while True:
            choice = self.show_menu()

            if not choice or "メインメニュー" in choice:
                break

            if "初期セットアップ" in choice:
                self.print_info("セットアップ機能は開発中です")