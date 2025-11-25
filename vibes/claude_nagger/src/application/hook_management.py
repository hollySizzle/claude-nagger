"""フック管理オーケストレータ（スタブ実装）"""

from shared.base.base_cli import BaseCLI
import questionary


class HookManagementCLI(BaseCLI):
    """フック管理オーケストレータ"""

    def show_menu(self) -> str:
        """サブメニュー表示"""
        choices = [
            "🔧 フック設定表示",
            "🔙 メインメニューに戻る"
        ]

        return questionary.select(
            "フック管理機能を選択:",
            choices=choices
        ).ask()

    def run_interactive(self):
        """対話的実行"""
        while True:
            choice = self.show_menu()

            if not choice or "メインメニュー" in choice:
                break

            if "フック設定表示" in choice:
                self.print_info("フック機能は開発中です")