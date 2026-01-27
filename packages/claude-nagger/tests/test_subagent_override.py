"""subagent override機構のテスト

#5620: SessionStartup hookのsub-agent別override機構
- SubagentMarkerManager: マーカーCRUD、並行subagent対応、クリーンアップ
- config.yaml overrides: 解決順序（base → subagent_default → subagent_types）、enabled: false
- SessionStartupHook: main agent時は従来通り、subagent時はoverridesメッセージ
- SubagentEventHook: マーカー作成・削除
- 統合: SubagentStart → PreToolUse（subagent用メッセージ） → SubagentStop
"""

import io
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.services.subagent_marker_manager import SubagentMarkerManager
from src.domain.hooks.session_startup_hook import (
    SessionStartupHook,
    _deep_copy_dict,
    _deep_merge,
)
from src.domain.hooks.subagent_event_hook import main as subagent_event_main


# ============================================================
# ヘルパー関数テスト
# ============================================================

class TestDeepCopyDict:
    """_deep_copy_dict のテスト"""

    def test_shallow_dict(self):
        """フラットな辞書のコピー"""
        d = {"a": 1, "b": "x"}
        result = _deep_copy_dict(d)
        assert result == d
        assert result is not d

    def test_nested_dict(self):
        """ネストされた辞書のコピー"""
        d = {"a": {"b": {"c": 1}}}
        result = _deep_copy_dict(d)
        assert result == d
        assert result["a"] is not d["a"]
        assert result["a"]["b"] is not d["a"]["b"]

    def test_empty_dict(self):
        """空辞書のコピー"""
        assert _deep_copy_dict({}) == {}

    def test_dict_with_list(self):
        """リスト値を含む辞書の深いコピー"""
        d = {"a": [1, 2, {"b": 3}]}
        result = _deep_copy_dict(d)
        assert result == d
        assert result["a"] is not d["a"]
        assert result["a"][2] is not d["a"][2]

    def test_dict_with_nested_list(self):
        """ネストされたリスト値の深いコピー"""
        d = {"items": [{"name": "x"}, {"name": "y"}]}
        result = _deep_copy_dict(d)
        result["items"][0]["name"] = "modified"
        assert d["items"][0]["name"] == "x"  # 元データに影響しない


class TestDeepMerge:
    """_deep_merge のテスト"""

    def test_simple_override(self):
        """単純な値の上書き"""
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        _deep_merge(base, override)
        assert base == {"a": 1, "b": 3}

    def test_nested_merge(self):
        """ネストされた辞書のマージ"""
        base = {"messages": {"first_time": {"title": "base", "main_text": "base text"}}}
        override = {"messages": {"first_time": {"title": "override"}}}
        _deep_merge(base, override)
        assert base["messages"]["first_time"]["title"] == "override"
        assert base["messages"]["first_time"]["main_text"] == "base text"

    def test_add_new_key(self):
        """新しいキーの追加"""
        base = {"a": 1}
        override = {"b": 2}
        _deep_merge(base, override)
        assert base == {"a": 1, "b": 2}

    def test_override_non_dict_with_dict(self):
        """非辞書値を辞書で上書き"""
        base = {"a": "string"}
        override = {"a": {"nested": True}}
        _deep_merge(base, override)
        assert base["a"] == {"nested": True}

    def test_empty_override(self):
        """空のoverrideはbaseを変更しない"""
        base = {"a": 1}
        _deep_merge(base, {})
        assert base == {"a": 1}


# ============================================================
# SubagentMarkerManager テスト
# ============================================================

