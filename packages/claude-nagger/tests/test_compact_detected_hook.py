"""CompactDetectedHookのテスト"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.domain.hooks.compact_detected_hook import CompactDetectedHook, main


class TestCompactDetectedHookInit:
    """初期化のテスト"""

    def test_init_sets_debug_true(self):
        """debug=Trueで初期化される"""
        with patch.object(CompactDetectedHook, '__init__', lambda self: None):
            hook = CompactDetectedHook()
            hook.debug = True
            hook.history_file = Path.cwd() / ".claude-nagger" / "compact_history.jsonl"
        
        # 実際の初期化テスト
        hook = CompactDetectedHook()
        assert hook.debug is True

    def test_init_sets_history_file_path(self):
        """履歴ファイルパスが正しく設定される"""
        hook = CompactDetectedHook()
        expected = Path.cwd() / ".claude-nagger" / "compact_history.jsonl"
        assert hook.history_file == expected


class TestShouldProcess:
    """should_processメソッドのテスト"""

    def test_compact_source_returns_true(self):
        """source=compactの場合Trueを返す"""
        hook = CompactDetectedHook()
        input_data = {
            "source": "compact",
            "hook_event_name": "SessionStart",
            "session_id": "test-123",
        }
        assert hook.should_process(input_data) is True

    def test_non_compact_source_returns_false(self):
        """source!=compactの場合Falseを返す"""
        hook = CompactDetectedHook()
        input_data = {
            "source": "user",
            "hook_event_name": "SessionStart",
            "session_id": "test-123",
        }
        assert hook.should_process(input_data) is False

    def test_empty_source_returns_false(self):
        """sourceが空の場合Falseを返す"""
        hook = CompactDetectedHook()
        input_data = {
            "hook_event_name": "SessionStart",
            "session_id": "test-123",
        }
        assert hook.should_process(input_data) is False


class TestSaveCompactHistory:
    """_save_compact_historyメソッドのテスト"""

    def test_creates_directory_if_not_exists(self):
        """ディレクトリが存在しない場合作成される"""
        with tempfile.TemporaryDirectory() as tmpdir:
            hook = CompactDetectedHook()
            hook.history_file = Path(tmpdir) / "subdir" / "history.jsonl"
            
            hook._save_compact_history("session-123", "/path/to/transcript")
            
            assert hook.history_file.parent.exists()

    def test_appends_record_to_jsonl(self):
        """レコードがJSONL形式で追記される"""
        with tempfile.TemporaryDirectory() as tmpdir:
            hook = CompactDetectedHook()
            hook.history_file = Path(tmpdir) / "history.jsonl"
            
            # 2回保存
            hook._save_compact_history("session-1", "/path/1")
            hook._save_compact_history("session-2", "/path/2")
            
            # 2行のJSONLが書き込まれている
            lines = hook.history_file.read_text().strip().split("\n")
            assert len(lines) == 2
            
            # 各行が正しいJSON
            record1 = json.loads(lines[0])
            record2 = json.loads(lines[1])
            
            assert record1["session_id"] == "session-1"
            assert record2["session_id"] == "session-2"

    def test_record_contains_required_fields(self):
        """レコードに必須フィールドが含まれる"""
        with tempfile.TemporaryDirectory() as tmpdir:
            hook = CompactDetectedHook()
            hook.history_file = Path(tmpdir) / "history.jsonl"
            
            hook._save_compact_history("test-session", "/transcript/path")
            
            record = json.loads(hook.history_file.read_text().strip())
            
            assert "timestamp" in record
            assert record["session_id"] == "test-session"
            assert record["transcript_path"] == "/transcript/path"


class TestBuildReminderMessage:
    """_build_reminder_messageメソッドのテスト"""

    def test_returns_reminder_string(self):
        """リマインダー文字列を返す"""
        hook = CompactDetectedHook()
        message = hook._build_reminder_message()
        
        assert isinstance(message, str)
        assert "COMPACT DETECTED" in message
        assert len(message) > 0


class TestProcess:
    """processメソッドのテスト"""

    def test_calls_save_compact_history(self):
        """_save_compact_historyが呼び出される"""
        hook = CompactDetectedHook()
        hook._save_compact_history = MagicMock()
        
        input_data = {
            "session_id": "test-123",
            "transcript_path": "/path/to/transcript",
        }
        
        with pytest.raises(SystemExit):
            hook.process(input_data)
        
        hook._save_compact_history.assert_called_once_with(
            "test-123", "/path/to/transcript"
        )

    def test_exits_with_hook_response(self):
        """HookResponseで終了する"""
        hook = CompactDetectedHook()
        hook._save_compact_history = MagicMock()
        
        input_data = {
            "session_id": "test-123",
            "transcript_path": "/path/to/transcript",
        }
        
        with pytest.raises(SystemExit) as exc_info:
            hook.process(input_data)
        
        # 正常終了(0)
        assert exc_info.value.code == 0

    def test_outputs_json_with_additional_context(self, capsys):
        """additionalContextを含むJSONを出力する"""
        hook = CompactDetectedHook()
        hook._save_compact_history = MagicMock()
        
        input_data = {
            "session_id": "test-123",
            "transcript_path": "/path/to/transcript",
        }
        
        with pytest.raises(SystemExit):
            hook.process(input_data)
        
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        
        assert "hookSpecificOutput" in output
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert "additionalContext" in output["hookSpecificOutput"]


class TestMain:
    """mainエントリーポイントのテスト"""

    def test_main_creates_hook_and_runs(self):
        """mainがフックを作成して実行する"""
        with patch.object(CompactDetectedHook, 'run', return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            mock_run.assert_called_once()
            assert exc_info.value.code == 0
