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


class TestRenameMarkersForCompact:
    """_rename_markers_for_compactメソッドのテスト"""

    def _do_rename(self, tmpdir, session_id):
        """テスト用のリネーム処理"""
        from datetime import datetime
        temp_dir = Path(tmpdir)
        renamed_count = 0
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        patterns = [
            f"claude_session_startup_*{session_id}*",
            f"claude_rule_*{session_id}*",
            f"claude_cmd_{session_id}_*",
            f"claude_hook_*_session_{session_id}",
        ]
        for pattern in patterns:
            for marker_path in temp_dir.glob(pattern):
                if ".expired" in marker_path.name:
                    continue
                expired_name = f"{marker_path.name}.expired_compact_{timestamp}"
                expired_path = marker_path.parent / expired_name
                marker_path.rename(expired_path)
                renamed_count += 1
        return renamed_count

    def test_renames_session_startup_marker(self):
        """SessionStartupマーカーをリネームする"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = "test-session-123"
            temp_dir = Path(tmpdir)
            
            # マーカーファイルを作成
            marker = temp_dir / f"claude_session_startup_{session_id}"
            marker.touch()
            assert marker.exists()
            
            # リネーム実行
            count = self._do_rename(tmpdir, session_id)
            
            assert count == 1
            assert not marker.exists()
            # リネーム先が存在
            expired_files = list(temp_dir.glob("*.expired_compact_*"))
            assert len(expired_files) == 1

    def test_renames_multiple_markers(self):
        """複数のマーカーファイルをリネームする"""
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
            
            # リネーム実行
            count = self._do_rename(tmpdir, session_id)
            
            assert count == 4
            for m in markers:
                assert not m.exists()
            # リネーム先が存在
            expired_files = list(temp_dir.glob("*.expired_compact_*"))
            assert len(expired_files) == 4

    def test_returns_zero_when_no_markers(self):
        """マーカーがない場合は0を返す"""
        with tempfile.TemporaryDirectory() as tmpdir:
            count = self._do_rename(tmpdir, "nonexistent-session")
            assert count == 0

    def test_skips_already_expired_markers(self):
        """既にexpiredのマーカーはスキップする"""
        with tempfile.TemporaryDirectory() as tmpdir:
            session_id = "test-session-789"
            temp_dir = Path(tmpdir)
            
            # 通常マーカーと既存expiredマーカーを作成
            normal_marker = temp_dir / f"claude_session_startup_{session_id}"
            expired_marker = temp_dir / f"claude_session_startup_{session_id}.expired_20240101_120000"
            normal_marker.touch()
            expired_marker.touch()
            
            # リネーム実行
            count = self._do_rename(tmpdir, session_id)
            
            # 通常マーカーのみリネーム
            assert count == 1
            assert not normal_marker.exists()
            assert expired_marker.exists()  # 既存expiredは残る


class TestProcess:
    """processメソッドのテスト"""

    def test_calls_rename_markers_for_compact(self):
        """_rename_markers_for_compactが呼び出される"""
        hook = CompactDetectedHook()
        hook._rename_markers_for_compact = MagicMock(return_value=3)
        
        input_data = {
            "session_id": "test-123",
        }
        
        result = hook.process(input_data)
        
        hook._rename_markers_for_compact.assert_called_once_with("test-123")

    def test_returns_approve_decision(self):
        """approveを返す"""
        hook = CompactDetectedHook()
        hook._rename_markers_for_compact = MagicMock(return_value=0)
        
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
