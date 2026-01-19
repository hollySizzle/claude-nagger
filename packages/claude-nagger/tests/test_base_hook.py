"""base_hook.py のテスト"""

import os
import pytest
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
from io import StringIO

from src.domain.hooks.base_hook import BaseHook, ExitCode, MarkerPatterns


class ConcreteHook(BaseHook):
    """テスト用の具象フッククラス"""

    def should_process(self, input_data):
        return input_data.get('should_process', True)

    def process(self, input_data):
        return {'decision': 'approve', 'reason': 'test'}


class TestBaseHookInit:
    """BaseHook初期化のテスト"""

    def test_init_default_log_dir(self):
        """デフォルトのログディレクトリ"""
        hook = ConcreteHook()
        assert hook.log_dir == Path(f"/tmp/claude-nagger-{os.getuid()}")

    def test_init_custom_log_dir(self, tmp_path):
        """カスタムログディレクトリ"""
        log_dir = tmp_path / "custom_logs"
        hook = ConcreteHook(log_dir=log_dir)
        assert hook.log_dir == log_dir

    def test_init_debug_flag_explicit(self):
        """明示的なデバッグフラグ"""
        hook = ConcreteHook(debug=True)
        assert hook.debug is True

    def test_init_debug_flag_from_env(self):
        """環境変数からのデバッグフラグ検出"""
        with patch.dict(os.environ, {'CLAUDE_CODE_DEBUG': 'true'}):
            hook = ConcreteHook()
            assert hook.debug is True


class TestLogging:
    """ログメソッドのテスト"""

    def test_log_debug(self):
        """log_debugの呼び出し"""
        hook = ConcreteHook()
        with patch.object(hook._structured_logger, 'debug') as mock_debug:
            hook.log_debug("test message", extra_key="value")
            mock_debug.assert_called_once_with("test message", extra_key="value")

    def test_log_info(self):
        """log_infoの呼び出し"""
        hook = ConcreteHook()
        with patch.object(hook._structured_logger, 'info') as mock_info:
            hook.log_info("test message")
            mock_info.assert_called_once_with("test message")

    def test_log_error(self):
        """log_errorの呼び出し"""
        hook = ConcreteHook()
        with patch.object(hook._structured_logger, 'error') as mock_error:
            hook.log_error("test message")
            mock_error.assert_called_once_with("test message")

    def test_log_warning(self):
        """log_warningの呼び出し"""
        hook = ConcreteHook()
        with patch.object(hook._structured_logger, 'warning') as mock_warning:
            hook.log_warning("test message")
            mock_warning.assert_called_once_with("test message")


class TestSaveRawJson:
    """_save_raw_json メソッドのテスト"""

    def test_save_raw_json_success(self, tmp_path):
        """JSONを保存（構造化ロガー経由）"""
        hook = ConcreteHook(log_dir=tmp_path)
        result = hook._save_raw_json('{"test": "data"}')
        assert result is not None
        assert result.exists()

    def test_save_raw_json_returns_path(self, tmp_path):
        """保存成功時はパスを返す"""
        hook = ConcreteHook(log_dir=tmp_path)
        result = hook._save_raw_json('{"test": "data"}')
        assert isinstance(result, Path)

    def test_save_raw_json_failure(self, tmp_path):
        """保存失敗時はNoneを返す"""
        hook = ConcreteHook(log_dir=tmp_path)
        with patch.object(hook._structured_logger, 'save_input_json', return_value=None):
            result = hook._save_raw_json('{"test": "data"}')
            assert result is None


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


class TestExitCode:
    """ExitCode enum のテスト"""

    def test_exit_code_values(self):
        """終了コードの値が正しい"""
        assert ExitCode.SUCCESS == 0
        assert ExitCode.ERROR == 1
        assert ExitCode.BLOCK == 2

    def test_exit_code_is_int(self):
        """終了コードはint互換"""
        assert int(ExitCode.SUCCESS) == 0
        assert int(ExitCode.BLOCK) == 2


class TestProjectDir:
    """project_dir プロパティのテスト"""

    def test_project_dir_from_env(self):
        """CLAUDE_PROJECT_DIR環境変数から取得"""
        hook = ConcreteHook()
        with patch.dict(os.environ, {'CLAUDE_PROJECT_DIR': '/workspace/myproject'}):
            assert hook.project_dir == '/workspace/myproject'

    def test_project_dir_not_set(self):
        """環境変数未設定時はNone"""
        hook = ConcreteHook()
        with patch.dict(os.environ, {}, clear=True):
            # CLAUDE_PROJECT_DIRを削除
            os.environ.pop('CLAUDE_PROJECT_DIR', None)
            assert hook.project_dir is None


