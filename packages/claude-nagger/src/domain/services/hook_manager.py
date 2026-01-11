"""Claude Code Hooks管理サービス"""

import json
from typing import Dict, List, Optional
from pathlib import Path


class HookManager:
    """Claude Code Hooks管理サービス"""

    HOOK_EVENTS = [
        "PreToolUse",
        "PostToolUse",
        "Notification",
        "Stop",
        "SubagentStop"
    ]

    def __init__(self, claude_dir: Optional[Path] = None):
        """
        初期化
        
        Args:
            claude_dir: .claudeディレクトリのパス（省略時はカレントディレクトリ）
        """
        self.claude_dir = claude_dir or Path.cwd() / ".claude"
        self.settings_file = self.claude_dir / "settings.json"
        self.settings_local_file = self.claude_dir / "settings.local.json"

    def load_settings(self, local: bool = False) -> Dict:
        """
        設定ファイルを読み込む
        
        Args:
            local: ローカル設定ファイルを読み込むかどうか
            
        Returns:
            設定内容の辞書
        """
        settings_file = self.settings_local_file if local else self.settings_file
        
        if not settings_file.exists():
            return {"hooks": {}}
        
        try:
            with open(settings_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {"hooks": {}}

    def save_settings(self, settings: Dict, local: bool = False) -> Dict:
        """
        設定ファイルを保存する
        
        Args:
            settings: 保存する設定内容
            local: ローカル設定ファイルに保存するかどうか
            
        Returns:
            実行結果
        """
        try:
            settings_file = self.settings_local_file if local else self.settings_file
            
            # ディレクトリがなければ作成
            self.claude_dir.mkdir(parents=True, exist_ok=True)
            
            # 設定を保存
            with open(settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            
            return {'success': True, 'file': str(settings_file)}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def add_hook(self, event: str, matcher: str, command: str, 
                 timeout: Optional[int] = None, local: bool = False) -> Dict:
        """
        フックを追加する
        
        Args:
            event: フックイベント（PreToolUse, PostToolUse, Notification, Stop, SubagentStop）
            matcher: マッチャー（ツール名のパターン、空文字列で全て）
            command: 実行するコマンド
            timeout: タイムアウト秒数（省略可）
            local: ローカル設定に追加するかどうか
            
        Returns:
            実行結果
        """
        if event not in self.HOOK_EVENTS:
            return {'success': False, 'error': f'無効なイベント: {event}'}
        
        # 現在の設定を読み込む
        settings = self.load_settings(local)
        
        # hooks構造を初期化
        if 'hooks' not in settings:
            settings['hooks'] = {}
        
        if event not in settings['hooks']:
            settings['hooks'][event] = []
        
        # 同じマッチャーを探す
        matcher_entry = None
        for entry in settings['hooks'][event]:
            if entry.get('matcher') == matcher:
                matcher_entry = entry
                break
        
        # マッチャーエントリがなければ作成
        if not matcher_entry:
            matcher_entry = {'matcher': matcher, 'hooks': []}
            settings['hooks'][event].append(matcher_entry)
        
        # 新しいフックを作成
        new_hook = {'type': 'command', 'command': command}
        if timeout:
            new_hook['timeout'] = timeout
        
        # 重複チェック
        for hook in matcher_entry['hooks']:
            if hook.get('command') == command:
                return {'success': False, 'error': '同じコマンドが既に登録されています'}
        
        # フックを追加
        matcher_entry['hooks'].append(new_hook)
        
        # 設定を保存
        result = self.save_settings(settings, local)
        if result['success']:
            result['message'] = f'{event}フックを追加しました: {command}'
        
        return result

    def remove_hook(self, event: str, matcher: str, command: str, 
                    local: bool = False) -> Dict:
        """
        フックを削除する
        
        Args:
            event: フックイベント
            matcher: マッチャー
            command: 削除するコマンド（部分一致）
            local: ローカル設定から削除するかどうか
            
        Returns:
            実行結果
        """
        if event not in self.HOOK_EVENTS:
            return {'success': False, 'error': f'無効なイベント: {event}'}
        
        # 現在の設定を読み込む
        settings = self.load_settings(local)
        
        if 'hooks' not in settings or event not in settings['hooks']:
            return {'success': False, 'error': f'{event}フックが存在しません'}
        
        removed_count = 0
        
        # マッチャーエントリを探す
        for entry in settings['hooks'][event]:
            if entry.get('matcher') == matcher:
                # 削除対象のフックを探す
                hooks_to_remove = []
                for hook in entry['hooks']:
                    if command in hook.get('command', ''):
                        hooks_to_remove.append(hook)
                
                # フックを削除
                for hook in hooks_to_remove:
                    entry['hooks'].remove(hook)
                    removed_count += 1
                
                # マッチャーエントリが空になったら削除
                if not entry['hooks']:
                    settings['hooks'][event].remove(entry)
        
        if removed_count == 0:
            return {'success': False, 'error': '削除対象のフックが見つかりませんでした'}
        
        # 設定を保存
        result = self.save_settings(settings, local)
        if result['success']:
            result['message'] = f'{removed_count}個のフックを削除しました'
        
        return result

    def list_hooks(self, event: Optional[str] = None, local: bool = False) -> Dict:
        """
        フック一覧を取得する
        
        Args:
            event: 特定のイベントのみ取得（省略時は全て）
            local: ローカル設定を取得するかどうか
            
        Returns:
            フック一覧
        """
        settings = self.load_settings(local)
        
        if 'hooks' not in settings:
            return {'hooks': {}}
        
        if event:
            if event not in self.HOOK_EVENTS:
                return {'success': False, 'error': f'無効なイベント: {event}'}
            
            return {
                'hooks': {
                    event: settings['hooks'].get(event, [])
                }
            }
        
        return {'hooks': settings['hooks']}

    def clear_hooks(self, event: Optional[str] = None, local: bool = False) -> Dict:
        """
        フックをクリアする
        
        Args:
            event: 特定のイベントのみクリア（省略時は全て）
            local: ローカル設定をクリアするかどうか
            
        Returns:
            実行結果
        """
        settings = self.load_settings(local)
        
        if event:
            if event not in self.HOOK_EVENTS:
                return {'success': False, 'error': f'無効なイベント: {event}'}
            
            if 'hooks' in settings and event in settings['hooks']:
                settings['hooks'][event] = []
                message = f'{event}フックをクリアしました'
            else:
                return {'success': False, 'error': f'{event}フックが存在しません'}
        else:
            settings['hooks'] = {}
            message = '全てのフックをクリアしました'
        
        # 設定を保存
        result = self.save_settings(settings, local)
        if result['success']:
            result['message'] = message
        
        return result

    def import_hooks(self, source_file: Path, local: bool = False) -> Dict:
        """
        別のファイルからフックをインポートする
        
        Args:
            source_file: インポート元のファイル
            local: ローカル設定にインポートするかどうか
            
        Returns:
            実行結果
        """
        if not source_file.exists():
            return {'success': False, 'error': f'ファイルが存在しません: {source_file}'}
        
        try:
            with open(source_file, 'r', encoding='utf-8') as f:
                source_settings = json.load(f)
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'JSONの解析に失敗しました: {e}'}
        
        if 'hooks' not in source_settings:
            return {'success': False, 'error': 'フック設定が含まれていません'}
        
        # 現在の設定を読み込む
        settings = self.load_settings(local)
        
        # フックをマージ
        if 'hooks' not in settings:
            settings['hooks'] = {}
        
        imported_count = 0
        for event, matchers in source_settings['hooks'].items():
            if event not in self.HOOK_EVENTS:
                continue
            
            if event not in settings['hooks']:
                settings['hooks'][event] = []
            
            for matcher_entry in matchers:
                # 既存のマッチャーエントリを探す
                existing_entry = None
                for entry in settings['hooks'][event]:
                    if entry.get('matcher') == matcher_entry.get('matcher'):
                        existing_entry = entry
                        break
                
                if not existing_entry:
                    # 新規追加
                    settings['hooks'][event].append(matcher_entry)
                    imported_count += len(matcher_entry.get('hooks', []))
                else:
                    # 既存にマージ
                    for hook in matcher_entry.get('hooks', []):
                        # 重複チェック
                        duplicate = False
                        for existing_hook in existing_entry['hooks']:
                            if existing_hook.get('command') == hook.get('command'):
                                duplicate = True
                                break
                        
                        if not duplicate:
                            existing_entry['hooks'].append(hook)
                            imported_count += 1
        
        # 設定を保存
        result = self.save_settings(settings, local)
        if result['success']:
            result['message'] = f'{imported_count}個のフックをインポートしました'
        
        return result