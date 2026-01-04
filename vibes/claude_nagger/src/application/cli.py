#!/usr/bin/env python3
"""claude-nagger CLI エントリーポイント"""

import argparse
import sys
from pathlib import Path


def main():
    """メインエントリーポイント"""
    parser = argparse.ArgumentParser(
        prog="claude-nagger",
        description="Claude Code統合ツール - フック・規約管理CLI"
    )
    parser.add_argument(
        "--version", action="store_true", help="バージョン表示"
    )

    subparsers = parser.add_subparsers(dest="command", help="サブコマンド")

    # install-hooks サブコマンド
    install_parser = subparsers.add_parser(
        "install-hooks",
        help="フック設定をインストール"
    )
    install_parser.add_argument(
        "--force", "-f", action="store_true",
        help="既存ファイルを上書き"
    )
    install_parser.add_argument(
        "--dry-run", action="store_true",
        help="実行内容を表示するのみ（実際には変更しない）"
    )

    args = parser.parse_args()

    if args.version:
        print("claude-nagger v1.0.0")
        return 0

    if args.command == "install-hooks":
        from application.install_hooks import InstallHooksCommand
        cmd = InstallHooksCommand(
            force=args.force,
            dry_run=args.dry_run
        )
        return cmd.execute()

    # コマンド未指定時はヘルプ表示
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
