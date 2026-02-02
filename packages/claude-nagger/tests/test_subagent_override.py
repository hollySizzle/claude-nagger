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
        # #5827/#5828: 新規フィールドのデフォルト値
        assert data["role"] is None
        assert data["startup_processed"] is False
        assert data["startup_processed_at"] is None

    def test_create_marker_new_fields(self, tmp_marker_dir):
        """マーカー作成時にrole, startup_processed, startup_processed_atが含まれる"""
        mgr = self._make_manager()
        mgr.create_marker("agent-new", "Bash")
        marker_path = tmp_marker_dir / "test-session-123" / "subagents" / "agent-new.json"
        data = json.loads(marker_path.read_text())
        assert "role" in data
        assert "startup_processed" in data
        assert "startup_processed_at" in data

    def test_update_marker_role(self, tmp_marker_dir):
        """update_markerでroleを設定できる"""
        mgr = self._make_manager()
        mgr.create_marker("agent-abc", "general-purpose")
        mgr.update_marker("agent-abc", role="coder")
        marker_path = tmp_marker_dir / "test-session-123" / "subagents" / "agent-abc.json"
        data = json.loads(marker_path.read_text())
        assert data["role"] == "coder"
        # 他のフィールドは変更されない
        assert data["agent_type"] == "general-purpose"
        assert data["startup_processed"] is False

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

    def test_resolve_namespaced_agent_type_matches_short_key(self):
        """名前空間付きagent_type（例: my-plugin:coder）が短いキーにマッチ"""
        config = {
            "enabled": True,
            "messages": {
                "first_time": {"title": "base", "main_text": "base text"},
            },
            "overrides": {
                "subagent_default": {
                    "messages": {"first_time": {"title": "subagent default"}}
                },
                "subagent_types": {
                    "coder": {
                        "messages": {
                            "first_time": {
                                "title": "coder規約",
                                "main_text": "[ ] スコープ外編集禁止",
                            }
                        }
                    },
                },
            },
        }
        hook = self._make_hook(config)
        resolved = hook._resolve_subagent_config("my-plugin:coder")

        assert resolved["messages"]["first_time"]["title"] == "coder規約"
        assert resolved["messages"]["first_time"]["main_text"] == "[ ] スコープ外編集禁止"

    def test_resolve_exact_match_takes_priority_over_short_name(self):
        """完全一致が部分一致（短いキー）より優先される"""
        config = {
            "enabled": True,
            "messages": {
                "first_time": {"title": "base", "main_text": "base text"},
            },
            "overrides": {
                "subagent_default": {},
                "subagent_types": {
                    "my-plugin:coder": {
                        "messages": {
                            "first_time": {"title": "完全一致の規約"}
                        }
                    },
                    "coder": {
                        "messages": {
                            "first_time": {"title": "短いキーの規約"}
                        }
                    },
                },
            },
        }
        hook = self._make_hook(config)
        resolved = hook._resolve_subagent_config("my-plugin:coder")

        # 完全一致が優先される
        assert resolved["messages"]["first_time"]["title"] == "完全一致の規約"

    def test_resolve_plain_agent_type_still_works(self):
        """":"を含まない従来のagent_typeが引き続き動作する"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("Bash")

        assert resolved["messages"]["first_time"]["title"] == "Bash subagent規約"
        assert resolved["messages"]["first_time"]["main_text"] == "[ ] 破壊的コマンド禁止"

    def test_resolve_namespaced_no_match_falls_back_to_default(self):
        """名前空間付きだが短いキーもマッチしない場合はsubagent_defaultにフォールバック"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("my-plugin:unknown-type")

        # subagent_defaultのメッセージが使われる
        assert resolved["messages"]["first_time"]["title"] == "subagent規約"

    def test_resolve_role_takes_priority(self):
        """roleがsubagent_typesにマッチする場合、agent_typeより優先"""
        hook = self._make_hook()
        # role="Bash"でBash用設定を取得、agent_typeは"general-purpose"
        resolved = hook._resolve_subagent_config("general-purpose", role="Bash")

        assert resolved["messages"]["first_time"]["title"] == "Bash subagent規約"
        assert resolved["messages"]["first_time"]["main_text"] == "[ ] 破壊的コマンド禁止"

    def test_resolve_role_no_match_falls_back_to_agent_type(self):
        """roleがsubagent_typesに無い場合はagent_typeで解決"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("Bash", role="nonexistent-role")

        assert resolved["messages"]["first_time"]["title"] == "Bash subagent規約"

    def test_resolve_role_none_uses_agent_type(self):
        """role=Noneの場合は従来通りagent_typeで解決"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("Bash", role=None)

        assert resolved["messages"]["first_time"]["title"] == "Bash subagent規約"

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
            "role": None,
            "startup_processed": False,
            "startup_processed_at": None,
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            mock_instance.is_startup_processed.return_value = False
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
            "role": None,
            "startup_processed": True,
            "startup_processed_at": "2026-01-27T00:01:00",
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            mock_instance.is_startup_processed.return_value = True
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
        mock_mgr = MagicMock()
        mock_mgr.update_marker.return_value = True
        hook._subagent_marker_manager = mock_mgr

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
        mock_mgr = MagicMock()
        mock_mgr.update_marker.return_value = True
        hook._subagent_marker_manager = mock_mgr

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

    def test_subagent_updates_lifecycle_marker(self):
        """subagent処理時はライフサイクルマーカーのstartup_processedを更新"""
        hook = self._make_hook()
        hook._is_subagent = True
        hook._current_agent_id = "agent-abc"
        hook._current_agent_type = "general-purpose"
        hook._resolved_config = hook._resolve_subagent_config("general-purpose")
        mock_mgr = MagicMock()
        mock_mgr.update_marker.return_value = True
        hook._subagent_marker_manager = mock_mgr

        hook.process({"session_id": "test-session"})

        mock_mgr.update_marker.assert_called_once()
        call_kwargs = mock_mgr.update_marker.call_args
        assert call_kwargs[0][0] == "agent-abc"
        assert call_kwargs[1]["startup_processed"] is True
        assert "startup_processed_at" in call_kwargs[1]

    def test_main_agent_creates_main_marker(self):
        """main agent処理時は従来のマーカーを作成"""
        hook = self._make_hook()
        hook._is_subagent = False
        hook._resolved_config = None

        with patch.object(hook, 'mark_session_startup_processed', return_value=True) as mock_mark:
            with patch.object(hook, '_get_execution_count', return_value=1):
                hook.process({"session_id": "test-session"})

        mock_mark.assert_called_once()


