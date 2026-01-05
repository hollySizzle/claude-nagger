"""hook_executor.py のテスト"""

import pytest
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock

from src.infrastructure.hooks.hook_executor import HookExecutor


class TestHookExecutorInit:
    """HookExecutor初期化のテスト"""

    def test_init_creates_hook_manager(self):
        """初期化時にHookManagerが作成される"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager:
            executor = HookExecutor()
            mock_manager.assert_called_once()

    def test_init_registers_builtin_hooks(self):
        """初期化時に内蔵フックが登録される"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            assert 'implementation_design' in executor.builtin_hooks

    def test_init_with_claude_dir(self):
        """claude_dirを指定して初期化できる"""
        claude_dir = Path('/tmp/test_claude')
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager:
            executor = HookExecutor(claude_dir=claude_dir)
            mock_manager.assert_called_once_with(claude_dir)


class TestMatchesTool:
    """_matches_tool メソッドのテスト"""

    def test_empty_matcher_matches_all(self):
        """空文字列マッチャーは全てにマッチ"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            assert executor._matches_tool('Edit', '') is True
            assert executor._matches_tool('Write', '') is True

    def test_exact_match(self):
        """完全一致でマッチ"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            assert executor._matches_tool('Edit', 'Edit') is True
            assert executor._matches_tool('Edit', 'Write') is False

    def test_pipe_separator_or_match(self):
        """パイプ区切りでOR条件マッチ"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            assert executor._matches_tool('Edit', 'Edit|Write') is True
            assert executor._matches_tool('Write', 'Edit|Write') is True
            assert executor._matches_tool('Read', 'Edit|Write') is False

    def test_wildcard_match(self):
        """ワイルドカードでマッチ"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            assert executor._matches_tool('mcp__serena__create', 'mcp__serena__*') is True
            assert executor._matches_tool('mcp__other__create', 'mcp__serena__*') is False


