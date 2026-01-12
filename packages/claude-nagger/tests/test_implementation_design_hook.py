"""ImplementationDesignHookのテスト"""

import os
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import sys
sys.path.append(str(Path(__file__).parent.parent))

from src.domain.hooks.implementation_design_hook import ImplementationDesignHook


class TestImplementationDesignHook:
    """ImplementationDesignHookのテストクラス"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)
        
        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        
        # クリーンアップ
        log_file.unlink(missing_ok=True)

    def test_should_process_with_matching_file(self, hook):
        """マッチするファイルパスの処理判定テスト"""
        input_data = {
            'tool_input': {
                'file_path': 'test/実装設計書.pu'
            }
        }
        
        # FileConventionMatcherをモック
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get_message:
            mock_get_message.return_value = {
                'rule_name': 'Test Rule',
                'severity': 'block',
                'message': 'Test message'
            }
            
            assert hook.should_process(input_data) is True

    def test_should_process_without_matching_file(self, hook):
        """マッチしないファイルパスの処理判定テスト"""
        input_data = {
            'tool_input': {
                'file_path': 'test/other.txt'
            }
        }
        
        # FileConventionMatcherをモック
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get_message:
            mock_get_message.return_value = None
            
            assert hook.should_process(input_data) is False

    def test_should_process_without_file_path(self, hook):
        """ファイルパスがない場合の処理判定テスト"""
        input_data = {
            'tool_input': {}
        }
        
        assert hook.should_process(input_data) is False

    def test_process_with_block_severity(self, hook):
        """blockセベリティの処理テスト"""
        input_data = {
            'tool_input': {
                'file_path': 'test/実装設計書.pu'
            }
        }
        
        # FileConventionMatcherをモック
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get_message:
            mock_get_message.return_value = {
                'rule_name': 'Test Rule',
                'severity': 'block',
                'message': 'This file is blocked',
                'convention_doc': '@test/doc.md'
            }
            
            result = hook.process(input_data)
            
            assert result['decision'] == 'block'
            assert 'This file is blocked' in result['reason']

    def test_process_with_warn_severity(self, hook):
        """warnセベリティの処理テスト（現在の実装ではblockとして扱われる）"""
        input_data = {
            'tool_input': {
                'file_path': 'app/presenters/test.rb'
            }
        }

        # FileConventionMatcherをモック
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get_message:
            mock_get_message.return_value = {
                'rule_name': 'Test Warning',
                'severity': 'warn',
                'message': 'This is a warning',
                'convention_doc': '@test/warn.md'
            }

            result = hook.process(input_data)

            # 現在の実装ではすべてのseverityでblockを返す
            assert result['decision'] == 'block'
            assert 'This is a warning' in result['reason']

    def test_process_with_no_matching_rule(self, hook):
        """ルールにマッチしない場合の処理テスト"""
        input_data = {
            'tool_input': {
                'file_path': 'test/other.txt'
            }
        }

        # FileConventionMatcherをモック
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get_message:
            mock_get_message.return_value = None

            result = hook.process(input_data)

            assert result['decision'] == 'approve'
            assert result['reason'] == 'No rules matched'

    def test_session_marker_creation(self, hook):
        """セッションマーカーの作成テスト"""
        session_id = 'test_session_123'
        
        # マーカーが存在しないことを確認
        assert not hook.is_session_processed(session_id)
        
        # マーカーを作成
        assert hook.mark_session_processed(session_id)
        
        # マーカーが存在することを確認
        assert hook.is_session_processed(session_id)
        
        # クリーンアップ
        marker_path = hook.get_session_marker_path(session_id)
        marker_path.unlink()

    @patch('sys.stdin')
    @patch('builtins.print')
    def test_run_full_flow(self, mock_print, mock_stdin, hook):
        """run メソッドの完全なフローテスト"""
        # 入力データ（ユニークなセッションIDを使用）
        import uuid
        unique_session_id = f'test_session_{uuid.uuid4().hex[:8]}'
        input_data = {
            'session_id': unique_session_id,
            'tool_input': {
                'file_path': 'test/実装設計書.pu'
            }
        }

        mock_stdin.read.return_value = json.dumps(input_data)

        # FileConventionMatcherをモック（should_processとprocessの両方に影響）
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get_message:
            mock_get_message.return_value = {
                'rule_name': 'Test Rule',
                'severity': 'block',
                'message': 'Blocked for testing',
                'convention_doc': '@test/doc.md'
            }

            # should_processとセッション関連メソッドをモック
            with patch.object(hook, 'should_process', return_value=True), \
                 patch.object(hook, 'is_session_processed_context_aware', return_value=False), \
                 patch.object(hook, 'is_rule_processed', return_value=False), \
                 patch.object(hook, 'mark_rule_processed', return_value=True), \
                 patch.object(hook, 'mark_session_processed', return_value=True):
                # フックを実行
                exit_code = hook.run()

                # 正常終了
                assert exit_code == 0

                # 出力を確認（printが呼ばれたか）
                assert mock_print.called, "print should have been called"
                output = mock_print.call_args[0][0]
                output_data = json.loads(output)

                # 新形式: hookSpecificOutput を確認
                assert 'hookSpecificOutput' in output_data
                hook_output = output_data['hookSpecificOutput']
                assert hook_output['permissionDecision'] == 'deny'
                assert 'Blocked for testing' in hook_output['permissionDecisionReason']

    @patch('sys.stdin')
    def test_run_with_invalid_json(self, mock_stdin, hook):
        """無効なJSON入力での実行テスト"""
        mock_stdin.read.return_value = 'invalid json'

        # エラーが発生してもクラッシュしないことを確認
        exit_code = hook.run()
        assert exit_code == 0  # 無効な入力は無視される


class TestNormalizeFilePath:
    """normalize_file_pathメソッドのテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_absolute_path_unchanged(self, hook):
        """絶対パスはそのまま返される"""
        result = hook.normalize_file_path('/home/user/test.txt', '/cwd')
        assert result == '/home/user/test.txt'

    def test_relative_path_converted(self, hook):
        """相対パスはcwdと結合される"""
        result = hook.normalize_file_path('src/file.py', '/project')
        assert result == '/project/src/file.py'

    def test_path_normalized(self, hook):
        """パスが正規化される"""
        result = hook.normalize_file_path('../test/../file.txt', '/project/src')
        assert result == '/project/file.txt'

    def test_project_dir_takes_priority(self, hook):
        """CLAUDE_PROJECT_DIRが設定されていれば優先"""
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': '/workspace/myproject'}):
            result = hook.normalize_file_path('src/file.py', '/other/dir')
            assert result == '/workspace/myproject/src/file.py'

    def test_cwd_fallback_when_project_dir_not_set(self, hook):
        """CLAUDE_PROJECT_DIR未設定時はcwdにフォールバック"""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('CLAUDE_PROJECT_DIR', None)
            result = hook.normalize_file_path('src/file.py', '/fallback/cwd')
            assert result == '/fallback/cwd/src/file.py'