class TestSubagentStartupMarkerUnified:
    """統一マーカーによるstartup処理済み判定のテスト"""

    @pytest.fixture
    def tmp_marker_dir(self, tmp_path):
        session_id = "test-session"
        with patch.object(SubagentMarkerManager, 'BASE_DIR', tmp_path):
            mgr = SubagentMarkerManager(session_id)
        return mgr

    def test_is_startup_processed_default_false(self, tmp_marker_dir):
        """作成直後のマーカーはstartup_processed=False"""
        mgr = tmp_marker_dir
        mgr.create_marker("a1", "Bash")
        assert mgr.is_startup_processed("a1") is False

    def test_update_marker_sets_startup_processed(self, tmp_marker_dir):
        """update_markerでstartup_processedをTrueに更新"""
        mgr = tmp_marker_dir
        mgr.create_marker("a1", "Bash")
        mgr.update_marker("a1", startup_processed=True, startup_processed_at="2026-01-27T00:00:00")
        assert mgr.is_startup_processed("a1") is True

    def test_different_agents_independent(self, tmp_marker_dir):
        """異なるagent_idのstartup_processedは独立"""
        mgr = tmp_marker_dir
        mgr.create_marker("a1", "Bash")
        mgr.create_marker("a2", "Explore")
        mgr.update_marker("a1", startup_processed=True)
        assert mgr.is_startup_processed("a1") is True
        assert mgr.is_startup_processed("a2") is False

    def test_is_startup_processed_nonexistent_marker(self, tmp_marker_dir):
        """存在しないマーカーはFalse"""
        mgr = tmp_marker_dir
        assert mgr.is_startup_processed("nonexistent") is False

    def test_update_nonexistent_marker_returns_false(self, tmp_marker_dir):
        """存在しないマーカーの更新はFalse"""
        mgr = tmp_marker_dir
        assert mgr.update_marker("nonexistent", startup_processed=True) is False


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
            # 初期状態: startup未処理
            assert mgr.is_startup_processed(agent_id) is False

        # Step 2: PreToolUse → SessionStartupHook発火
        with patch.object(SessionStartupHook, '_load_config', return_value=self.CONFIG):
            hook = SessionStartupHook()
            input_data = {"session_id": session_id, "tool_name": "Read"}

            marker_data = {
                "agent_id": agent_id,
                "agent_type": agent_type,
                "session_id": session_id,
                "created_at": "2026-01-27T00:00:00",
                "role": None,
                "startup_processed": False,
                "startup_processed_at": None,
            }

            # SubagentMarkerManagerをモック
            with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
                MockMgr.BASE_DIR = tmp_path
                mock_instance = MockMgr.return_value
                mock_instance.is_subagent_active.return_value = True
                mock_instance.get_active_subagent.return_value = marker_data
                mock_instance.is_startup_processed.return_value = False
                mock_instance.update_marker.return_value = True

                # should_process: subagent検出 → True
                result = hook.should_process(input_data)
                assert result is True
                assert hook._is_subagent is True
                assert hook._current_agent_type == agent_type

                # process: subagent用メッセージでblock + update_marker呼び出し
                process_result = hook.process(input_data)
                assert process_result["decision"] == "block"
                assert "subagent規約" in process_result["reason"]
                mock_instance.update_marker.assert_called_once()

                # 2回目のPreToolUse → startup_processed=Trueで処理済みスキップ
                mock_instance.is_startup_processed.return_value = True
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