class TestSubagentMarkerManager:
    """SubagentMarkerManagerのテスト"""

    @pytest.fixture
    def tmp_marker_dir(self, tmp_path):
        """テスト用の一時マーカーディレクトリ"""
        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            yield tmp_path

    def _make_manager(self, session_id="test-session-123"):
        return SubagentMarkerManager(session_id)

    def test_create_marker(self, tmp_marker_dir):
        """マーカー作成の基本動作"""
        mgr = self._make_manager()
        result = mgr.create_marker("agent-abc", "general-purpose")

        assert result is True
        marker_path = tmp_marker_dir / "test-session-123" / "subagents" / "agent-abc.json"
        assert marker_path.exists()

        data = json.loads(marker_path.read_text())
        assert data["agent_id"] == "agent-abc"
        assert data["agent_type"] == "general-purpose"
        assert data["session_id"] == "test-session-123"
        assert "created_at" in data

    def test_delete_marker(self, tmp_marker_dir):
        """マーカー削除の基本動作"""
        mgr = self._make_manager()
        mgr.create_marker("agent-abc", "Bash")
        assert mgr.is_subagent_active()

        result = mgr.delete_marker("agent-abc")
        assert result is True
        assert not mgr.is_subagent_active()

    def test_delete_nonexistent_marker(self, tmp_marker_dir):
        """存在しないマーカーの削除は冪等（True）"""
        mgr = self._make_manager()
        result = mgr.delete_marker("nonexistent")
        assert result is True

    def test_is_subagent_active(self, tmp_marker_dir):
        """subagentアクティブ判定"""
        mgr = self._make_manager()
        assert mgr.is_subagent_active() is False

        mgr.create_marker("agent-1", "Explore")
        assert mgr.is_subagent_active() is True

    def test_get_active_subagent(self, tmp_marker_dir):
        """最新のアクティブsubagent取得"""
        mgr = self._make_manager()
        assert mgr.get_active_subagent() is None

        mgr.create_marker("agent-1", "Explore")
        active = mgr.get_active_subagent()
        assert active is not None
        assert active["agent_id"] == "agent-1"
        assert active["agent_type"] == "Explore"

    def test_concurrent_subagents(self, tmp_marker_dir):
        """並行subagent対応"""
        mgr = self._make_manager()
        mgr.create_marker("agent-1", "Explore")
        mgr.create_marker("agent-2", "Bash")
        mgr.create_marker("agent-3", "Plan")

        assert mgr.get_active_count() == 3
        assert mgr.is_subagent_active() is True

        all_active = mgr.get_all_active_subagents()
        types = {a["agent_type"] for a in all_active}
        assert types == {"Explore", "Bash", "Plan"}

    def test_partial_deletion(self, tmp_marker_dir):
        """一部のsubagent削除後もアクティブ判定が正しい"""
        mgr = self._make_manager()
        mgr.create_marker("agent-1", "Explore")
        mgr.create_marker("agent-2", "Bash")

        mgr.delete_marker("agent-1")
        assert mgr.get_active_count() == 1
        active = mgr.get_active_subagent()
        assert active["agent_type"] == "Bash"

    def test_cleanup(self, tmp_marker_dir):
        """全マーカーのクリーンアップ"""
        mgr = self._make_manager()
        mgr.create_marker("agent-1", "Explore")
        mgr.create_marker("agent-2", "Bash")

        count = mgr.cleanup()
        assert count == 2
        assert mgr.get_active_count() == 0

    def test_cleanup_empty(self, tmp_marker_dir):
        """空の状態でのクリーンアップ"""
        mgr = self._make_manager()
        count = mgr.cleanup()
        assert count == 0


# ============================================================
# SessionStartupHook subagent override テスト
# ============================================================

