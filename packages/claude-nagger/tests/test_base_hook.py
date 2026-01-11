"""base_hook.py のテスト"""

import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from io import StringIO

from src.domain.hooks.base_hook import BaseHook


class ConcreteHook(BaseHook):
    """テスト用の具象フッククラス"""

    def should_process(self, input_data):
        return input_data.get('should_process', True)

    def process(self, input_data):
        return {'decision': 'approve', 'reason': 'test'}


class TestBaseHookInit:
    """BaseHook初期化のテスト"""

    def test_init_default_log_file(self):
        """デフォルトのログファイルパス"""
        hook = ConcreteHook()
        assert hook.log_file == Path("/tmp/claude_hooks_debug.log")

    def test_init_custom_log_file(self, tmp_path):
        """カスタムログファイルパス"""
        log_file = tmp_path / "custom.log"
        hook = ConcreteHook(log_file=log_file)
        assert hook.log_file == log_file

    def test_init_debug_flag(self):
        """デバッグフラグ"""
        hook = ConcreteHook(debug=True)
        assert hook.debug is True


class TestLogging:
    """ログメソッドのテスト"""

    def test_log_debug(self):
        """log_debugの呼び出し"""
        hook = ConcreteHook()
        with patch.object(hook.logger, 'debug') as mock_debug:
            hook.log_debug("test message")
            mock_debug.assert_called_once_with("test message")

    def test_log_info(self):
        """log_infoの呼び出し"""
        hook = ConcreteHook()
        with patch.object(hook.logger, 'info') as mock_info:
            hook.log_info("test message")
            mock_info.assert_called_once_with("test message")

    def test_log_error(self):
        """log_errorの呼び出し"""
        hook = ConcreteHook()
        with patch.object(hook.logger, 'error') as mock_error:
            hook.log_error("test message")
            mock_error.assert_called_once_with("test message")


class TestSaveRawJson:
    """_save_raw_json メソッドのテスト"""

    def test_save_raw_json_success(self, tmp_path):
        """JSONを保存"""
        hook = ConcreteHook()
        with patch('os.makedirs'):
            with patch('builtins.open', mock_open()):
                hook._save_raw_json('{"test": "data"}')

    def test_save_raw_json_exception(self):
        """保存失敗時のエラーログ"""
        hook = ConcreteHook()
        with patch('os.makedirs', side_effect=Exception('error')):
            with patch.object(hook, 'log_error') as mock_log:
                hook._save_raw_json('{"test": "data"}')
                mock_log.assert_called()


class TestReadInput:
    """read_input メソッドのテスト"""

    def test_read_valid_json(self):
        """有効なJSONを読み取り"""
        hook = ConcreteHook()
        test_input = '{"tool_name": "Edit"}'

        with patch('sys.stdin.read', return_value=test_input):
            with patch.object(hook, '_save_raw_json'):
                result = hook.read_input()

        assert result == {"tool_name": "Edit"}

    def test_read_empty_input(self):
        """空の入力"""
        hook = ConcreteHook()

        with patch('sys.stdin.read', return_value=''):
            result = hook.read_input()

        assert result == {}

    def test_read_invalid_json(self):
        """無効なJSON"""
        hook = ConcreteHook()

        with patch('sys.stdin.read', return_value='not json'):
            with patch.object(hook, '_save_raw_json'):
                result = hook.read_input()

        assert result == {}

    def test_read_input_exception(self):
        """読み取り例外"""
        hook = ConcreteHook()

        with patch('sys.stdin.read', side_effect=Exception('error')):
            result = hook.read_input()

        assert result == {}