class TestIsRemote:
    """is_remote プロパティのテスト"""

    def test_is_remote_true(self):
        """CLAUDE_CODE_REMOTE=trueの場合True"""
        hook = ConcreteHook()
        with patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': 'true'}):
            assert hook.is_remote is True

    def test_is_remote_true_uppercase(self):
        """CLAUDE_CODE_REMOTE=TRUEでもTrue"""
        hook = ConcreteHook()
        with patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': 'TRUE'}):
            assert hook.is_remote is True

    def test_is_remote_false(self):
        """CLAUDE_CODE_REMOTE=falseの場合False"""
        hook = ConcreteHook()
        with patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': 'false'}):
            assert hook.is_remote is False

    def test_is_remote_not_set(self):
        """環境変数未設定時はFalse"""
        hook = ConcreteHook()
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop('CLAUDE_CODE_REMOTE', None)
            assert hook.is_remote is False

    def test_is_remote_empty(self):
        """空文字の場合False"""
        hook = ConcreteHook()
        with patch.dict(os.environ, {'CLAUDE_CODE_REMOTE': ''}):
            assert hook.is_remote is False


class TestExitBlock:
    """exit_block メソッドのテスト"""

    def test_exit_block_writes_to_stderr(self, capsys):
        """stderrに理由を出力"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit) as exc_info:
            hook.exit_block("ブロックの理由")

        assert exc_info.value.code == ExitCode.BLOCK
        captured = capsys.readouterr()
        assert "ブロックの理由" in captured.err

    def test_exit_block_exits_with_code_2(self):
        """終了コード2で終了"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit) as exc_info:
            hook.exit_block("test")

        assert exc_info.value.code == 2


class TestExitSuccess:
    """exit_success メソッドのテスト"""

    def test_exit_success_writes_json_to_stdout(self, capsys):
        """stdoutにJSON出力"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit) as exc_info:
            hook.exit_success(
                hook_event_name='PreToolUse',
                permission_decision='allow',
                reason='テスト理由'
            )

        assert exc_info.value.code == ExitCode.SUCCESS
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output['hookSpecificOutput']['hookEventName'] == 'PreToolUse'
        assert output['hookSpecificOutput']['permissionDecision'] == 'allow'
        assert output['hookSpecificOutput']['permissionDecisionReason'] == 'テスト理由'

    def test_exit_success_without_reason(self, capsys):
        """理由なしでも動作"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit):
            hook.exit_success()

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert 'permissionDecisionReason' not in output['hookSpecificOutput']

    def test_exit_success_with_extra_fields(self, capsys):
        """追加フィールドを含む"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit):
            hook.exit_success(extra_fields={'continue': False, 'stopReason': '停止'})

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output['continue'] is False
        assert output['stopReason'] == '停止'


class TestExitSkip:
    """exit_skip メソッドのテスト"""

    def test_exit_skip_no_output(self, capsys):
        """出力なしで終了"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit) as exc_info:
            hook.exit_skip()

        assert exc_info.value.code == ExitCode.SUCCESS
        captured = capsys.readouterr()
        assert captured.out == ""


class TestRunWithExitCode:
    """run メソッドの ExitCode テスト"""

    def test_run_returns_exit_code_success(self):
        """正常終了時はExitCode.SUCCESSを返す"""
        hook = ConcreteHook()

        with patch.object(hook, 'read_input', return_value={}):
            with patch('application.install_hooks.ensure_config_exists'):
                result = hook.run()

        assert result == ExitCode.SUCCESS

    def test_run_returns_exit_code_error_on_exception(self):
        """例外時はExitCode.ERRORを返す"""
        hook = ConcreteHook()

        with patch.object(hook, 'read_input', side_effect=Exception('error')):
            with patch('application.install_hooks.ensure_config_exists'):
                result = hook.run()

        assert result == ExitCode.ERROR


