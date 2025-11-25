"""品質チェックオーケストレータ（スタブ実装）"""

from shared.base.base_cli import BaseCLI
import questionary


class QualityCheckCLI(BaseCLI):
    """品質チェックオーケストレータ"""

    def show_menu(self) -> str:
        """サブメニュー表示"""
        choices = [
            "📐 PlantUMLチェック",
            "📝 Markdownチェック",
            "🔙 メインメニューに戻る"
        ]

        return questionary.select(
            "品質チェック機能を選択:",
            choices=choices
        ).ask()

    def run_interactive(self):
        """対話的実行"""
        while True:
            choice = self.show_menu()

            if not choice or "メインメニュー" in choice:
                break

            if "PlantUML" in choice:
                self.print_info("PlantUMLチェック機能は開発中です")
            elif "Markdown" in choice:
                self.print_info("Markdownチェック機能は開発中です")