class TestOutputResponse:
    """output_response メソッドのテスト（Claude Code公式スキーマ対応）"""

    def test_output_approve(self, capsys):
        """approveレスポンス出力（hookSpecificOutput形式）"""
        hook = ConcreteHook()
        result = hook.output_response('approve', 'test reason')

        assert result is True
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        # 新形式: hookSpecificOutput を使用
        assert 'hookSpecificOutput' in output
        hook_output = output['hookSpecificOutput']
        assert hook_output['hookEventName'] == 'PreToolUse'
        assert hook_output['permissionDecision'] == 'allow'
        assert hook_output['permissionDecisionReason'] == 'test reason'

    def test_output_block(self, capsys):
        """blockレスポンス出力（hookSpecificOutput形式）"""
        hook = ConcreteHook()
        result = hook.output_response('block', 'blocked reason')

        assert result is True
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        # 新形式: hookSpecificOutput を使用
        assert 'hookSpecificOutput' in output
        hook_output = output['hookSpecificOutput']
        assert hook_output['hookEventName'] == 'PreToolUse'
        assert hook_output['permissionDecision'] == 'deny'
        assert hook_output['permissionDecisionReason'] == 'blocked reason'

    def test_output_exception(self):
        """出力例外時はFalse"""
        hook = ConcreteHook()

        with patch('json.dumps', side_effect=Exception('error')):
            result = hook.output_response('approve', 'test')

        assert result is False


class TestSessionMarker:
    """セッションマーカー関連のテスト"""

    def test_get_session_marker_path(self):
        """セッションマーカーパスの取得"""
        hook = ConcreteHook()
        path = hook.get_session_marker_path('test-session')

        assert path == Path('/tmp/claude_hook_ConcreteHook_session_test-session')

    def test_is_session_processed_false(self):
        """セッション未処理"""
        hook = ConcreteHook()
        with patch.object(Path, 'exists', return_value=False):
            result = hook.is_session_processed('test-session')
        assert result is False

    def test_is_session_processed_true(self):
        """セッション処理済み"""
        hook = ConcreteHook()
        with patch.object(Path, 'exists', return_value=True):
            result = hook.is_session_processed('test-session')
        assert result is True

    def test_mark_session_processed(self, tmp_path):
        """セッションを処理済みにマーク"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'marker'

        with patch.object(hook, 'get_session_marker_path', return_value=marker_path):
            result = hook.mark_session_processed('test-session', 1000)

        assert result is True
        assert marker_path.exists()
        data = json.loads(marker_path.read_text())
        assert data['tokens'] == 1000

    def test_mark_session_processed_failure(self):
        """マーク失敗"""
        hook = ConcreteHook()

        with patch.object(hook, 'get_session_marker_path', side_effect=Exception('error')):
            result = hook.mark_session_processed('test-session')

        assert result is False


class TestCommandMarker:
    """コマンドマーカー関連のテスト"""

    def test_get_command_marker_path(self):
        """コマンドマーカーパスの取得"""
        hook = ConcreteHook()
        path = hook.get_command_marker_path('session', 'echo test')

        assert 'claude_cmd_session_' in str(path)
        assert path.parent == Path('/tmp')

    def test_is_command_processed(self):
        """コマンド処理済み確認"""
        hook = ConcreteHook()

        with patch.object(hook, 'get_command_marker_path') as mock_get:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_get.return_value = mock_path

            result = hook.is_command_processed('session', 'echo test')

        assert result is True

    def test_mark_command_processed(self, tmp_path):
        """コマンドを処理済みにマーク"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'cmd_marker'

        with patch.object(hook, 'get_command_marker_path', return_value=marker_path):
            result = hook.mark_command_processed('session', 'echo test', 500)

        assert result is True
        assert marker_path.exists()
        data = json.loads(marker_path.read_text())
        assert data['command'] == 'echo test'

    def test_mark_command_processed_failure(self):
        """マーク失敗"""
        hook = ConcreteHook()

        with patch.object(hook, 'get_command_marker_path', side_effect=Exception('error')):
            result = hook.mark_command_processed('session', 'cmd')

        assert result is False


