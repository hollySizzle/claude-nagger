"""フック実行エンジン"""

import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from domain.services.hook_manager import HookManager
from domain.hooks.implementation_design_hook import ImplementationDesignHook


class HookExecutor:
    """フック実行エンジン"""

    def __init__(self, claude_dir: Optional[Path] = None):
        """
        初期化
        
        Args:
            claude_dir: .claudeディレクトリのパス
        """
        self.hook_manager = HookManager(claude_dir)
        
        # 内蔵フックの登録
        self.builtin_hooks = {
            'implementation_design': ImplementationDesignHook
        }

    def execute_hook(self, event: str, tool_name: str, tool_input: Dict[str, Any], 
                     session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        該当するフックを実行
        
        Args:
            event: イベント名（PreToolUse, PostToolUse等）
            tool_name: ツール名
            tool_input: ツールへの入力
            session_id: セッションID
            
        Returns:
            フック実行結果のリスト
        """
        results = []
        
        # 設定ファイルからフックを取得
        hooks_config = self.hook_manager.list_hooks(event)
        
        if 'hooks' in hooks_config:
            event_hooks = hooks_config['hooks'].get(event, [])
            
            for matcher_entry in event_hooks:
                matcher = matcher_entry.get('matcher', '')
                
                # マッチャーがツール名と一致するか確認
                if self._matches_tool(tool_name, matcher):
                    for hook in matcher_entry.get('hooks', []):
                        result = self._execute_single_hook(
                            hook, event, tool_name, tool_input, session_id
                        )
                        if result:
                            results.append(result)
        
        # 内蔵フックの実行（実装設計フック等）
        if event == 'PreToolUse' and (tool_name in ['Edit', 'Write', 'MultiEdit'] or tool_name.startswith('mcp__serena__')):
            result = self._execute_builtin_hook(
                'implementation_design', tool_input, session_id
            )
            if result:
                results.append(result)
        
        return results

    def _matches_tool(self, tool_name: str, matcher: str) -> bool:
        """
        ツール名がマッチャーパターンに一致するか確認
        
        Args:
            tool_name: ツール名
            matcher: マッチャーパターン
            
        Returns:
            一致する場合True
        """
        if not matcher:  # 空文字列は全てにマッチ
            return True
        
        # パイプ区切りのOR条件
        if '|' in matcher:
            patterns = matcher.split('|')
            return any(self._matches_single_pattern(tool_name, p.strip()) for p in patterns)
        
        return self._matches_single_pattern(tool_name, matcher)

    def _matches_single_pattern(self, tool_name: str, pattern: str) -> bool:
        """
        単一パターンとのマッチング
        
        Args:
            tool_name: ツール名
            pattern: パターン
            
        Returns:
            一致する場合True
        """
        # ワイルドカード処理
        if '*' in pattern:
            import fnmatch
            return fnmatch.fnmatch(tool_name, pattern)
        
        # 完全一致
        return tool_name == pattern

    def _execute_single_hook(self, hook_config: Dict[str, Any], event: str, 
                            tool_name: str, tool_input: Dict[str, Any], 
                            session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        単一のフックを実行
        
        Args:
            hook_config: フック設定
            event: イベント名
            tool_name: ツール名
            tool_input: ツール入力
            session_id: セッションID
            
        Returns:
            フック実行結果
        """
        if hook_config.get('type') != 'command':
            return None
        
        command = hook_config.get('command')
        if not command:
            return None
        
        timeout = hook_config.get('timeout', 60)
        
        # 入力データを構築
        input_data = {
            'event': event,
            'tool_name': tool_name,
            'tool_input': tool_input
        }
        
        if session_id:
            input_data['session_id'] = session_id
        
        try:
            # コマンドを実行
            result = subprocess.run(
                command,
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
                shell=True,
                timeout=timeout
            )
            
            if result.stdout:
                try:
                    return json.loads(result.stdout)
                except json.JSONDecodeError:
                    return {
                        'decision': 'allow',
                        'reason': '',
                        'error': 'Invalid JSON response from hook'
                    }
            
            return {'decision': 'allow', 'reason': ''}
            
        except subprocess.TimeoutExpired:
            return {
                'decision': 'allow',
                'reason': '',
                'error': f'Hook timed out after {timeout} seconds'
            }
        except Exception as e:
            return {
                'decision': 'allow',
                'reason': '',
                'error': str(e)
            }

    def _execute_builtin_hook(self, hook_name: str, tool_input: Dict[str, Any], 
                             session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        内蔵フックを実行
        
        Args:
            hook_name: フック名
            tool_input: ツール入力
            session_id: セッションID
            
        Returns:
            フック実行結果
        """
        hook_class = self.builtin_hooks.get(hook_name)
        if not hook_class:
            return None
        
        try:
            # フックインスタンスを作成
            hook = hook_class()
            
            # 入力データを構築
            input_data = {
                'tool_input': tool_input
            }
            
            if session_id:
                input_data['session_id'] = session_id
                
                # 既に処理済みの場合はスキップ
                if hook.is_session_processed(session_id):
                    return None
            
            # 処理対象かチェック
            if not hook.should_process(input_data):
                return None
            
            # フック処理を実行
            result = hook.process(input_data)
            
            # セッションIDがある場合は処理済みとしてマーク
            if session_id and result.get('decision') in ['block', 'warn']:
                hook.mark_session_processed(session_id)
            
            return result
            
        except Exception as e:
            return {
                'decision': 'allow',
                'reason': '',
                'error': f'Builtin hook error: {str(e)}'
            }

    def register_hook_via_cli(self, event: str, matcher: str, command: str, 
                             timeout: Optional[int] = None, local: bool = False) -> Dict[str, Any]:
        """
        CLIからフックを登録
        
        Args:
            event: イベント名
            matcher: マッチャーパターン
            command: 実行コマンド
            timeout: タイムアウト
            local: ローカル設定に保存
            
        Returns:
            実行結果
        """
        # Pythonスクリプトをフックコマンドとして登録する場合の例
        if command.endswith('.py'):
            # Pythonスクリプトのフルパスに変換
            command = f"python3 {Path(command).resolve()}"
        
        return self.hook_manager.add_hook(event, matcher, command, timeout, local)