class TestSessionStartupHookSubagentOverride:
    """SessionStartupHookのsubagent override機構テスト"""

    BASE_CONFIG = {
        "enabled": True,
        "messages": {
            "first_time": {
                "title": "プロジェクト規約",
                "main_text": "[ ] テスト必須",
            },
            "repeated": {
                "title": "継続確認",
                "main_text": "[ ] テスト必須（再確認）",
            },
        },
        "behavior": {"once_per_session": True},
        "overrides": {
            "subagent_default": {
                "messages": {
                    "first_time": {
                        "title": "subagent規約",
                        "main_text": "[ ] スコープ外編集禁止",
                    }
                }
            },
            "subagent_types": {
                "Explore": {"enabled": False},
                "Bash": {
                    "messages": {
                        "first_time": {
                            "title": "Bash subagent規約",
                            "main_text": "[ ] 破壊的コマンド禁止",
                        }
                    }
                },
                "Plan": {"enabled": False},
            },
        },
    }

    def _make_hook(self, config=None):
        """テスト用hookインスタンス生成"""
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_resolve_subagent_config_default(self):
        """未定義subagent_typeはsubagent_defaultにフォールバック"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("general-purpose")

        assert resolved["enabled"] is True
        assert resolved["messages"]["first_time"]["title"] == "subagent規約"
        assert resolved["messages"]["first_time"]["main_text"] == "[ ] スコープ外編集禁止"

    def test_resolve_subagent_config_type_specific(self):
        """subagent_typesの設定がsubagent_defaultを上書き"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("Bash")

        assert resolved["enabled"] is True
        assert resolved["messages"]["first_time"]["title"] == "Bash subagent規約"
        assert resolved["messages"]["first_time"]["main_text"] == "[ ] 破壊的コマンド禁止"

    def test_resolve_subagent_config_disabled(self):
        """enabled: falseの解決"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("Explore")
        assert resolved["enabled"] is False

    def test_resolve_subagent_config_no_overrides(self):
        """overridesセクションなしはbase設定を返す"""
        config = {
            "enabled": True,
            "messages": {"first_time": {"title": "base", "main_text": "base text"}},
        }
        hook = self._make_hook(config)
        resolved = hook._resolve_subagent_config("general-purpose")

        assert resolved["messages"]["first_time"]["title"] == "base"

    def test_is_session_processed_context_aware_always_false(self):
        """BaseHookのセッションチェックを常にバイパス"""
        hook = self._make_hook()
        result = hook.is_session_processed_context_aware("session-123", {})
        assert result is False


class TestSessionStartupHookShouldProcessSubagent:
    """should_processのsubagent検出テスト"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_subagent_detected_new(self):
        """新規subagent検出時はTrue"""
        hook = self._make_hook()
        marker_data = {
            "agent_id": "agent-abc",
            "agent_type": "general-purpose",
            "session_id": "test-session",
            "created_at": "2026-01-27T00:00:00",
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            with patch.object(hook, '_is_subagent_startup_processed', return_value=False):
                result = hook.should_process({"session_id": "test-session"})

        assert result is True
        assert hook._is_subagent is True
        assert hook._current_agent_type == "general-purpose"
        assert hook._current_agent_id == "agent-abc"

    def test_subagent_already_processed(self):
        """処理済みsubagentはFalse"""
        hook = self._make_hook()
        marker_data = {
            "agent_id": "agent-abc",
            "agent_type": "general-purpose",
            "session_id": "test-session",
            "created_at": "2026-01-27T00:00:00",
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            with patch.object(hook, '_is_subagent_startup_processed', return_value=True):
                result = hook.should_process({"session_id": "test-session"})

        assert result is False

    def test_subagent_disabled_type(self):
        """enabled: falseのsubagent種別はFalse"""
        hook = self._make_hook()
        marker_data = {
            "agent_id": "agent-xyz",
            "agent_type": "Explore",
            "session_id": "test-session",
            "created_at": "2026-01-27T00:00:00",
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            result = hook.should_process({"session_id": "test-session"})

        assert result is False

    def test_no_subagent_main_agent_flow(self):
        """subagentなしの場合はmain agentフロー"""
        hook = self._make_hook()

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = False
            with patch.object(hook, 'is_session_startup_processed', return_value=False):
                result = hook.should_process({"session_id": "new-session"})

        assert result is True
        assert hook._is_subagent is False


class TestSessionStartupHookProcessSubagent:
    """processのsubagent override テスト"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_subagent_message_uses_override(self):
        """subagent時はoverride設定のメッセージを使用"""
        hook = self._make_hook()
        hook._is_subagent = True
        hook._current_agent_id = "agent-abc"
        hook._current_agent_type = "general-purpose"
        hook._resolved_config = hook._resolve_subagent_config("general-purpose")

        with patch.object(hook, '_mark_subagent_startup_processed', return_value=True):
            result = hook.process({"session_id": "test-session"})

        assert result["decision"] == "block"
        assert "subagent規約" in result["reason"]
        assert "スコープ外編集禁止" in result["reason"]

    def test_bash_subagent_message(self):
        """Bash subagentは種別固有メッセージを使用"""
        hook = self._make_hook()
        hook._is_subagent = True
        hook._current_agent_id = "agent-bash"
        hook._current_agent_type = "Bash"
        hook._resolved_config = hook._resolve_subagent_config("Bash")

        with patch.object(hook, '_mark_subagent_startup_processed', return_value=True):
            result = hook.process({"session_id": "test-session"})

        assert "Bash subagent規約" in result["reason"]
        assert "破壊的コマンド禁止" in result["reason"]

    def test_main_agent_message_unchanged(self):
        """main agent時は従来のメッセージ"""
        hook = self._make_hook()
        hook._is_subagent = False
        hook._resolved_config = None

        with patch.object(hook, 'mark_session_startup_processed', return_value=True):
            with patch.object(hook, '_get_execution_count', return_value=1):
                result = hook.process({"session_id": "test-session"})

        assert result["decision"] == "block"
        assert "プロジェクト規約" in result["reason"]

    def test_subagent_creates_subagent_marker(self):
        """subagent処理時はsubagent別マーカーを作成"""
        hook = self._make_hook()
        hook._is_subagent = True
        hook._current_agent_id = "agent-abc"
        hook._current_agent_type = "general-purpose"
        hook._resolved_config = hook._resolve_subagent_config("general-purpose")

        with patch.object(hook, '_mark_subagent_startup_processed', return_value=True) as mock_mark:
            hook.process({"session_id": "test-session"})

        mock_mark.assert_called_once_with("test-session", "agent-abc", "general-purpose")

    def test_main_agent_creates_main_marker(self):
        """main agent処理時は従来のマーカーを作成"""
        hook = self._make_hook()
        hook._is_subagent = False
        hook._resolved_config = None

        with patch.object(hook, 'mark_session_startup_processed', return_value=True) as mock_mark:
            with patch.object(hook, '_get_execution_count', return_value=1):
                hook.process({"session_id": "test-session"})

        mock_mark.assert_called_once()


class TestSubagentStartupMarker:
    """subagent startup マーカーのテスト"""

    def _make_hook(self):
        with patch.object(SessionStartupHook, '_load_config', return_value={}):
            return SessionStartupHook()

    def test_subagent_marker_path(self, tmp_path):
        """subagentマーカーパスの形式確認"""
        hook = self._make_hook()
        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            MockMgr.BASE_DIR = tmp_path
            path = hook._get_subagent_startup_marker_path("session-123", "agent-abc")

        assert path == tmp_path / "session-123" / "startup" / "agent-abc.json"

    def test_mark_and_check_subagent(self, tmp_path):
        """subagentマーカー作成と確認"""
        hook = self._make_hook()
        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            MockMgr.BASE_DIR = tmp_path

            assert hook._is_subagent_startup_processed("s1", "a1") is False

            hook._mark_subagent_startup_processed("s1", "a1", "Bash")

            assert hook._is_subagent_startup_processed("s1", "a1") is True

    def test_different_agents_independent(self, tmp_path):
        """異なるagent_idのマーカーは独立"""
        hook = self._make_hook()
        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            MockMgr.BASE_DIR = tmp_path

            hook._mark_subagent_startup_processed("s1", "a1", "Bash")

            assert hook._is_subagent_startup_processed("s1", "a1") is True
            assert hook._is_subagent_startup_processed("s1", "a2") is False


# ============================================================
# SubagentEventHook テスト
# ============================================================

class TestSubagentEventHook:
    """SubagentEventHookのテスト（SubagentMarkerManager直接呼び出し確認）"""

    def test_subagent_start_creates_marker(self, tmp_path):
        """SubagentStartイベントでマーカーが作成される"""
        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            mgr = SubagentMarkerManager("session-123")
            mgr.create_marker("agent-abc", "general-purpose")

            assert mgr.is_subagent_active()
            active = mgr.get_active_subagent()
            assert active["agent_id"] == "agent-abc"
            assert active["agent_type"] == "general-purpose"

    def test_subagent_stop_deletes_marker(self, tmp_path):
        """SubagentStopイベントでマーカーが削除される"""
        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            mgr = SubagentMarkerManager("session-123")
            mgr.create_marker("agent-abc", "general-purpose")
            assert mgr.is_subagent_active()

            mgr.delete_marker("agent-abc")
            assert not mgr.is_subagent_active()


class TestSubagentEventHookMain:
    """SubagentEventHook main()のstdin mock経由テスト（#5631）"""

    def _run_main_with_stdin(self, input_data):
        """stdin経由でmain()を実行するヘルパー。SystemExit例外をキャッチ。"""
        stdin_text = json.dumps(input_data) if isinstance(input_data, dict) else input_data
        with patch('sys.stdin', io.StringIO(stdin_text)):
            with pytest.raises(SystemExit) as exc_info:
                subagent_event_main()
        return exc_info.value.code

    def test_start_event_calls_create_marker(self):
        """SubagentStartイベントでcreate_markerが呼ばれる"""
        input_data = {
            "hook_event_name": "SubagentStart",
            "session_id": "session-123",
            "agent_id": "agent-abc",
            "agent_type": "general-purpose",
        }
        with patch('src.domain.hooks.subagent_event_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        MockMgr.assert_called_once_with("session-123")
        mock_instance.create_marker.assert_called_once_with("agent-abc", "general-purpose")
        mock_instance.delete_marker.assert_not_called()

    def test_stop_event_calls_delete_marker(self):
        """SubagentStopイベントでdelete_markerが呼ばれる"""
        input_data = {
            "hook_event_name": "SubagentStop",
            "session_id": "session-123",
            "agent_id": "agent-abc",
        }
        with patch('src.domain.hooks.subagent_event_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        MockMgr.assert_called_once_with("session-123")
        mock_instance.delete_marker.assert_called_once_with("agent-abc")
        mock_instance.create_marker.assert_not_called()

    def test_invalid_json_exits_cleanly(self):
        """不正JSONは正常終了（exit 0）"""
        exit_code = self._run_main_with_stdin("{invalid json!!!")

        # create_marker/delete_markerは呼ばれない（JSONDecodeErrorでexit）
        assert exit_code == 0

    def test_empty_stdin_exits_cleanly(self):
        """空stdinは正常終了（exit 0）"""
        with patch('sys.stdin', io.StringIO("")):
            with pytest.raises(SystemExit) as exc_info:
                subagent_event_main()
        assert exc_info.value.code == 0

    def test_missing_session_id_exits_early(self):
        """session_id欠損は早期終了（マーカー操作なし）"""
        input_data = {
            "hook_event_name": "SubagentStart",
            "agent_id": "agent-abc",
            "agent_type": "general-purpose",
        }
        with patch('src.domain.hooks.subagent_event_hook.SubagentMarkerManager') as MockMgr:
            exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        MockMgr.assert_not_called()

    def test_missing_agent_id_exits_early(self):
        """agent_id欠損は早期終了（マーカー操作なし）"""
        input_data = {
            "hook_event_name": "SubagentStart",
            "session_id": "session-123",
            "agent_type": "general-purpose",
        }
        with patch('src.domain.hooks.subagent_event_hook.SubagentMarkerManager') as MockMgr:
            exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        MockMgr.assert_not_called()

    def test_unknown_event_no_marker_operation(self):
        """未知のイベント名ではマーカー操作なし"""
        input_data = {
            "hook_event_name": "UnknownEvent",
            "session_id": "session-123",
            "agent_id": "agent-abc",
        }
        with patch('src.domain.hooks.subagent_event_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        # SubagentMarkerManagerはインスタンス化されるがマーカー操作は無い
        MockMgr.assert_called_once_with("session-123")
        mock_instance.create_marker.assert_not_called()
        mock_instance.delete_marker.assert_not_called()

    def test_start_event_missing_agent_type_defaults_unknown(self):
        """agent_type欠損時は"unknown"がデフォルト"""
        input_data = {
            "hook_event_name": "SubagentStart",
            "session_id": "session-123",
            "agent_id": "agent-abc",
        }
        with patch('src.domain.hooks.subagent_event_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        mock_instance.create_marker.assert_called_once_with("agent-abc", "unknown")


# ============================================================
# 統合テスト
# ============================================================

class TestSubagentOverrideIntegration:
    """SubagentStart → PreToolUse → SubagentStop の統合テスト"""

    CONFIG = {
        "enabled": True,
        "messages": {
            "first_time": {
                "title": "プロジェクト規約",
                "main_text": "[ ] テスト必須",
            }
        },
        "behavior": {"once_per_session": True},
        "overrides": {
            "subagent_default": {
                "messages": {
                    "first_time": {
                        "title": "subagent規約",
                        "main_text": "[ ] スコープ外編集禁止",
                    }
                }
            },
            "subagent_types": {
                "Explore": {"enabled": False},
            },
        },
    }

    def test_full_flow_general_purpose(self, tmp_path):
        """一般subagentのフルフロー: Start→PreToolUse(block)→Stop"""
        session_id = "integration-session"
        agent_id = "agent-gp"
        agent_type = "general-purpose"

        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            # Step 1: SubagentStart → マーカー作成
            mgr = SubagentMarkerManager(session_id)
            mgr.create_marker(agent_id, agent_type)
            assert mgr.is_subagent_active()

        # Step 2: PreToolUse → SessionStartupHook発火
        with patch.object(SessionStartupHook, '_load_config', return_value=self.CONFIG):
            hook = SessionStartupHook()
            input_data = {"session_id": session_id, "tool_name": "Read"}

            # SubagentMarkerManagerをモック
            with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
                MockMgr.BASE_DIR = tmp_path
                mock_instance = MockMgr.return_value
                mock_instance.is_subagent_active.return_value = True
                mock_instance.get_active_subagent.return_value = {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "session_id": session_id,
                    "created_at": "2026-01-27T00:00:00",
                }

                # should_process: subagent検出 → True
                result = hook.should_process(input_data)
                assert result is True
                assert hook._is_subagent is True
                assert hook._current_agent_type == agent_type

                # process: subagent用メッセージでblock
                process_result = hook.process(input_data)
                assert process_result["decision"] == "block"
                assert "subagent規約" in process_result["reason"]

                # 2回目のPreToolUse → 処理済みでスキップ
                # マーカーが作成されたので、_is_subagent_startup_processedがTrueを返す
                result2 = hook.should_process(input_data)
                assert result2 is False

        # Step 3: SubagentStop → マーカー削除
        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            mgr2 = SubagentMarkerManager(session_id)
            mgr2.delete_marker(agent_id)
            assert not mgr2.is_subagent_active()

    def test_full_flow_explore_disabled(self, tmp_path):
        """Exploresubagentは無効化: Start→PreToolUse(skip)→Stop"""
        session_id = "integration-session"
        agent_id = "agent-explore"
        agent_type = "Explore"

        # SubagentStart
        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            mgr = SubagentMarkerManager(session_id)
            mgr.create_marker(agent_id, agent_type)

        # PreToolUse → should_processがFalse（disabled）
        with patch.object(SessionStartupHook, '_load_config', return_value=self.CONFIG):
            hook = SessionStartupHook()

            with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
                MockMgr.BASE_DIR = tmp_path
                mock_instance = MockMgr.return_value
                mock_instance.is_subagent_active.return_value = True
                mock_instance.get_active_subagent.return_value = {
                    "agent_id": agent_id,
                    "agent_type": agent_type,
                    "session_id": session_id,
                    "created_at": "2026-01-27T00:00:00",
                }

                result = hook.should_process({"session_id": session_id})
                assert result is False

        # SubagentStop
        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            mgr2 = SubagentMarkerManager(session_id)
            mgr2.delete_marker(agent_id)

    def test_main_agent_unaffected(self, tmp_path):
        """subagentがいない場合はmain agentの従来動作"""
        with patch.object(SessionStartupHook, '_load_config', return_value=self.CONFIG):
            hook = SessionStartupHook()

            with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
                mock_instance = MockMgr.return_value
                mock_instance.is_subagent_active.return_value = False

                with patch.object(hook, 'is_session_startup_processed', return_value=False):
                    result = hook.should_process({"session_id": "main-session"})

                assert result is True
                assert hook._is_subagent is False