class TestCommandToolDetection:
    """コマンドツール検出のテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_bash_tool_detected(self, hook):
        """Bashツールが検出される"""
        input_data = {
            'tool_name': 'Bash',
            'tool_input': {
                'command': 'git push origin main'
            }
        }
        assert hook.should_process(input_data) is True

    def test_serena_shell_tool_detected(self, hook):
        """serena execute_shell_commandが検出される"""
        input_data = {
            'tool_name': 'mcp__serena__execute_shell_command',
            'tool_input': {
                'command': 'npm run deploy'
            }
        }
        assert hook.should_process(input_data) is True

    def test_command_tool_without_command(self, hook):
        """コマンドが空の場合はFalse"""
        input_data = {
            'tool_name': 'Bash',
            'tool_input': {
                'command': ''
            }
        }
        assert hook.should_process(input_data) is False


class TestProcessCommand:
    """_process_commandメソッドのテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_process_command_with_matching_rule(self, hook):
        """コマンドが規約にマッチする場合"""
        input_data = {
            'tool_name': 'Bash',
            'tool_input': {
                'command': 'git push origin main'
            },
            'session_id': 'test_session'
        }

        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_cmd:
            mock_cmd.return_value = {
                'rule_name': 'Git Push規約',
                'severity': 'block',
                'message': 'プッシュ前にテストを実行'
            }

            result = hook.process(input_data)

            assert result['decision'] == 'block'
            assert 'プッシュ前にテストを実行' in result['reason']

    def test_process_command_without_matching_rule(self, hook):
        """コマンドが規約にマッチしない場合"""
        input_data = {
            'tool_name': 'Bash',
            'tool_input': {
                'command': 'ls -la'
            },
            'session_id': 'test_session'
        }

        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_cmd:
            mock_cmd.return_value = None

            result = hook.process(input_data)

            assert result['decision'] == 'approve'
            assert result['reason'] == 'No command rules matched'

    def test_process_command_without_command(self, hook):
        """コマンドがない場合"""
        input_data = {
            'tool_name': 'Bash',
            'tool_input': {},
            'session_id': 'test_session'
        }

        result = hook.process(input_data)

        assert result['decision'] == 'approve'
        assert result['reason'] == 'No command found'