class TestRuleMarker:
    """規約マーカー関連のテスト"""

    def test_get_rule_marker_path(self):
        """規約マーカーパスの取得"""
        hook = ConcreteHook()
        path = hook.get_rule_marker_path('session', 'Presenter層編集規約')

        assert 'claude_rule_ConcreteHook_session_' in str(path)

    def test_is_rule_processed(self):
        """規約処理済み確認"""
        hook = ConcreteHook()

        with patch.object(hook, 'get_rule_marker_path') as mock_get:
            mock_path = MagicMock()
            mock_path.exists.return_value = True
            mock_get.return_value = mock_path

            result = hook.is_rule_processed('session', 'rule_name')

        assert result is True

    def test_mark_rule_processed(self, tmp_path):
        """規約を処理済みにマーク"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'rule_marker'

        with patch.object(hook, 'get_rule_marker_path', return_value=marker_path):
            result = hook.mark_rule_processed('session', 'test_rule', 2000)

        assert result is True
        assert marker_path.exists()
        data = json.loads(marker_path.read_text())
        assert data['rule_name'] == 'test_rule'

    def test_mark_rule_processed_failure(self):
        """マーク失敗"""
        hook = ConcreteHook()

        with patch.object(hook, 'get_rule_marker_path', side_effect=Exception('error')):
            result = hook.mark_rule_processed('session', 'rule')

        assert result is False


class TestContextAwareProcessing:
    """コンテキストベース処理のテスト"""

    def test_is_session_processed_context_aware_no_marker(self):
        """マーカーなしの場合はFalse"""
        hook = ConcreteHook()

        with patch.object(hook, 'get_session_marker_path') as mock_get:
            mock_path = MagicMock()
            mock_path.exists.return_value = False
            mock_get.return_value = mock_path

            result = hook.is_session_processed_context_aware('session', {})

        assert result is False

    def test_is_session_processed_context_aware_within_threshold(self, tmp_path):
        """閾値内の場合はTrue"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'marker'
        marker_path.write_text(json.dumps({'tokens': 1000}))

        with patch.object(hook, 'get_session_marker_path', return_value=marker_path):
            with patch.object(hook, '_get_current_context_size', return_value=2000):
                result = hook.is_session_processed_context_aware('session', {})

        assert result is True

    def test_is_session_processed_context_aware_exceeds_threshold(self, tmp_path):
        """閾値超過の場合はFalse"""
        hook = ConcreteHook()
        hook.marker_settings = {'valid_until_token_increase': 1000}
        marker_path = tmp_path / 'marker'
        marker_path.write_text(json.dumps({'tokens': 1000}))

        with patch.object(hook, 'get_session_marker_path', return_value=marker_path):
            with patch.object(hook, '_get_current_context_size', return_value=100000):
                with patch.object(hook, '_rename_expired_marker'):
                    result = hook.is_session_processed_context_aware('session', {})

        assert result is False

    def test_is_session_processed_context_aware_no_transcript(self, tmp_path):
        """transcript解析失敗時は単純チェック"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'marker'
        marker_path.write_text(json.dumps({'tokens': 1000}))

        with patch.object(hook, 'get_session_marker_path', return_value=marker_path):
            with patch.object(hook, '_get_current_context_size', return_value=None):
                result = hook.is_session_processed_context_aware('session', {})

        assert result is True  # マーカーが存在するのでTrue


class TestReadMarkerData:
    """_read_marker_data メソッドのテスト"""

    def test_read_existing_marker(self, tmp_path):
        """既存マーカーを読み取り"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'marker'
        marker_data = {'tokens': 500, 'session_id': 'test'}
        marker_path.write_text(json.dumps(marker_data))

        result = hook._read_marker_data(marker_path)

        assert result == marker_data

    def test_read_nonexistent_marker(self, tmp_path):
        """存在しないマーカーはNone"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'nonexistent'

        result = hook._read_marker_data(marker_path)

        assert result is None

    def test_read_invalid_marker(self, tmp_path):
        """無効なマーカーはNone"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'invalid'
        marker_path.write_text('not json')

        result = hook._read_marker_data(marker_path)

        assert result is None