# ============================================================
# ROLE prefix トランスクリプト解析テスト (#5829)
# ============================================================

class TestParseRoleFromTranscript:
    """_parse_role_from_transcript のユニットテスト"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def _write_transcript(self, tmp_path, lines):
        """JSONL形式のトランスクリプトファイルを作成"""
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w', encoding='utf-8') as f:
            for entry in lines:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        return str(transcript)

    def test_basic_role_extraction(self, tmp_path):
        """基本的な[ROLE:xxx]抽出"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": "[ROLE:coder]\nPlease fix the bug."}},
        ])
        assert hook._parse_role_from_transcript(path) == "coder"

    def test_role_in_list_content(self, tmp_path):
        """contentがリスト形式の場合"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": [
                {"type": "text", "text": "[ROLE:reviewer]\nReview this PR."},
            ]}},
        ])
        assert hook._parse_role_from_transcript(path) == "reviewer"

    def test_no_role_returns_none(self, tmp_path):
        """[ROLE:xxx]がない場合はNone"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": "Just a normal message."}},
        ])
        assert hook._parse_role_from_transcript(path) is None

    def test_only_first_user_message_checked(self, tmp_path):
        """最初のuserメッセージのみ検索"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": "No role here."}},
            {"type": "user", "message": {"content": "[ROLE:tester]\nThis should be ignored."}},
        ])
        assert hook._parse_role_from_transcript(path) is None

    def test_skips_non_user_entries(self, tmp_path):
        """user以外のエントリはスキップ"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "assistant", "message": {"content": "[ROLE:fake]\nNot a user."}},
            {"type": "user", "message": {"content": "[ROLE:planner]\nPlan the work."}},
        ])
        assert hook._parse_role_from_transcript(path) == "planner"

    def test_none_transcript_path(self):
        """transcript_pathがNoneの場合"""
        hook = self._make_hook()
        assert hook._parse_role_from_transcript(None) is None

    def test_nonexistent_file(self):
        """存在しないファイルパスの場合"""
        hook = self._make_hook()
        assert hook._parse_role_from_transcript("/nonexistent/path.jsonl") is None

    def test_malformed_json_lines(self, tmp_path):
        """不正なJSONL行はスキップ"""
        hook = self._make_hook()
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write("not valid json\n")
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:debug]\nOK"}}) + '\n')
        assert hook._parse_role_from_transcript(str(transcript)) == "debug"

    def test_empty_file(self, tmp_path):
        """空ファイルの場合"""
        hook = self._make_hook()
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")
        assert hook._parse_role_from_transcript(str(transcript)) is None

    def test_content_string_list_mixed(self, tmp_path):
        """contentリスト内に文字列要素が混在する場合"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": ["[ROLE:ops]\nDo the thing."]}},
        ])
        assert hook._parse_role_from_transcript(path) == "ops"


class TestShouldProcessRoleParsing:
    """should_processでのROLE解析統合テスト"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_role_parsed_and_stored_in_marker(self, tmp_path):
        """transcript解析でroleがマーカーに保存される"""
        hook = self._make_hook()

        # トランスクリプトファイル作成
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:coder]\nFix bug."}}) + '\n')

        marker_data = {
            "agent_id": "agent-role-test",
            "agent_type": "general-purpose",
            "session_id": "test-session",
            "created_at": "2026-01-27T00:00:00",
            "role": None,
            "startup_processed": False,
            "startup_processed_at": None,
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            mock_instance.is_startup_processed.return_value = False

            result = hook.should_process({
                "session_id": "test-session",
                "transcript_path": str(transcript),
            })

        assert result is True
        # update_markerがrole=coderで呼ばれたことを確認
        mock_instance.update_marker.assert_called_once_with("agent-role-test", role="coder")

    def test_existing_role_not_overwritten(self, tmp_path):
        """マーカーに既存roleがある場合はtranscript解析しない"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:reviewer]\nReview."}}) + '\n')

        marker_data = {
            "agent_id": "agent-existing-role",
            "agent_type": "general-purpose",
            "session_id": "test-session",
            "created_at": "2026-01-27T00:00:00",
            "role": "coder",  # 既にroleがある
            "startup_processed": False,
            "startup_processed_at": None,
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            mock_instance.is_startup_processed.return_value = False

            result = hook.should_process({
                "session_id": "test-session",
                "transcript_path": str(transcript),
            })

        assert result is True
        # update_markerはroleで呼ばれない（roleが既にある）
        mock_instance.update_marker.assert_not_called()

    def test_no_role_in_transcript_no_update(self, tmp_path):
        """transcriptにROLEがない場合はupdate_marker呼ばれない"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "No role here."}}) + '\n')

        marker_data = {
            "agent_id": "agent-no-role",
            "agent_type": "general-purpose",
            "session_id": "test-session",
            "created_at": "2026-01-27T00:00:00",
            "role": None,
            "startup_processed": False,
            "startup_processed_at": None,
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            mock_instance.is_startup_processed.return_value = False

            result = hook.should_process({
                "session_id": "test-session",
                "transcript_path": str(transcript),
            })

        assert result is True
        mock_instance.update_marker.assert_not_called()

    def test_role_passed_to_resolve_subagent_config(self, tmp_path):
        """解析されたroleが_resolve_subagent_configに渡される"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:coder]\nWork."}}) + '\n')

        marker_data = {
            "agent_id": "agent-resolve-test",
            "agent_type": "general-purpose",
            "session_id": "test-session",
            "created_at": "2026-01-27T00:00:00",
            "role": None,
            "startup_processed": False,
            "startup_processed_at": None,
        }

        with patch('src.domain.hooks.session_startup_hook.SubagentMarkerManager') as MockMgr:
            mock_instance = MockMgr.return_value
            mock_instance.is_subagent_active.return_value = True
            mock_instance.get_active_subagent.return_value = marker_data
            mock_instance.is_startup_processed.return_value = False

            with patch.object(hook, '_resolve_subagent_config', return_value={"enabled": True, "messages": {}, "behavior": {}}) as mock_resolve:
                hook.should_process({
                    "session_id": "test-session",
                    "transcript_path": str(transcript),
                })

            # roleがresolve_subagent_configに渡される
            mock_resolve.assert_called_once_with("general-purpose", role="coder")
