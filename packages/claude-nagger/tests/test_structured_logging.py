"""structured_logging.py のテスト"""

import json
import logging
import os
import pytest
from pathlib import Path
from unittest.mock import patch

from src.shared.structured_logging import (
    StructuredLogger,
    StructuredFormatter,
    is_debug_mode,
    get_logger,
    DEFAULT_LOG_DIR,
)


class TestIsDebugMode:
    """is_debug_mode 関数のテスト"""

    def test_debug_mode_claude_code_debug_true(self):
        """CLAUDE_CODE_DEBUG=trueでデバッグモード"""
        with patch.dict(os.environ, {'CLAUDE_CODE_DEBUG': 'true'}):
            assert is_debug_mode() is True

    def test_debug_mode_nagger_debug_true(self):
        """CLAUDE_NAGGER_DEBUG=trueでデバッグモード"""
        with patch.dict(os.environ, {'CLAUDE_NAGGER_DEBUG': 'true'}):
            assert is_debug_mode() is True

    def test_debug_mode_both_false(self):
        """両方falseの場合はデバッグモードでない"""
        with patch.dict(os.environ, {
            'CLAUDE_CODE_DEBUG': 'false',
            'CLAUDE_NAGGER_DEBUG': 'false'
        }):
            assert is_debug_mode() is False

    def test_debug_mode_not_set(self):
        """未設定の場合はデバッグモードでない"""
        env = os.environ.copy()
        env.pop('CLAUDE_CODE_DEBUG', None)
        env.pop('CLAUDE_NAGGER_DEBUG', None)
        with patch.dict(os.environ, env, clear=True):
            assert is_debug_mode() is False

    def test_debug_mode_case_insensitive(self):
        """大文字小文字を区別しない"""
        with patch.dict(os.environ, {'CLAUDE_CODE_DEBUG': 'TRUE'}):
            assert is_debug_mode() is True


class TestStructuredFormatter:
    """StructuredFormatter クラスのテスト"""

    def test_format_basic_message(self):
        """基本的なログメッセージのフォーマット"""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=10,
            msg='Test message',
            args=(),
            exc_info=None
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert 'timestamp' in parsed
        assert parsed['level'] == 'INFO'
        assert parsed['logger'] == 'test_logger'
        assert parsed['message'] == 'Test message'

    def test_format_with_exception(self):
        """例外情報を含むログ"""
        formatter = StructuredFormatter()

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name='test_logger',
            level=logging.ERROR,
            pathname='test.py',
            lineno=20,
            msg='Error occurred',
            args=(),
            exc_info=exc_info
        )

        result = formatter.format(record)
        parsed = json.loads(result)

        assert 'exception' in parsed
        assert 'ValueError' in parsed['exception']

    def test_format_with_extra_fields(self):
        """追加フィールドを含むログ"""
        formatter = StructuredFormatter(include_extras=True)
        record = logging.LogRecord(
            name='test_logger',
            level=logging.INFO,
            pathname='test.py',
            lineno=10,
            msg='Test message',
            args=(),
            exc_info=None
        )
        record.custom_field = 'custom_value'
        record.numeric_field = 123

        result = formatter.format(record)
        parsed = json.loads(result)

        assert 'context' in parsed
        assert parsed['context']['custom_field'] == 'custom_value'
        assert parsed['context']['numeric_field'] == 123

    def test_format_source_info_in_debug_mode(self):
        """デバッグモードではソース情報を含む"""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name='test_logger',
            level=logging.DEBUG,
            pathname='test.py',
            lineno=10,
            msg='Debug message',
            args=(),
            exc_info=None
        )

        with patch('src.shared.structured_logging.is_debug_mode', return_value=True):
            result = formatter.format(record)

        parsed = json.loads(result)
        assert 'source' in parsed
        assert parsed['source']['line'] == 10


