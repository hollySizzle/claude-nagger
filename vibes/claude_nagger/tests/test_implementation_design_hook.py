"""ImplementationDesignHookのテスト"""

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
        """warnセベリティの処理テスト"""
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
            
            assert result['decision'] == 'warn'
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
            
            assert result['decision'] == 'allow'
            assert result['reason'] == ''

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
        # 入力データ
        input_data = {
            'session_id': 'test_session',
            'tool_input': {
                'file_path': 'test/実装設計書.pu'
            }
        }
        
        mock_stdin.read.return_value = json.dumps(input_data)
        
        # FileConventionMatcherをモック
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_get_message:
            mock_get_message.return_value = {
                'rule_name': 'Test Rule',
                'severity': 'block',
                'message': 'Blocked for testing',
                'convention_doc': '@test/doc.md'
            }
            
            # フックを実行
            exit_code = hook.run()
            
            # 正常終了
            assert exit_code == 0
            
            # 出力を確認
            mock_print.assert_called_once()
            output = mock_print.call_args[0][0]
            output_data = json.loads(output)
            
            assert output_data['decision'] == 'block'
            assert 'Blocked for testing' in output_data['reason']

    @patch('sys.stdin')
    def test_run_with_invalid_json(self, mock_stdin, hook):
        """無効なJSON入力での実行テスト"""
        mock_stdin.read.return_value = 'invalid json'
        
        # エラーが発生してもクラッシュしないことを確認
        exit_code = hook.run()
        assert exit_code == 0  # 無効な入力は無視される