class TestHookResponse:
    """HookResponse型のテスト"""

    def test_hook_response_default_values(self):
        """デフォルト値の確認"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse()
        assert response.hook_event_name == "PreToolUse"
        assert response.permission_decision == "allow"
        assert response.permission_decision_reason is None
        assert response.updated_input is None
        assert response.additional_context is None
        assert response.continue_processing is None
        assert response.stop_reason is None
        assert response.suppress_output is None

    def test_hook_response_to_dict_minimal(self):
        """最小限のto_dict出力"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse()
        result = response.to_dict()

        assert result == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }

    def test_hook_response_to_dict_with_reason(self):
        """理由付きto_dict出力"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse(
            permission_decision="deny",
            permission_decision_reason="危険なコマンド"
        )
        result = response.to_dict()

        assert result["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert result["hookSpecificOutput"]["permissionDecisionReason"] == "危険なコマンド"

    def test_hook_response_to_dict_with_updated_input(self):
        """updatedInput付きto_dict出力"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse(
            permission_decision="allow",
            updated_input={"command": "safe_command"}
        )
        result = response.to_dict()

        assert result["hookSpecificOutput"]["updatedInput"] == {"command": "safe_command"}

    def test_hook_response_to_dict_with_additional_context(self):
        """additionalContext付きto_dict出力"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse(
            permission_decision="allow",
            additional_context="このプロジェクトでは..."
        )
        result = response.to_dict()

        assert result["hookSpecificOutput"]["additionalContext"] == "このプロジェクトでは..."

    def test_hook_response_to_dict_with_continue_false(self):
        """continue=false付きto_dict出力"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse(continue_processing=False, stop_reason="停止理由")
        result = response.to_dict()

        assert result["continue"] is False
        assert result["stopReason"] == "停止理由"

    def test_hook_response_to_dict_with_suppress_output(self):
        """suppressOutput付きto_dict出力"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse(suppress_output=True)
        result = response.to_dict()

        assert result["suppressOutput"] is True

    def test_hook_response_allow_factory(self):
        """allowファクトリメソッド"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse.allow(reason="許可理由")

        assert response.permission_decision == "allow"
        assert response.permission_decision_reason == "許可理由"

    def test_hook_response_deny_factory(self):
        """denyファクトリメソッド"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse.deny(reason="拒否理由")

        assert response.permission_decision == "deny"
        assert response.permission_decision_reason == "拒否理由"

    def test_hook_response_ask_factory(self):
        """askファクトリメソッド"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse.ask(reason="確認理由")

        assert response.permission_decision == "ask"
        assert response.permission_decision_reason == "確認理由"

    def test_hook_response_allow_with_updated_input(self):
        """allowファクトリでupdatedInput"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse.allow(
            updated_input={"command": "echo safe"}
        )

        assert response.permission_decision == "allow"
        assert response.updated_input == {"command": "echo safe"}

    def test_hook_response_ask_with_updated_input(self):
        """askファクトリでupdatedInput"""
        from src.domain.hooks.hook_response import HookResponse
        response = HookResponse.ask(
            reason="確認",
            updated_input={"command": "rm file.txt"}
        )

        assert response.permission_decision == "ask"
        assert response.updated_input == {"command": "rm file.txt"}


class TestExitWithResponse:
    """exit_with_response メソッドのテスト"""

    def test_exit_with_response_allow(self, capsys):
        """HookResponseで許可終了"""
        from src.domain.hooks.hook_response import HookResponse
        hook = ConcreteHook()
        response = HookResponse.allow()

        with pytest.raises(SystemExit) as exc_info:
            hook.exit_with_response(response)

        assert exc_info.value.code == ExitCode.SUCCESS
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_exit_with_response_deny(self, capsys):
        """HookResponseで拒否終了"""
        from src.domain.hooks.hook_response import HookResponse
        hook = ConcreteHook()
        response = HookResponse.deny(reason="NG")

        with pytest.raises(SystemExit):
            hook.exit_with_response(response)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "NG"

    def test_exit_with_response_with_updated_input(self, capsys):
        """updatedInput付きで終了"""
        from src.domain.hooks.hook_response import HookResponse
        hook = ConcreteHook()
        response = HookResponse.allow(updated_input={"command": "safe"})

        with pytest.raises(SystemExit):
            hook.exit_with_response(response)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["updatedInput"] == {"command": "safe"}

    def test_exit_with_response_with_additional_context(self, capsys):
        """additionalContext付きで終了"""
        from src.domain.hooks.hook_response import HookResponse
        hook = ConcreteHook()
        response = HookResponse.allow(additional_context="追加情報")

        with pytest.raises(SystemExit):
            hook.exit_with_response(response)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["additionalContext"] == "追加情報"


class TestExitAllow:
    """exit_allow メソッドのテスト"""

    def test_exit_allow_minimal(self, capsys):
        """最小限のexit_allow"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit) as exc_info:
            hook.exit_allow()

        assert exc_info.value.code == ExitCode.SUCCESS
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_exit_allow_with_reason(self, capsys):
        """理由付きexit_allow"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit):
            hook.exit_allow(reason="許可理由")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "許可理由"

    def test_exit_allow_with_updated_input(self, capsys):
        """updatedInput付きexit_allow"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit):
            hook.exit_allow(updated_input={"command": "safe"})

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["updatedInput"] == {"command": "safe"}

    def test_exit_allow_with_additional_context(self, capsys):
        """additionalContext付きexit_allow"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit):
            hook.exit_allow(additional_context="規約情報")

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["additionalContext"] == "規約情報"

    def test_exit_allow_with_suppress_output(self, capsys):
        """suppressOutput付きexit_allow"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit):
            hook.exit_allow(suppress_output=True)

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["suppressOutput"] is True


