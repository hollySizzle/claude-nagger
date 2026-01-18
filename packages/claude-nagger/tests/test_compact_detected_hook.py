"""CompactDetectedHookのテスト"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.domain.hooks.compact_detected_hook import CompactDetectedHook, main


class TestCompactDetectedHookInit:
    """初期化のテスト"""

    def test_init_sets_debug_true(self):
        """debug=Trueで初期化される"""
        hook = CompactDetectedHook()
        assert hook.debug is True


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


class TestResetMarkerFiles:
    """_reset_marker_filesメソッドのテスト"""

    def _do_reset(self, tmpdir, session_id):
        """テスト用のリセット処理"""
        temp_dir = Path(tmpdir)
        reset_count = 0
        patterns = [
            f"claude_session_startup_*{session_id}*",
            f"claude_rule_*{session_id}*",
            f"claude_cmd_{session_id}_*",
            f"claude_hook_*_session_{session_id}",
        ]
        for pattern in patterns:
            for marker_path in temp_dir.glob(pattern):
                marker_path.unlink()
                reset_count += 1
        return reset_count

    def test_deletes_session_startup_marker(self):
        """SessionStartupマーカーを削除する"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = "test-session-123"
            temp_dir = Path(tmpdir)
            
            # マーカーファイルを作成
            marker = temp_dir / f"claude_session_startup_{session_id}"
            marker.touch()
            assert marker.exists()
            
            # リセット実行
            count = self._do_reset(tmpdir, session_id)
            
            assert count == 1
            assert not marker.exists()

    def test_deletes_multiple_markers(self):
        """複数のマーカーファイルを削除する"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = "test-session-456"
            temp_dir = Path(tmpdir)
            
            # 各種マーカーファイルを作成
            markers = [
                temp_dir / f"claude_session_startup_{session_id}",
                temp_dir / f"claude_rule_TestHook_{session_id}_abc123",
                temp_dir / f"claude_cmd_{session_id}_def456",
                temp_dir / f"claude_hook_TestHook_session_{session_id}",
            ]
            for m in markers:
                m.touch()
            
            # リセット実行
            count = self._do_reset(tmpdir, session_id)
            
            assert count == 4
            for m in markers:
                assert not m.exists()

    def test_returns_zero_when_no_markers(self):
        """マーカーがない場合は0を返す"""
        with tempfile.TemporaryDirectory() as tmpdir:
            count = self._do_reset(tmpdir, "nonexistent-session")
            assert count == 0


class TestProcess:
    """processメソッドのテスト"""

    def test_calls_reset_marker_files(self):
        """_reset_marker_filesが呼び出される"""
        hook = CompactDetectedHook()
        hook._reset_marker_files = MagicMock(return_value=3)
        
        input_data = {
            "session_id": "test-123",
        }
        
        result = hook.process(input_data)
        
        hook._reset_marker_files.assert_called_once_with("test-123")

    def test_returns_approve_decision(self):
        """approveを返す"""
        hook = CompactDetectedHook()
        hook._reset_marker_files = MagicMock(return_value=0)
        
        input_data = {
            "session_id": "test-123",
        }
        
        result = hook.process(input_data)
        
        assert result["decision"] == "approve"


class TestMain:
    """mainエントリーポイントのテスト"""

    def test_main_creates_hook_and_runs(self):
        """mainがフックを作成して実行する"""
        with patch.object(CompactDetectedHook, 'run', return_value=0) as mock_run:
            with pytest.raises(SystemExit) as exc_info:
                main()
            
            mock_run.assert_called_once()
            assert exc_info.value.code == 0
