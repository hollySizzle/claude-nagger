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

    # diagnose サブコマンド
    subparsers.add_parser(
        "diagnose",
        help="環境診断・設定確認"
    )

    # test-hook サブコマンド
    test_hook_parser = subparsers.add_parser(
        "test-hook",
        help="フック発火をテスト"
    )
    test_hook_parser.add_argument(
        "--tool", "-t", required=True,
        help="テスト対象のツール名（Bash, Edit, Write等）"
    )
    test_hook_parser.add_argument(
        "--cmd", "-c", dest="test_cmd",
        help="テスト対象のコマンド（Bashツール用）"
    )
    test_hook_parser.add_argument(
        "--file", dest="test_file",
        help="テスト対象のファイルパス（Edit/Writeツール用）"
    )

    # match-test サブコマンド（パターンマッチングdry-run）
    match_test_parser = subparsers.add_parser(
        "match-test",
        help="パターンマッチングをテスト（dry-run）"
    )
    match_test_parser.add_argument(
        "--file", "-f", dest="match_file",
        help="テスト対象のファイルパス"
    )
    match_test_parser.add_argument(
        "--command", "-c", dest="match_command",
        help="テスト対象のコマンド"
    )
    match_test_parser.add_argument(
        "--pattern", "-p", required=True,
        help="マッチングパターン"
    )

    # hook サブコマンド（フック実行用）
    hook_parser = subparsers.add_parser(
        "hook",
        help="フックを実行（Claude Code PreToolUse用）"
    )
    hook_subparsers = hook_parser.add_subparsers(dest="hook_name", help="フック名")

    # hook session-startup
    hook_subparsers.add_parser(
        "session-startup",
        help="セッション開始時フック"
    )

    # hook implementation-design
    hook_subparsers.add_parser(
        "implementation-design",
        help="実装設計確認フック"
    )

    # hook compact-detected
    hook_subparsers.add_parser(
        "compact-detected",
        help="compact検知フック"
    )

    # notify サブコマンド（Discord通知）
    notify_parser = subparsers.add_parser(
        "notify",
        help="Discord通知を送信"
    )
    notify_parser.add_argument(
        "message",
        nargs="?",
        default="hello",
        help="送信するメッセージ"
    )

    args = parser.parse_args()

    if args.version:
        from shared.version import __version__
        print(f"claude-nagger v{__version__}")
        return 0

    if args.command == "install-hooks":
        from application.install_hooks import InstallHooksCommand
        cmd = InstallHooksCommand(
            force=args.force,
            dry_run=args.dry_run
        )
        return cmd.execute()

    if args.command == "diagnose":
        from application.diagnose import DiagnoseCommand
        cmd = DiagnoseCommand()
        return cmd.execute()

    if args.command == "test-hook":
        from application.test_hook import TestHookCommand
        cmd = TestHookCommand(
            tool=args.tool,
            command=args.test_cmd,
            file_path=args.test_file
        )
        return cmd.execute()

    if args.command == "match-test":
        from application.match_test import MatchTestCommand
        cmd = MatchTestCommand(
            file_path=args.match_file,
            command=args.match_command,
            pattern=args.pattern
        )
        return cmd.execute()

    if args.command == "notify":
        from infrastructure.notifiers.discord_notifier import DiscordNotifier
        notifier = DiscordNotifier()
        result = notifier.send_sync(args.message)
        if result['success']:
            print(f"Message sent to Discord [{result['agent_name']}]: {result['message']}", file=sys.stderr)
        else:
            print(f"Failed to send Discord message: {result['error']}", file=sys.stderr)
        return 0

    if args.command == "hook":
        if args.hook_name == "session-startup":
            from domain.hooks.session_startup_hook import SessionStartupHook
            hook = SessionStartupHook()
            return hook.run()

        if args.hook_name == "implementation-design":
            from domain.hooks.implementation_design_hook import ImplementationDesignHook
            hook = ImplementationDesignHook()
            return hook.run()

        if args.hook_name == "compact-detected":
            from domain.hooks.compact_detected_hook import CompactDetectedHook
            hook = CompactDetectedHook()
            return hook.run()

        # hook名未指定時はhookヘルプ表示
        hook_parser.print_help()
        return 0

    # コマンド未指定時はヘルプ表示
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
