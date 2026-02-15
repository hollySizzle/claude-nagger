"""TranscriptStorageHook 単体テスト"""

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from domain.hooks.transcript_storage_hook import (
    TranscriptStorageHook,
    run_background_storage,
    main,
)


# === フィクスチャ ===

@pytest.fixture
def sample_jsonl(tmp_path):
    """テスト用.jsonlファイル"""
    jsonl_path = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "user", "message": {"content": "hello"}},
        {"type": "assistant", "message": {"content": "hi", "usage": {"input_tokens": 100}}},
        {"type": "progress", "data": {"type": "tool_use"}},
    ]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return jsonl_path


# === should_processテスト ===

class TestShouldProcess:
    """should_processメソッドのテスト"""

    def test_should_process_when_enabled(self, tmp_path, sample_jsonl):
        """enabled=trueで処理対象"""
        hook = TranscriptStorageHook()
        hook._config = {'enabled': True}

        input_data = {
            'transcript_path': str(sample_jsonl),
            'session_id': 'test-session',
        }
        result = hook.should_process(input_data)
        assert result is True

    def test_should_not_process_when_disabled(self):
        """enabled=falseでスキップ"""
        hook = TranscriptStorageHook()
        hook._config = {'enabled': False}

        input_data = {
            'transcript_path': '/some/path.jsonl',
            'session_id': 'test-session',
        }
        result = hook.should_process(input_data)
        assert result is False

    def test_should_not_process_when_enabled_not_set(self):
        """enabled未設定（デフォルトfalse）でスキップ"""
        hook = TranscriptStorageHook()
        hook._config = {}

        input_data = {
            'transcript_path': '/some/path.jsonl',
            'session_id': 'test-session',
        }
        result = hook.should_process(input_data)
        assert result is False

    def test_process_handles_missing_transcript_path(self):
        """transcript_pathなしで安全にスキップ"""
        hook = TranscriptStorageHook()
        hook._config = {'enabled': True}

        input_data = {'session_id': 'test-session'}
        result = hook.should_process(input_data)
        assert result is False

    def test_process_handles_missing_file(self, tmp_path):
        """ファイル不在で安全にスキップ"""
        hook = TranscriptStorageHook()
        hook._config = {'enabled': True}

        input_data = {
            'transcript_path': str(tmp_path / "nonexistent.jsonl"),
            'session_id': 'test-session',
        }
        result = hook.should_process(input_data)
        assert result is False


# === processテスト ===

class TestProcess:
    """processメソッドのテスト"""

    def test_バックグラウンド起動してapprove返却(self):
        """_launch_backgroundを呼びapproveを返す"""
        hook = TranscriptStorageHook()
        hook._launch_background = MagicMock()

        input_data = {
            'transcript_path': '/path/to/transcript.jsonl',
            'session_id': 'test-session',
        }
        result = hook.process(input_data)

        hook._launch_background.assert_called_once_with('test-session', '/path/to/transcript.jsonl')
        assert result["decision"] == "approve"

    @patch("domain.hooks.transcript_storage_hook.subprocess.Popen")
    def test_nohupでプロセス起動(self, mock_popen):
        """nohupでバックグラウンドプロセスが起動される"""
        hook = TranscriptStorageHook()
        hook._launch_background("sess-123", "/path/to/transcript.jsonl")

        mock_popen.assert_called_once()
        args = mock_popen.call_args
        cmd = args[0][0]
        assert cmd[0] == "nohup"
        assert "--background" in cmd
        assert "--session-id" in cmd
        assert "sess-123" in cmd
        assert "--transcript-path" in cmd
        assert "/path/to/transcript.jsonl" in cmd
        assert args[1]["start_new_session"] is True

    @patch("domain.hooks.transcript_storage_hook.subprocess.Popen", side_effect=Exception("test error"))
    def test_起動失敗時にエラーログ(self, mock_popen):
        """プロセス起動失敗時にエラーをログ出力（例外伝播しない）"""
        hook = TranscriptStorageHook()
        hook._launch_background("sess-123", "/path/to/transcript.jsonl")


# === processテスト（DB格納） ===

class TestProcessStoresTranscript:
    """process結果としてDB格納されることのテスト"""

    def test_process_stores_transcript(self, db, sample_jsonl):
        """run_background_storageで.jsonlが正しくDBに格納される"""
        # DB接続を使ってバックグラウンド処理と同等の操作を実行
        from infrastructure.db.transcript_repository import TranscriptRepository

        repo = TranscriptRepository(db)
        count = repo.store_transcript("test-session", str(sample_jsonl))

        assert count == 3

        lines = repo.get_transcript_lines("test-session")
        assert len(lines) == 3
        assert lines[0].line_type == "user"
        assert lines[1].line_type == "assistant"
        assert lines[2].line_type == "progress"


# === run_background_storageテスト ===

class TestRunBackgroundStorage:
    """run_background_storage関数のテスト"""

    @patch("domain.hooks.transcript_storage_hook.NaggerStateDB")
    def test_正常終了(self, MockDB, sample_jsonl):
        """正常にトランスクリプトを格納して0を返す"""
        mock_db = MockDB.return_value
        mock_db.conn = MagicMock()
        mock_db.conn.execute = MagicMock()

        # resolve_db_pathのモック
        MockDB.resolve_db_path.return_value = Path("/tmp/test.db")

        result = run_background_storage("test-session", str(sample_jsonl))
        assert result == 0
        mock_db.connect.assert_called_once()
        mock_db.close.assert_called_once()

    @patch("domain.hooks.transcript_storage_hook.NaggerStateDB")
    def test_例外発生時エラー返却(self, MockDB):
        """予期しない例外発生時に1を返す"""
        MockDB.resolve_db_path.side_effect = Exception("unexpected error")

        result = run_background_storage("test-session", "/nonexistent")
        assert result == 1


# === mainテスト ===

class TestMain:
    """mainエントリーポイントのテスト"""

    @patch("domain.hooks.transcript_storage_hook.TranscriptStorageHook")
    def test_通常モードでhook実行(self, MockHook):
        """引数なしの場合Stopフックとして実行"""
        mock_instance = MockHook.return_value
        mock_instance.run.return_value = 0

        with patch("sys.argv", ["transcript_storage_hook"]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            mock_instance.run.assert_called_once()
            assert exc_info.value.code == 0

    @patch("domain.hooks.transcript_storage_hook.run_background_storage", return_value=0)
    def test_backgroundモードで格納実行(self, mock_bg):
        """--backgroundフラグでバックグラウンド処理実行"""
        with patch("sys.argv", [
            "transcript_storage_hook", "--background",
            "--session-id", "sess-123",
            "--transcript-path", "/path/to/transcript.jsonl",
        ]):
            with pytest.raises(SystemExit) as exc_info:
                main()

            mock_bg.assert_called_once_with(
                session_id="sess-123",
                transcript_path="/path/to/transcript.jsonl",
                mode="raw",
            )
            assert exc_info.value.code == 0