class TestGetRuleThreshold:
    """_get_rule_thresholdメソッドのテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_rule_specific_threshold(self, hook):
        """規約固有の閾値が使用される"""
        rule_info = {
            'rule_name': 'Test Rule',
            'severity': 'warn',
            'token_threshold': 15000
        }

        result = hook._get_rule_threshold(rule_info)
        assert result == 15000

    def test_default_threshold_by_severity(self, hook):
        """severity別のデフォルト閾値が使用される"""
        rule_info = {
            'rule_name': 'Test Rule',
            'severity': 'warn'
        }

        result = hook._get_rule_threshold(rule_info)
        # デフォルト値が返される（設定による）
        assert isinstance(result, int)
        assert result > 0


class TestGetCommandThreshold:
    """_get_command_thresholdメソッドのテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_command_specific_threshold(self, hook):
        """コマンド固有の閾値が使用される"""
        rule_info = {
            'rule_name': 'Git Push',
            'token_threshold': 25000
        }

        result = hook._get_command_threshold(rule_info)
        assert result == 25000

    def test_default_command_threshold(self, hook):
        """デフォルトのコマンド閾値が使用される"""
        rule_info = {
            'rule_name': 'Git Push'
        }

        result = hook._get_command_threshold(rule_info)
        # デフォルト値が返される（設定による）
        assert isinstance(result, int)
        assert result > 0


class TestNormalizeRuleName:
    """_normalize_rule_nameメソッドのテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_normalize_japanese_rule_name(self, hook):
        """日本語規約名が正規化される"""
        result = hook._normalize_rule_name('実装設計書規約')
        # 正規化された文字列が返される
        assert isinstance(result, str)
        assert len(result) > 0

    def test_normalize_long_rule_name(self, hook):
        """長い規約名がハッシュ化される"""
        long_name = 'This is a very long rule name that exceeds twenty characters'
        result = hook._normalize_rule_name(long_name)
        # 長い名前は短縮される
        assert len(result) <= 21  # 12文字 + _ + 8文字のハッシュ

    def test_normalize_special_characters(self, hook):
        """特殊文字が除去される"""
        result = hook._normalize_rule_name('Rule!@#$%^&*()')
        # 特殊文字が除去された文字列
        assert '!' not in result
        assert '@' not in result


class TestFileToolDetection:
    """ファイルツール検出のテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_serena_create_text_file_detected(self, hook):
        """serena create_text_fileツールが検出される"""
        input_data = {
            'tool_name': 'mcp__serena__create_text_file',
            'tool_input': {
                'relative_path': 'src/test.py'
            }
        }

        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get:
            mock_get.return_value = {
                'rule_name': 'Test',
                'severity': 'warn',
                'message': 'Test'
            }
            assert hook.should_process(input_data) is True

    def test_edit_tool_with_relative_path(self, hook):
        """relative_pathを持つEditツール"""
        input_data = {
            'tool_name': 'Edit',
            'tool_input': {
                'relative_path': 'src/module.py'
            }
        }

        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get:
            mock_get.return_value = {
                'rule_name': 'Test',
                'severity': 'warn',
                'message': 'Test'
            }
            assert hook.should_process(input_data) is True


