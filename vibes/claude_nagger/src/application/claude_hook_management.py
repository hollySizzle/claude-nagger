"""Claude Code Hooks管理オーケストレータ"""

from typing import Optional
from pathlib import Path
import questionary
from rich.table import Table
from rich.console import Console
from domain.services.hook_manager import HookManager
from infrastructure.config.config_manager import ConfigManager
from infrastructure.hooks.hook_executor import HookExecutor
from shared.base.base_cli import BaseCLI


class HookManagementCLI(BaseCLI):
    """Claude Code Hooks管理オーケストレータ"""

    def __init__(self):
        super().__init__()
        self.config = ConfigManager()
        self.console = Console()
        
        # デフォルトの.claudeディレクトリを設定から取得
        claude_dir = self.config.get_claude_dir()
        self.hook_manager = HookManager(claude_dir)
        self.hook_executor = HookExecutor(claude_dir)

    def show_menu(self) -> str:
        """サブメニュー表示"""
        choices = [
            "📋 フック一覧表示",
            "➕ フック追加",
            "🗑️ フック削除",
            "🔄 フックインポート",
            "🧹 フッククリア",
            "🧪 フックテスト実行",
            "📝 規約ルール確認",
            "⚙️ 設定ディレクトリ変更",
            "🔙 メインメニューに戻る"
        ]

        return questionary.select(
            "Claude Code Hooks管理:",
            choices=choices
        ).ask()

    def run_interactive(self):
        """対話的実行"""
        while True:
            choice = self.show_menu()

            if not choice or "メインメニュー" in choice:
                break

            if "フック一覧表示" in choice:
                self.list_hooks()
            elif "フック追加" in choice:
                self.add_hook()
            elif "フック削除" in choice:
                self.remove_hook()
            elif "フックインポート" in choice:
                self.import_hooks()
            elif "フッククリア" in choice:
                self.clear_hooks()
            elif "フックテスト実行" in choice:
                self.test_hook()
            elif "規約ルール確認" in choice:
                self.show_convention_rules()
            elif "設定ディレクトリ変更" in choice:
                self.change_claude_dir()

    def list_hooks(self):
        """フック一覧表示"""
        # プロジェクト設定かローカル設定か選択
        source = questionary.select(
            "どの設定を表示しますか？",
            choices=["プロジェクト設定 (settings.json)", "ローカル設定 (settings.local.json)"]
        ).ask()
        
        local = "ローカル" in source
        
        # イベントフィルタ
        event_filter = questionary.select(
            "表示するイベント:",
            choices=["全て"] + HookManager.HOOK_EVENTS
        ).ask()
        
        event = None if event_filter == "全て" else event_filter
        
        # フック一覧取得
        result = self.hook_manager.list_hooks(event, local)
        
        if 'error' in result:
            self.print_error(result['error'])
            return
        
        # テーブル表示
        table = Table(title=f"Claude Code Hooks ({source})")
        table.add_column("イベント", style="cyan")
        table.add_column("マッチャー", style="yellow")
        table.add_column("コマンド", style="green")
        table.add_column("タイムアウト", style="magenta")
        
        for event_name, matchers in result['hooks'].items():
            for matcher_entry in matchers:
                matcher = matcher_entry.get('matcher', '')
                for hook in matcher_entry.get('hooks', []):
                    command = hook.get('command', '')
                    timeout = str(hook.get('timeout', '')) if 'timeout' in hook else ''
                    table.add_row(event_name, matcher or "(全て)", command, timeout)
        
        self.console.print(table)

    def add_hook(self):
        """フック追加"""
        # イベント選択（説明付き）
        event_choices = [
            questionary.Choice("PreToolUse - ツール実行直前に発火", value="PreToolUse"),
            questionary.Choice("PostToolUse - ツール実行完了直後に発火", value="PostToolUse"),
            questionary.Choice("Notification - Claude Codeが通知を送信する時に発火", value="Notification"),
            questionary.Choice("Stop - Claude Codeの応答完了時に発火", value="Stop"),
            questionary.Choice("SubagentStop - サブエージェント(Task)完了時に発火", value="SubagentStop")
        ]
        
        event = questionary.select(
            "フックイベント:",
            choices=event_choices
        ).ask()
        
        if not event:
            return
        
        # マッチャー入力（PreToolUse/PostToolUseの場合）
        matcher = ""
        if event in ["PreToolUse", "PostToolUse"]:
            matcher_type = questionary.select(
                "マッチャータイプ:",
                choices=["全てのツール", "特定のツール"]
            ).ask()
            
            if matcher_type == "特定のツール":
                # 一般的なツール名の提案
                common_tools = [
                    "Bash", "Edit", "Write", "MultiEdit", "Read",
                    "Grep", "Glob", "Task", "WebFetch", "WebSearch"
                ]
                
                use_common = questionary.confirm(
                    "一般的なツール名から選択しますか？"
                ).ask()
                
                if use_common:
                    matcher = questionary.select(
                        "ツール名:",
                        choices=common_tools + ["カスタム入力"]
                    ).ask()
                    
                    if matcher == "カスタム入力":
                        matcher = questionary.text(
                            "マッチャーパターン (例: Edit|Write, Notebook.*):"
                        ).ask()
                else:
                    matcher = questionary.text(
                        "マッチャーパターン (例: Edit|Write, Notebook.*):"
                    ).ask()
        
        # コマンド入力
        command = questionary.text(
            "実行するコマンド:"
        ).ask()
        
        if not command:
            return
        
        # タイムアウト設定
        set_timeout = questionary.confirm(
            "タイムアウトを設定しますか？（デフォルト: 60秒）"
        ).ask()
        
        timeout = None
        if set_timeout:
            timeout = questionary.text(
                "タイムアウト秒数:",
                validate=lambda x: x.isdigit() or "数値を入力してください"
            ).ask()
            timeout = int(timeout) if timeout else None
        
        # 保存先選択
        target = questionary.select(
            "保存先:",
            choices=["プロジェクト設定 (settings.json)", "ローカル設定 (settings.local.json)"]
        ).ask()
        
        local = "ローカル" in target
        
        # フック追加
        result = self.hook_manager.add_hook(event, matcher, command, timeout, local)
        
        if result['success']:
            self.print_success(result.get('message', 'フックを追加しました'))
        else:
            self.print_error(result.get('error', 'フックの追加に失敗しました'))

    def remove_hook(self):
        """フック削除"""
        # 削除元選択
        source = questionary.select(
            "削除元:",
            choices=["プロジェクト設定 (settings.json)", "ローカル設定 (settings.local.json)"]
        ).ask()
        
        local = "ローカル" in source
        
        # 現在のフック一覧を取得
        result = self.hook_manager.list_hooks(local=local)
        
        if 'error' in result or not result['hooks']:
            self.print_warning("削除可能なフックがありません")
            return
        
        # イベント選択
        events_with_hooks = [event for event, matchers in result['hooks'].items() if matchers]
        
        if not events_with_hooks:
            self.print_warning("フックが登録されていません")
            return
        
        event = questionary.select(
            "削除するフックのイベント:",
            choices=events_with_hooks
        ).ask()
        
        if not event:
            return
        
        # マッチャー選択
        matchers = []
        for matcher_entry in result['hooks'][event]:
            matcher = matcher_entry.get('matcher', '')
            matchers.append(matcher or "(全て)")
        
        selected_matcher = questionary.select(
            "削除するフックのマッチャー:",
            choices=list(set(matchers))
        ).ask()
        
        matcher = "" if selected_matcher == "(全て)" else selected_matcher
        
        # コマンド選択
        commands = []
        for matcher_entry in result['hooks'][event]:
            if matcher_entry.get('matcher', '') == matcher:
                for hook in matcher_entry.get('hooks', []):
                    commands.append(hook.get('command', ''))
        
        if not commands:
            self.print_warning("削除可能なコマンドがありません")
            return
        
        selected_command = questionary.select(
            "削除するコマンド:",
            choices=commands
        ).ask()
        
        if not selected_command:
            return
        
        # 確認
        if questionary.confirm(f"本当に削除しますか？\n{selected_command}").ask():
            result = self.hook_manager.remove_hook(event, matcher, selected_command, local)
            
            if result['success']:
                self.print_success(result.get('message', 'フックを削除しました'))
            else:
                self.print_error(result.get('error', 'フックの削除に失敗しました'))

    def import_hooks(self):
        """フックインポート"""
        # インポート元ファイル
        source_file = questionary.text(
            "インポート元ファイルパス:"
        ).ask()
        
        if not source_file:
            return
        
        source_path = Path(source_file)
        
        # インポート先選択
        target = questionary.select(
            "インポート先:",
            choices=["プロジェクト設定 (settings.json)", "ローカル設定 (settings.local.json)"]
        ).ask()
        
        local = "ローカル" in target
        
        # インポート実行
        result = self.hook_manager.import_hooks(source_path, local)
        
        if result['success']:
            self.print_success(result.get('message', 'フックをインポートしました'))
        else:
            self.print_error(result.get('error', 'インポートに失敗しました'))

    def clear_hooks(self):
        """フッククリア"""
        # クリア対象選択
        target = questionary.select(
            "クリア対象:",
            choices=["プロジェクト設定 (settings.json)", "ローカル設定 (settings.local.json)"]
        ).ask()
        
        local = "ローカル" in target
        
        # クリア範囲選択
        scope = questionary.select(
            "クリア範囲:",
            choices=["全てのフック", "特定のイベントのみ"]
        ).ask()
        
        event = None
        if scope == "特定のイベントのみ":
            event_choices = [
                questionary.Choice("PreToolUse - ツール実行直前に発火", value="PreToolUse"),
                questionary.Choice("PostToolUse - ツール実行完了直後に発火", value="PostToolUse"),
                questionary.Choice("Notification - Claude Codeが通知を送信する時に発火", value="Notification"),
                questionary.Choice("Stop - Claude Codeの応答完了時に発火", value="Stop"),
                questionary.Choice("SubagentStop - サブエージェント(Task)完了時に発火", value="SubagentStop")
            ]
            
            event = questionary.select(
                "クリアするイベント:",
                choices=event_choices
            ).ask()
        
        # 確認
        confirm_msg = f"{'全ての' if not event else event}フックをクリアします。よろしいですか？"
        if questionary.confirm(confirm_msg).ask():
            result = self.hook_manager.clear_hooks(event, local)
            
            if result['success']:
                self.print_success(result.get('message', 'フックをクリアしました'))
            else:
                self.print_error(result.get('error', 'クリアに失敗しました'))

    def change_claude_dir(self):
        """設定ディレクトリ変更"""
        current_dir = self.hook_manager.claude_dir
        self.print_info(f"現在の設定ディレクトリ: {current_dir}")
        
        new_dir = questionary.text(
            "新しい.claudeディレクトリパス (相対パスまたは絶対パス):"
        ).ask()
        
        if new_dir:
            new_path = Path(new_dir).resolve()
            self.hook_manager = HookManager(new_path)
            self.print_success(f"設定ディレクトリを変更しました: {new_path}")
            
            # 設定ファイルの存在確認
            if not self.hook_manager.settings_file.exists():
                if questionary.confirm("settings.jsonが存在しません。作成しますか？").ask():
                    result = self.hook_manager.save_settings({"hooks": {}})
                    if result['success']:
                        self.print_success(f"settings.jsonを作成しました: {result['file']}")
                    else:
                        self.print_error(f"作成に失敗しました: {result.get('error')}")

    def test_hook(self):
        """フックテスト実行"""
        # テスト対象選択
        test_type = questionary.select(
            "テストタイプ:",
            choices=[
                "実装設計フック（内蔵）",
                "カスタムフック（settings.json）"
            ]
        ).ask()
        
        if test_type == "実装設計フック（内蔵）":
            # テスト用ファイルパス入力
            file_path = questionary.text(
                "テスト用ファイルパス（例: test/実装設計書.pu）:"
            ).ask()
            
            if file_path:
                # フック実行テスト
                results = self.hook_executor.execute_hook(
                    event='PreToolUse',
                    tool_name='Edit',
                    tool_input={'file_path': file_path},
                    session_id='test_session'
                )
                
                if results:
                    for result in results:
                        self.print_info(f"Decision: {result.get('decision')}")
                        if result.get('reason'):
                            self.print_warning(f"Reason:\n{result.get('reason')}")
                        if result.get('error'):
                            self.print_error(f"Error: {result.get('error')}")
                else:
                    self.print_info("フックは発火しませんでした（該当なし）")
        else:
            self.print_info("カスタムフックのテストは未実装です")

    def show_convention_rules(self):
        """規約ルール確認"""
        from domain.services.file_convention_matcher import FileConventionMatcher
        
        matcher = FileConventionMatcher()
        rules = matcher.list_rules()
        
        if not rules:
            self.print_warning("規約ルールが定義されていません")
            return
        
        # テーブル表示
        table = Table(title="ファイル編集規約ルール")
        table.add_column("ルール名", style="cyan")
        table.add_column("パターン", style="yellow")
        table.add_column("規約ドキュメント", style="green")
        table.add_column("重要度", style="magenta")
        
        for rule in rules:
            patterns_str = "\n".join(rule['patterns'])
            severity_display = "🚫 ブロック" if rule['severity'] == 'block' else "⚠️  警告"
            table.add_row(
                rule['name'],
                patterns_str,
                rule['convention_doc'],
                severity_display
            )
        
        self.console.print(table)
        
        # ファイルパスチェック機能
        if questionary.confirm("特定のファイルパスをチェックしますか？").ask():
            file_path = questionary.text("ファイルパス:").ask()
            if file_path:
                result = matcher.get_confirmation_message(file_path)
                if result:
                    self.print_warning(f"このファイルには以下の規約が適用されます:\n{result['message']}")
                else:
                    self.print_info("このファイルには特別な規約はありません")