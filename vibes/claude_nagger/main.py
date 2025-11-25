#!/usr/bin/env python3
"""
vibes_tools: Claude Code統合ツールシステム
旧Node.jsツールのPython完全移行版
"""

import os
import sys
from pathlib import Path

# srcディレクトリをPython pathに追加
src_path = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_path))

try:
    import questionary
except ImportError:
    print("questionaryが見つかりません: pip install questionary")
    sys.exit(1)


class VibesToolsCLI:
    """統合CLIメインクラス（純粋ルータ）"""

    # 直接実行ハンドラーマッピング
    DIRECT_HANDLERS = {
        'doc': 'run_document_management',
        'hook': 'run_hook_management',
        'quality': 'run_quality_check',
        'setup': 'run_project_setup'
    }
    
    # ヘルプ用の説明文
    DIRECT_HELP_TEXT = {
        'doc': 'ドキュメント管理',
        'hook': 'フック管理', 
        'quality': '品質チェック',
        'setup': 'プロジェクトセットアップ'
    }

    def __init__(self):
        self.working_dir = Path(__file__).parent

    def show_banner(self):
        """バナー表示"""
        print("=" * 60)
        print("🛠️  Vibes Tools - Claude Code Integration System")
        print("    旧Node.jsツール完全Python移行版")
        print("=" * 60)
        print()

    def main_menu(self) -> str:
        """メインメニュー表示"""
        choices = [
            "📚 ドキュメント管理 (TOC更新, 参照チェック, 生成)",
            "🪝 フック管理 (設定, 実行, モニタリング)",
            "✅ 品質チェック (PlantUML, Markdown, コード)",
            "🚀 プロジェクトセットアップ",
            "🔧 システム設定",
            "❌ 終了"
        ]

        return questionary.select(
            "実行したい機能を選択してください:",
            choices=choices
        ).ask()

    def run_document_management(self):
        """ドキュメント管理オーケストレータに委譲"""
        from application.document_management import DocumentManagementCLI

        cli = DocumentManagementCLI()
        cli.run_interactive()



    def run_hook_management(self):
        """フック管理オーケストレータに委譲"""
        from application.claude_hook_management import HookManagementCLI

        cli = HookManagementCLI()
        cli.run_interactive()

    def run_quality_check(self):
        """品質チェックオーケストレータに委譲"""
        from application.quality_check import QualityCheckCLI

        cli = QualityCheckCLI()
        cli.run_interactive()

    def run_project_setup(self):
        """プロジェクトセットアップオーケストレータに委譲"""
        from application.project_setup import ProjectSetupCLI

        cli = ProjectSetupCLI()
        cli.run_interactive()

    def run_system_config(self):
        """システム設定管理"""
        from infrastructure.config.config_manager import ConfigManager

        config = ConfigManager()
        config.interactive_setup()

    def run(self):
        """メイン実行ループ"""
        self.show_banner()

        while True:
            try:
                choice = self.main_menu()

                if not choice or "終了" in choice:
                    break

                if "ドキュメント管理" in choice:
                    self.run_document_management()
                elif "フック管理" in choice:
                    self.run_hook_management()
                elif "品質チェック" in choice:
                    self.run_quality_check()
                elif "プロジェクトセットアップ" in choice:
                    self.run_project_setup()
                elif "システム設定" in choice:
                    self.run_system_config()

                # 継続確認
                if not questionary.confirm("他の機能を実行しますか？", default=True).ask():
                    break

            except KeyboardInterrupt:
                print("\n👋 終了します")
                break

        print("\n👋 Vibes Tools を終了します")


def main():
    """エントリポイント"""
    # 責務は純粋なルータである｡オプションは全て各オーケストラに直接渡す
    import argparse

    parser = argparse.ArgumentParser(description="Vibes Tools")
    parser.add_argument('--version', action='store_true', help='バージョン表示')
    # ヘルプテキストを動的生成
    direct_help_lines = []
    for key, desc in VibesToolsCLI.DIRECT_HELP_TEXT.items():
        direct_help_lines.append(f'{key}: {desc}')
    direct_help_text = '特定機能を直接実行 (' + ', '.join(direct_help_lines) + ')'
    
    parser.add_argument('--direct', choices=list(VibesToolsCLI.DIRECT_HANDLERS.keys()),
                       help=direct_help_text)
    
    # 非対話モード用のオプション（オーケストレータに委譲）
    from application.document_management import DocumentManagementCLI
    DocumentManagementCLI.add_parser_arguments(parser)

    args = parser.parse_args()

    if args.version:
        print("Vibes Tools v1.0.0")
        return 0

    if args.direct:
        cli = VibesToolsCLI()
        # --directと--actionが両方指定された場合は非対話モード
        if args.direct == 'doc' and args.action:
            from application.document_management import DocumentManagementCLI
            doc_cli = DocumentManagementCLI()
            return doc_cli.run_with_args(
                args.action, 
                getattr(args, 'file', None), 
                getattr(args, 'quiet', False),
                getattr(args, 'doc_type', None),
                getattr(args, 'filename', None)
            )
        else:
            # 通常の対話モード
            method_name = cli.DIRECT_HANDLERS.get(args.direct)
            if method_name:
                getattr(cli, method_name)()
        return 0

    # 非対話モード: 適切なオーケストレータに委譲
    if args.action:
        from application.document_management import DocumentManagementCLI
        
        # アクションを処理できるオーケストレータを探す
        if DocumentManagementCLI.can_handle_action(args.action):
            cli = DocumentManagementCLI()
            return cli.run_with_args(
                args.action, 
                getattr(args, 'file', None), 
                getattr(args, 'quiet', False),
                getattr(args, 'doc_type', None),
                getattr(args, 'filename', None)
            )
        else:
            print(f"エラー: 未対応のアクション: {args.action}")
            return 1

    # 対話モード
    cli = VibesToolsCLI()
    cli.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())