class TestRuleMarkerWithTokenThreshold:
    """規約マーカーとトークン閾値のテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_rule_processed_within_threshold_skips(self, hook):
        """閾値内の場合はスキップ"""
        import uuid
        session_id = f'test_session_{uuid.uuid4().hex[:8]}'
        rule_name = 'Test Rule'

        input_data = {
            'tool_name': 'Edit',
            'tool_input': {
                'file_path': '/test/file.py'
            },
            'session_id': session_id,
            'transcript_path': None
        }

        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get:
            mock_get.return_value = {
                'rule_name': rule_name,
                'severity': 'warn',
                'message': 'Test message',
                'token_threshold': 50000
            }

            # 初回は処理される
            with patch.object(hook, 'is_rule_processed', return_value=False):
                result = hook.should_process(input_data)
                assert result is True


class TestCommandMarkerWithTokenThreshold:
    """コマンドマーカーとトークン閾値のテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_command_within_threshold_approves(self, hook):
        """コマンドが閾値内の場合は承認"""
        import uuid
        session_id = f'test_session_{uuid.uuid4().hex[:8]}'

        input_data = {
            'tool_name': 'Bash',
            'tool_input': {
                'command': 'git push'
            },
            'session_id': session_id
        }

        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_cmd:
            mock_cmd.return_value = {
                'rule_name': 'Git Push',
                'severity': 'warn',
                'message': 'Test',
                'token_threshold': 50000
            }

            # マーカーが存在し、閾値内
            with patch.object(hook, 'is_command_processed', return_value=True), \
                 patch.object(hook, 'get_command_marker_path') as mock_path, \
                 patch.object(hook, '_get_current_context_size', return_value=1000):

                # マーカーファイルのモック
                mock_marker = MagicMock()
                mock_marker.exists.return_value = True
                mock_path.return_value = mock_marker

                # ファイル読み込みをモック
                with patch('builtins.open', create=True) as mock_open:
                    mock_open.return_value.__enter__.return_value.read.return_value = '{"tokens": 500}'

                    result = hook.process(input_data)

                    # 閾値内なので承認
                    assert result['decision'] == 'approve'


class TestMain:
    """main関数のテスト"""

    def test_main_creates_hook_and_runs(self):
        """main関数がフックを作成して実行する"""
        with patch('sys.stdin') as mock_stdin, \
             patch('builtins.print'), \
             patch('sys.exit') as mock_exit:

            mock_stdin.read.return_value = '{}'

            # main関数をインポートして実行
            from src.domain.hooks.implementation_design_hook import main
            main()

            # sys.exitが呼ばれることを確認
            mock_exit.assert_called_once()


class TestProcessWithRuleAlreadyProcessed:
    """すでに処理済みの規約のテスト"""

    @pytest.fixture
    def hook(self):
        """テスト用フックインスタンス"""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            log_file = Path(f.name)

        hook = ImplementationDesignHook(log_file=log_file, debug=False)
        yield hook
        log_file.unlink(missing_ok=True)

    def test_skip_already_processed_rule(self, hook):
        """すでに処理済みの規約はスキップ"""
        import uuid
        session_id = f'test_session_{uuid.uuid4().hex[:8]}'

        input_data = {
            'tool_name': 'Edit',
            'tool_input': {
                'file_path': '/test/file.py'
            },
            'session_id': session_id
        }

        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get:
            mock_get.return_value = {
                'rule_name': 'Test Rule',
                'severity': 'warn',
                'message': 'Test message'
            }

            with patch.object(hook, 'is_rule_processed', return_value=True):
                result = hook.process(input_data)

                assert result['decision'] == 'approve'
                assert 'within token threshold' in result['reason']