class TestGetCurrentContextSize:
    """_get_current_context_size メソッドのテスト"""

    def test_no_transcript_path(self):
        """transcriptパスなしの場合はNone"""
        hook = ConcreteHook()
        result = hook._get_current_context_size(None)
        assert result is None

    def test_nonexistent_transcript(self):
        """存在しないtranscriptはNone"""
        hook = ConcreteHook()
        result = hook._get_current_context_size('/nonexistent/path')
        assert result is None

    def test_valid_transcript(self, tmp_path):
        """有効なtranscriptからトークン数を取得"""
        hook = ConcreteHook()
        transcript_path = tmp_path / 'transcript.jsonl'

        entries = [
            {'type': 'user', 'message': 'hello'},
            {
                'type': 'assistant',
                'message': {
                    'usage': {
                        'input_tokens': 100,
                        'output_tokens': 50,
                        'cache_creation_input_tokens': 20,
                        'cache_read_input_tokens': 30
                    }
                }
            }
        ]
        transcript_path.write_text('\n'.join(json.dumps(e) for e in entries))

        result = hook._get_current_context_size(str(transcript_path))

        assert result == 200  # 100 + 50 + 20 + 30

    def test_transcript_with_invalid_lines(self, tmp_path):
        """無効な行があっても処理を継続"""
        hook = ConcreteHook()
        transcript_path = tmp_path / 'transcript.jsonl'

        content = 'invalid json\n{"type": "assistant", "message": {"usage": {"input_tokens": 100, "output_tokens": 50}}}'
        transcript_path.write_text(content)

        result = hook._get_current_context_size(str(transcript_path))

        assert result == 150


class TestRenameExpiredMarker:
    """_rename_expired_marker メソッドのテスト"""

    def test_rename_existing_marker(self, tmp_path):
        """既存マーカーをリネーム"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'marker'
        marker_path.touch()

        result = hook._rename_expired_marker(marker_path)

        assert result is True
        assert not marker_path.exists()
        expired_files = list(tmp_path.glob('marker.expired_*'))
        assert len(expired_files) == 1

    def test_rename_nonexistent_marker(self, tmp_path):
        """存在しないマーカーはFalse"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'nonexistent'

        result = hook._rename_expired_marker(marker_path)

        assert result is False

    def test_rename_failure(self, tmp_path):
        """リネーム失敗"""
        hook = ConcreteHook()
        marker_path = tmp_path / 'marker'
        marker_path.touch()

        with patch.object(Path, 'rename', side_effect=Exception('error')):
            result = hook._rename_expired_marker(marker_path)

        assert result is False


class TestRun:
    """run メソッドのテスト"""

    def test_run_no_input(self):
        """入力なしの場合は0を返す"""
        hook = ConcreteHook()

        with patch.object(hook, 'read_input', return_value={}):
            with patch('application.install_hooks.ensure_config_exists'):
                result = hook.run()

        assert result == 0

    def test_run_session_already_processed(self):
        """処理済みセッションはスキップ"""
        hook = ConcreteHook()

        with patch.object(hook, 'read_input', return_value={'session_id': 'test'}):
            with patch.object(hook, 'is_session_processed_context_aware', return_value=True):
                with patch('application.install_hooks.ensure_config_exists'):
                    result = hook.run()

        assert result == 0

    def test_run_not_target(self):
        """処理対象外はスキップ"""
        hook = ConcreteHook()

        with patch.object(hook, 'read_input', return_value={'should_process': False}):
            with patch('application.install_hooks.ensure_config_exists'):
                result = hook.run()

        assert result == 0

    def test_run_success(self, capsys):
        """正常実行"""
        hook = ConcreteHook()

        with patch.object(hook, 'read_input', return_value={'should_process': True}):
            with patch('application.install_hooks.ensure_config_exists'):
                result = hook.run()

        assert result == 0

    def test_run_exception(self):
        """例外時は1を返す"""
        hook = ConcreteHook()

        with patch.object(hook, 'read_input', side_effect=Exception('error')):
            with patch('application.install_hooks.ensure_config_exists'):
                result = hook.run()

        assert result == 1


class TestAbstractMethods:
    """抽象メソッドのテスト"""

    def test_cannot_instantiate_base_hook(self):
        """BaseHookは直接インスタンス化できない"""
        with pytest.raises(TypeError):
            BaseHook()