class TestExitDeny:
    """exit_deny メソッドのテスト"""

    def test_exit_deny(self, capsys):
        """exit_denyの基本動作"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit) as exc_info:
            hook.exit_deny(reason="拒否理由")

        assert exc_info.value.code == ExitCode.SUCCESS
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "拒否理由"


class TestExitAsk:
    """exit_ask メソッドのテスト"""

    def test_exit_ask_basic(self, capsys):
        """exit_askの基本動作"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit) as exc_info:
            hook.exit_ask(reason="確認理由")

        assert exc_info.value.code == ExitCode.SUCCESS
        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
        assert output["hookSpecificOutput"]["permissionDecisionReason"] == "確認理由"

    def test_exit_ask_with_updated_input(self, capsys):
        """updatedInput付きexit_ask"""
        hook = ConcreteHook()
        with pytest.raises(SystemExit):
            hook.exit_ask(reason="確認", updated_input={"command": "rm file.txt"})

        captured = capsys.readouterr()
        output = json.loads(captured.out.strip())
        assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
        assert output["hookSpecificOutput"]["updatedInput"] == {"command": "rm file.txt"}


class TestMarkerPatterns:
    """MarkerPatternsクラスのテスト"""

    def test_pattern_constants_format(self):
        """パターン定数が正しい形式であること"""
        # 各パターンにプレースホルダが含まれていること
        assert "{session_id}" in MarkerPatterns.SESSION_STARTUP
        assert "{class_name}" in MarkerPatterns.HOOK_SESSION
        assert "{session_id}" in MarkerPatterns.HOOK_SESSION
        assert "{class_name}" in MarkerPatterns.RULE
        assert "{session_id}" in MarkerPatterns.RULE
        assert "{rule_hash}" in MarkerPatterns.RULE
        assert "{session_id}" in MarkerPatterns.COMMAND
        assert "{command_hash}" in MarkerPatterns.COMMAND

    def test_pattern_prefixes(self):
        """パターン定数がclaude_で始まること"""
        assert MarkerPatterns.SESSION_STARTUP.startswith("claude_")
        assert MarkerPatterns.HOOK_SESSION.startswith("claude_")
        assert MarkerPatterns.RULE.startswith("claude_")
        assert MarkerPatterns.COMMAND.startswith("claude_")

    def test_format_session_startup(self):
        """format_session_startupのテスト"""
        result = MarkerPatterns.format_session_startup("test-session-123")
        assert result == "claude_session_startup_test-session-123"

    def test_format_hook_session(self):
        """format_hook_sessionのテスト"""
        result = MarkerPatterns.format_hook_session("MyHook", "session-456")
        assert result == "claude_hook_MyHook_session_session-456"

    def test_format_rule(self):
        """format_ruleのテスト"""
        result = MarkerPatterns.format_rule("RuleHook", "session-789", "abc123")
        assert result == "claude_rule_RuleHook_session-789_abc123"

    def test_format_command(self):
        """format_commandのテスト"""
        result = MarkerPatterns.format_command("session-001", "def456")
        assert result == "claude_cmd_session-001_def456"

    def test_get_glob_patterns_returns_list(self):
        """get_glob_patternsがリストを返すこと"""
        patterns = MarkerPatterns.get_glob_patterns("test-session")
        assert isinstance(patterns, list)
        assert len(patterns) == 4  # 4種類のパターン

    def test_get_glob_patterns_contains_session_id(self):
        """get_glob_patternsの各パターンにsession_idが含まれること"""
        session_id = "unique-session-id"
        patterns = MarkerPatterns.get_glob_patterns(session_id)
        for pattern in patterns:
            assert session_id in pattern

    def test_get_glob_patterns_format(self):
        """get_glob_patternsのパターン形式が正しいこと"""
        patterns = MarkerPatterns.get_glob_patterns("test-session")
        # 各パターンがワイルドカードを含むこと
        assert any("*" in p and "session_startup" in p for p in patterns)
        assert any("*" in p and "rule" in p for p in patterns)
        assert any("*" in p and "cmd" in p for p in patterns)
        assert any("*" in p and "hook" in p for p in patterns)

    def test_glob_patterns_match_formatted_markers(self, tmp_path):
        """globパターンがフォーマット済みマーカーにマッチすること"""
        import fnmatch
        
        session_id = "test-session-xyz"
        
        # 各フォーマットメソッドで生成されるマーカー名
        markers = [
            MarkerPatterns.format_session_startup(session_id),
            MarkerPatterns.format_hook_session("TestHook", session_id),
            MarkerPatterns.format_rule("TestHook", session_id, "abc123"),
            MarkerPatterns.format_command(session_id, "def456"),
        ]
        
        # globパターン
        patterns = MarkerPatterns.get_glob_patterns(session_id)
        
        # 各マーカーが少なくとも1つのパターンにマッチすること
        for marker in markers:
            matched = any(fnmatch.fnmatch(marker, pattern) for pattern in patterns)
            assert matched, f"Marker '{marker}' did not match any pattern"