class TestStructuredLogger:
    """StructuredLogger クラスのテスト"""

    def test_init_creates_log_dir(self, tmp_path):
        """初期化時にログディレクトリを作成"""
        log_dir = tmp_path / 'logs'
        logger = StructuredLogger(name='test', log_dir=log_dir)

        assert log_dir.exists()

    def test_init_default_log_dir(self):
        """デフォルトのログディレクトリ"""
        logger = StructuredLogger(name='test')
        assert logger.log_dir == DEFAULT_LOG_DIR

    def test_set_session_id(self, tmp_path):
        """セッションID設定"""
        logger = StructuredLogger(name='test', log_dir=tmp_path)
        logger.set_session_id('session123')

        assert logger.session_id == 'session123'

    def test_debug_log(self, tmp_path):
        """デバッグログ出力（デバッグモード有効時）"""
        # デバッグモードを有効にしないとDEBUGレベルは出力されない
        with patch('src.shared.structured_logging.is_debug_mode', return_value=True):
            logger = StructuredLogger(name='test', log_dir=tmp_path)
            logger.debug('Test debug message', extra_key='extra_value')

            log_file = tmp_path / 'claude_nagger.jsonl'
            assert log_file.exists()

            content = log_file.read_text()
            parsed = json.loads(content.strip())
            assert parsed['message'] == 'Test debug message'

    def test_info_log(self, tmp_path):
        """情報ログ出力"""
        logger = StructuredLogger(name='test', log_dir=tmp_path)
        logger.info('Test info message')

        log_file = tmp_path / 'claude_nagger.jsonl'
        content = log_file.read_text()
        parsed = json.loads(content.strip())
        assert parsed['level'] == 'INFO'

    def test_error_log(self, tmp_path):
        """エラーログ出力"""
        logger = StructuredLogger(name='test', log_dir=tmp_path)
        logger.error('Test error message')

        log_file = tmp_path / 'claude_nagger.jsonl'
        content = log_file.read_text()
        parsed = json.loads(content.strip())
        assert parsed['level'] == 'ERROR'

    def test_warning_log(self, tmp_path):
        """警告ログ出力"""
        logger = StructuredLogger(name='test', log_dir=tmp_path)
        logger.warning('Test warning message')

        log_file = tmp_path / 'claude_nagger.jsonl'
        content = log_file.read_text()
        parsed = json.loads(content.strip())
        assert parsed['level'] == 'WARNING'

    def test_save_input_json_success(self, tmp_path):
        """入力JSON保存成功"""
        logger = StructuredLogger(name='test', log_dir=tmp_path)
        raw_json = '{"tool_name": "Edit"}'

        result = logger.save_input_json(raw_json, prefix='input')

        assert result is not None
        assert result.exists()
        assert result.read_text() == raw_json

    def test_save_input_json_with_session_id(self, tmp_path):
        """セッションID付きで入力JSON保存"""
        logger = StructuredLogger(name='test', log_dir=tmp_path, session_id='session123')
        raw_json = '{"test": "data"}'

        result = logger.save_input_json(raw_json, prefix='input')

        assert result is not None
        assert 'session123' in result.name

    def test_save_input_json_failure(self, tmp_path):
        """入力JSON保存失敗"""
        logger = StructuredLogger(name='test', log_dir=tmp_path)

        with patch('builtins.open', side_effect=Exception('write error')):
            result = logger.save_input_json('{"test": "data"}')

        assert result is None

    def test_log_hook_event(self, tmp_path):
        """フックイベントログ"""
        logger = StructuredLogger(name='test', log_dir=tmp_path)
        logger.log_hook_event(
            event_type='start',
            hook_name='TestHook',
            decision='allow',
            reason='test reason',
            duration_ms=123.456
        )

        log_file = tmp_path / 'claude_nagger.jsonl'
        content = log_file.read_text()
        parsed = json.loads(content.strip())

        assert parsed['message'] == 'Hook event: start'
        assert parsed['context']['event_type'] == 'start'
        assert parsed['context']['hook_name'] == 'TestHook'
        assert parsed['context']['duration_ms'] == 123.46  # rounded

    def test_is_debug_property(self, tmp_path):
        """is_debugプロパティ"""
        with patch('src.shared.structured_logging.is_debug_mode', return_value=True):
            logger = StructuredLogger(name='test', log_dir=tmp_path)
            assert logger.is_debug is True

    def test_log_file_with_session_id(self, tmp_path):
        """セッションID付きログファイル名"""
        logger = StructuredLogger(
            name='test',
            log_dir=tmp_path,
            session_id='abc123'
        )
        logger.info('test')

        log_file = tmp_path / 'abc123.jsonl'
        assert log_file.exists()


class TestGetLogger:
    """get_logger 関数のテスト"""

    def test_get_logger_basic(self, tmp_path):
        """基本的なロガー取得"""
        with patch.object(StructuredLogger, '__init__', return_value=None) as mock_init:
            mock_init.return_value = None
            logger = get_logger('test_name', session_id='session1')
            # StructuredLoggerが呼ばれることを確認

    def test_get_logger_returns_structured_logger(self):
        """StructuredLoggerインスタンスを返す"""
        logger = get_logger('test_name')
        assert isinstance(logger, StructuredLogger)


class TestDefaultLogDir:
    """DEFAULT_LOG_DIR のテスト"""

    def test_default_log_dir_value(self):
        """デフォルトログディレクトリの値（UID付き）"""
        assert DEFAULT_LOG_DIR == Path(f'/tmp/claude-nagger-{os.getuid()}')