class TestMatchesSinglePattern:
    """_matches_single_pattern メソッドのテスト"""

    def test_exact_match(self):
        """完全一致"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            assert executor._matches_single_pattern('Edit', 'Edit') is True
            assert executor._matches_single_pattern('Edit', 'Write') is False

    def test_wildcard_asterisk(self):
        """アスタリスクワイルドカード"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            assert executor._matches_single_pattern('mcp__test__func', 'mcp__*') is True
            assert executor._matches_single_pattern('mcp__test__func', '*__func') is True
            assert executor._matches_single_pattern('mcp__test__func', 'mcp__test__*') is True

    def test_no_wildcard_exact_match_only(self):
        """ワイルドカードなしの場合は完全一致のみ"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            # ?はワイルドカードとして扱われない（*のみ対応）
            assert executor._matches_single_pattern('Edit', 'Edi?') is False
            assert executor._matches_single_pattern('Edit', 'Edit') is True


class TestExecuteSingleHook:
    """_execute_single_hook メソッドのテスト"""

    def test_non_command_type_returns_none(self):
        """type='command'以外はNoneを返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            result = executor._execute_single_hook(
                {'type': 'script'}, 'PreToolUse', 'Edit', {}
            )
            assert result is None

    def test_missing_command_returns_none(self):
        """commandがない場合はNoneを返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            result = executor._execute_single_hook(
                {'type': 'command'}, 'PreToolUse', 'Edit', {}
            )
            assert result is None

    def test_successful_command_execution(self):
        """コマンド実行成功時に結果を返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_result = MagicMock()
            mock_result.stdout = json.dumps({'decision': 'allow', 'reason': 'test'})

            with patch('subprocess.run', return_value=mock_result):
                result = executor._execute_single_hook(
                    {'type': 'command', 'command': 'echo test'},
                    'PreToolUse', 'Edit', {'file_path': '/test.py'}
                )

            assert result['decision'] == 'allow'
            assert result['reason'] == 'test'

    def test_command_with_session_id(self):
        """セッションIDが入力データに含まれる"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_result = MagicMock()
            mock_result.stdout = json.dumps({'decision': 'allow'})

            with patch('subprocess.run', return_value=mock_result) as mock_run:
                executor._execute_single_hook(
                    {'type': 'command', 'command': 'echo test'},
                    'PreToolUse', 'Edit', {}, session_id='test-session'
                )

            # 入力データにsession_idが含まれることを確認
            call_args = mock_run.call_args
            input_data = json.loads(call_args.kwargs['input'])
            assert input_data['session_id'] == 'test-session'

    def test_invalid_json_response(self):
        """無効なJSON応答時はエラーを含む結果を返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_result = MagicMock()
            mock_result.stdout = 'not json'

            with patch('subprocess.run', return_value=mock_result):
                result = executor._execute_single_hook(
                    {'type': 'command', 'command': 'echo test'},
                    'PreToolUse', 'Edit', {}
                )

            assert result['decision'] == 'allow'
            assert 'error' in result
            assert 'Invalid JSON' in result['error']

    def test_empty_stdout_returns_allow(self):
        """空の標準出力時はallowを返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_result = MagicMock()
            mock_result.stdout = ''

            with patch('subprocess.run', return_value=mock_result):
                result = executor._execute_single_hook(
                    {'type': 'command', 'command': 'echo test'},
                    'PreToolUse', 'Edit', {}
                )

            assert result['decision'] == 'allow'

    def test_timeout_handling(self):
        """タイムアウト時はエラーを含む結果を返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            with patch('subprocess.run', side_effect=subprocess.TimeoutExpired('cmd', 60)):
                result = executor._execute_single_hook(
                    {'type': 'command', 'command': 'sleep 100', 'timeout': 60},
                    'PreToolUse', 'Edit', {}
                )

            assert result['decision'] == 'allow'
            assert 'error' in result
            assert 'timed out' in result['error']

    def test_exception_handling(self):
        """例外発生時はエラーを含む結果を返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            with patch('subprocess.run', side_effect=Exception('test error')):
                result = executor._execute_single_hook(
                    {'type': 'command', 'command': 'bad command'},
                    'PreToolUse', 'Edit', {}
                )

            assert result['decision'] == 'allow'
            assert 'error' in result
            assert 'test error' in result['error']


class TestExecuteBuiltinHook:
    """_execute_builtin_hook メソッドのテスト"""

    def test_unknown_hook_returns_none(self):
        """未知のフック名はNoneを返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()
            result = executor._execute_builtin_hook('unknown_hook', {})
            assert result is None

    def test_implementation_design_hook_execution(self):
        """implementation_designフックが実行される"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_hook = MagicMock()
            mock_hook.is_session_processed.return_value = False
            mock_hook.should_process.return_value = True
            mock_hook.process.return_value = {'decision': 'allow', 'reason': 'ok'}

            executor.builtin_hooks['implementation_design'] = MagicMock(return_value=mock_hook)

            result = executor._execute_builtin_hook(
                'implementation_design', {'file_path': '/test.py'}
            )

            assert result['decision'] == 'allow'
            mock_hook.process.assert_called_once()

    def test_skip_processed_session(self):
        """処理済みセッションはスキップ"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_hook = MagicMock()
            mock_hook.is_session_processed.return_value = True

            executor.builtin_hooks['implementation_design'] = MagicMock(return_value=mock_hook)

            result = executor._execute_builtin_hook(
                'implementation_design', {}, session_id='processed-session'
            )

            assert result is None

    def test_skip_non_matching_input(self):
        """should_processがFalseの場合はスキップ"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_hook = MagicMock()
            mock_hook.is_session_processed.return_value = False
            mock_hook.should_process.return_value = False

            executor.builtin_hooks['implementation_design'] = MagicMock(return_value=mock_hook)

            result = executor._execute_builtin_hook(
                'implementation_design', {}
            )

            assert result is None

    def test_mark_session_processed_on_block(self):
        """blockの場合はセッションを処理済みにマーク"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            mock_hook = MagicMock()
            mock_hook.is_session_processed.return_value = False
            mock_hook.should_process.return_value = True
            mock_hook.process.return_value = {'decision': 'block', 'reason': 'test'}

            executor.builtin_hooks['implementation_design'] = MagicMock(return_value=mock_hook)

            executor._execute_builtin_hook(
                'implementation_design', {}, session_id='test-session'
            )

            mock_hook.mark_session_processed.assert_called_once_with('test-session')

    def test_exception_handling(self):
        """例外発生時はエラーを含む結果を返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager'):
            executor = HookExecutor()

            executor.builtin_hooks['implementation_design'] = MagicMock(
                side_effect=Exception('hook error')
            )

            result = executor._execute_builtin_hook('implementation_design', {})

            assert result['decision'] == 'allow'
            assert 'error' in result
            assert 'hook error' in result['error']


class TestExecuteHook:
    """execute_hook メソッドのテスト"""

    def test_no_hooks_returns_empty_list(self):
        """フックがない場合は空リストを返す"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_hooks.return_value = {}
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()
            results = executor.execute_hook('PreToolUse', 'Read', {})

            assert results == []

    def test_matching_hooks_are_executed(self):
        """マッチするフックが実行される"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_hooks.return_value = {
                'hooks': {
                    'PreToolUse': [
                        {
                            'matcher': 'Edit',
                            'hooks': [
                                {'type': 'command', 'command': 'echo test'}
                            ]
                        }
                    ]
                }
            }
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()

            mock_result = MagicMock()
            mock_result.stdout = json.dumps({'decision': 'allow'})

            with patch('subprocess.run', return_value=mock_result):
                results = executor.execute_hook('PreToolUse', 'Edit', {})

            assert len(results) == 1
            assert results[0]['decision'] == 'allow'

    def test_builtin_hook_for_edit_tool(self):
        """Editツールに対して内蔵フックが実行される"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_hooks.return_value = {}
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()

            mock_hook = MagicMock()
            mock_hook.is_session_processed.return_value = False
            mock_hook.should_process.return_value = True
            mock_hook.process.return_value = {'decision': 'allow'}

            executor.builtin_hooks['implementation_design'] = MagicMock(return_value=mock_hook)

            results = executor.execute_hook('PreToolUse', 'Edit', {'file_path': '/test.py'})

            assert len(results) == 1

    def test_builtin_hook_for_write_tool(self):
        """Writeツールに対して内蔵フックが実行される"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_hooks.return_value = {}
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()

            mock_hook = MagicMock()
            mock_hook.is_session_processed.return_value = False
            mock_hook.should_process.return_value = True
            mock_hook.process.return_value = {'decision': 'allow'}

            executor.builtin_hooks['implementation_design'] = MagicMock(return_value=mock_hook)

            results = executor.execute_hook('PreToolUse', 'Write', {'file_path': '/test.py'})

            assert len(results) == 1

    def test_builtin_hook_for_serena_tools(self):
        """mcp__serena__*ツールに対して内蔵フックが実行される"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_hooks.return_value = {}
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()

            mock_hook = MagicMock()
            mock_hook.is_session_processed.return_value = False
            mock_hook.should_process.return_value = True
            mock_hook.process.return_value = {'decision': 'allow'}

            executor.builtin_hooks['implementation_design'] = MagicMock(return_value=mock_hook)

            results = executor.execute_hook('PreToolUse', 'mcp__serena__create', {})

            assert len(results) == 1

    def test_no_builtin_hook_for_read_tool(self):
        """Readツールに対しては内蔵フックが実行されない"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.list_hooks.return_value = {}
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()
            results = executor.execute_hook('PreToolUse', 'Read', {})

            assert len(results) == 0


class TestRegisterHookViaCLI:
    """register_hook_via_cli メソッドのテスト"""

    def test_register_normal_command(self):
        """通常のコマンドを登録"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.add_hook.return_value = {'success': True}
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()
            result = executor.register_hook_via_cli(
                'PreToolUse', 'Edit', 'echo test', timeout=30, local=False
            )

            mock_manager.add_hook.assert_called_once_with(
                'PreToolUse', 'Edit', 'echo test', 30, False
            )
            assert result['success'] is True

    def test_register_python_script(self):
        """Pythonスクリプトを登録時はフルパスに変換"""
        with patch('src.infrastructure.hooks.hook_executor.HookManager') as mock_manager_class:
            mock_manager = MagicMock()
            mock_manager.add_hook.return_value = {'success': True}
            mock_manager_class.return_value = mock_manager

            executor = HookExecutor()
            result = executor.register_hook_via_cli(
                'PreToolUse', 'Edit', 'my_hook.py', local=True
            )

            # コマンドがpython3プレフィックス付きで呼ばれることを確認
            call_args = mock_manager.add_hook.call_args[0]
            assert 'python3' in call_args[2]
            assert 'my_hook.py' in call_args[2]
