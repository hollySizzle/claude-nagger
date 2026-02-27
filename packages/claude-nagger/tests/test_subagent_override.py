"""subagent override機構のテスト（DB移行後）

#5620: SessionStartup hookのsub-agent別override機構
- SubagentRepository/SessionRepository: DB based state management
- config.yaml overrides: 解決順序（base → subagent_default → subagent_types）、enabled: false
- SessionStartupHook: main agent時は従来通り、subagent時はoverridesメッセージ
- SubagentEventHook: DB登録・削除
- 統合: SubagentStart → PreToolUse（subagent用メッセージ） → SubagentStop
"""

import io
import json
import yaml
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from src.domain.hooks.session_startup_hook import (
    SessionStartupHook,
    _deep_copy_dict,
    _deep_merge,
    _strip_numeric_suffix,
)
from src.domain.hooks.subagent_event_hook import main as subagent_event_main


def _load_real_config():
    """実config.yamlからsession_startup設定を読み込む"""
    config_path = Path(__file__).parent.parent / ".claude-nagger" / "config.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return data.get('session_startup', {})


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
# SessionStartupHook subagent override テスト（DBベース）
# ============================================================

class TestSessionStartupHookSubagentOverride:
    """SessionStartupHookのsubagent override機構テスト"""

    BASE_CONFIG = _load_real_config()

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
        assert "スコープ外のファイルを編集しないこと" in resolved["messages"]["first_time"]["main_text"]
        assert "作業完了後に結果を報告すること" in resolved["messages"]["first_time"]["main_text"]

    def test_resolve_subagent_config_type_specific(self):
        """subagent_typesの設定がsubagent_defaultを上書き"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("Bash")

        assert resolved["enabled"] is True
        assert resolved["messages"]["first_time"]["title"] == "Bash subagent規約"
        assert "破壊的コマンド禁止" in resolved["messages"]["first_time"]["main_text"]

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
        assert "破壊的コマンド禁止" in resolved["messages"]["first_time"]["main_text"]

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
        assert "破壊的コマンド禁止" in resolved["messages"]["first_time"]["main_text"]

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

    def test_resolve_conductor_role(self):
        """conductor roleがsubagent_typesに未定義の場合subagent_defaultにフォールバック"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("general-purpose", role="conductor")

        # conductorはsubagent_typesに未定義 → subagent_default
        assert resolved["messages"]["first_time"]["title"] == "subagent規約"

    def test_resolve_conductor_role_contains_default_rules(self):
        """conductor未定義時はsubagent_defaultの規約が含まれる"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("general-purpose", role="conductor")

        main_text = resolved["messages"]["first_time"]["main_text"]
        assert "作業完了後に結果を報告すること" in main_text
        assert "スコープ外のファイルを編集しないこと" in main_text

    def test_is_session_processed_context_aware_always_false(self):
        """BaseHookのセッションチェックを常にバイパス"""
        hook = self._make_hook()
        result = hook.is_session_processed_context_aware("session-123", {})
        assert result is False


class TestShouldSkipSessionBypass:
    """should_skip_sessionが常にFalseを返し、run()のセッションチェックをバイパスするテスト

    根拠: SessionStartupHookはshould_process()内に独自の重複排除ロジックを持つため、
    BaseHookのセッション処理済みチェックは常にバイパスする必要がある。
    SubagentStartはfire-and-forget(非同期)のため、マーカー依存の条件付きバイパスは
    レースコンディションを引き起こす(issue #5862)。

    リファクタリング(issue #5933): is_session_processed_context_awareオーバーライドから
    should_skip_sessionオーバーライドに移行。run()はshould_skip_session()を呼び出す。
    """

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_always_false_without_markers(self):
        """マーカーなし状態で常にFalse"""
        hook = self._make_hook()
        result = hook.should_skip_session("session-123", {})
        assert result is False

    def test_always_false_with_session_marker(self):
        """セッションマーカー存在時でもFalse（BaseHookのチェックをバイパス）"""
        hook = self._make_hook()
        # BaseHookのセッションマーカーを作成
        hook.mark_session_processed("session-with-marker", context_tokens=1000)
        try:
            # SessionStartupHookのshould_skip_sessionは常にFalse
            result = hook.should_skip_session("session-with-marker", {})
            assert result is False
        finally:
            # マーカー削除
            marker_path = hook.get_session_marker_path("session-with-marker")
            if marker_path.exists():
                marker_path.unlink()


class TestSessionStartupHookShouldProcessSubagent:
    """should_processのsubagent検出テスト（DBベース）"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_subagent_detected_new(self):
        """新規subagent検出時はTrue（DBベース）"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-abc"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({"session_id": "test-session"})

        assert result is True
        assert hook._is_subagent is True
        assert hook._current_agent_type == "general-purpose"
        assert hook._current_agent_id == "agent-abc"

    def test_subagent_already_processed(self):
        """処理済みsubagentはFalse（claim_next_unprocessedがNone）"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_subagent_repo.claim_next_unprocessed.return_value = None

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({"session_id": "test-session"})

        assert result is False

    def test_subagent_disabled_type(self):
        """enabled: falseのsubagent種別はFalse"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "Explore"
        mock_record.agent_id = "agent-xyz"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({"session_id": "test-session"})

        assert result is False

    def test_no_subagent_main_agent_flow(self):
        """subagentなしの場合はmain agentフロー"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = False
        mock_session_repo.is_processed_context_aware.return_value = False

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({"session_id": "new-session"})

        assert result is True
        assert hook._is_subagent is False

    def test_leader_transcript_skips_subagent_blocking(self):
        """issue_6952: leaderのtool_use_idがtranscriptに見つかる場合はsubagentブロッキングをスキップ"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-abc"
        mock_record.role = None
        mock_record.leader_transcript_path = "/home/user/.claude/projects/test/leader-session.jsonl"
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record
        # tool_use_idがleader transcriptに見つかる → leader判定
        mock_subagent_repo.is_leader_tool_use.return_value = True

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    # leaderのtool_use_id + transcript_path → スキップ
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": "/home/user/.claude/projects/test/leader-session.jsonl",
                        "tool_use_id": "toolu_LEADER_001",
                    })

        assert result is False
        mock_subagent_repo.is_leader_tool_use.assert_called_once_with(
            "/home/user/.claude/projects/test/leader-session.jsonl", "toolu_LEADER_001"
        )

    def test_subagent_transcript_triggers_blocking(self):
        """issue_6057: subagentのtranscript_pathはleaderと異なるためブロッキング発火"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        leader_transcript = "/home/user/.claude/projects/test/leader-session.jsonl"
        subagent_transcript = "/home/user/.claude/projects/test/subagent-session.jsonl"

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-abc"
        mock_record.role = "coder"
        mock_record.leader_transcript_path = leader_transcript
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    # subagent自身のtranscript_path → ブロッキング発火
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": subagent_transcript,
                    })

        assert result is True
        assert hook._is_subagent is True
        assert hook._current_agent_id == "agent-abc"

    def test_no_leader_transcript_path_allows_blocking(self):
        """leader_transcript_pathがNone（旧DB）の場合は従来通りブロッキング発火"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-abc"
        mock_record.role = None
        mock_record.leader_transcript_path = None  # 旧スキーマ互換
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": "/some/transcript.jsonl",
                    })

        assert result is True
        assert hook._is_subagent is True


class TestSessionStartupHookProcessSubagent:
    """processのsubagent override テスト（DBベース）"""

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
        hook._session_repo = MagicMock()
        hook._subagent_repo = MagicMock()

        result = hook.process({"session_id": "test-session"})

        assert result["decision"] == "block"
        assert "subagent規約" in result["reason"]
        assert "作業完了後に結果を報告すること" in result["reason"]
        # mark_processedが呼ばれたことを確認
        hook._subagent_repo.mark_processed.assert_called_once_with("agent-abc")

    def test_bash_subagent_message(self):
        """Bash subagentは種別固有メッセージを使用"""
        hook = self._make_hook()
        hook._is_subagent = True
        hook._current_agent_id = "agent-bash"
        hook._current_agent_type = "Bash"
        hook._resolved_config = hook._resolve_subagent_config("Bash")
        hook._session_repo = MagicMock()
        hook._subagent_repo = MagicMock()

        result = hook.process({"session_id": "test-session"})

        assert "Bash subagent規約" in result["reason"]
        assert "破壊的コマンド禁止" in result["reason"]

    def test_main_agent_message_unchanged(self):
        """main agent時は従来のメッセージ"""
        hook = self._make_hook()
        hook._is_subagent = False
        hook._resolved_config = None
        hook._session_repo = MagicMock()

        with patch.object(hook, '_get_execution_count', return_value=1):
            with patch.object(hook, '_get_current_context_size', return_value=0):
                result = hook.process({"session_id": "test-session"})

        assert result["decision"] == "block"
        assert "ticket-tasuki 協働規約" in result["reason"]

    def test_subagent_no_register_call(self):
        """subagent処理時はSessionRepository.registerが呼ばれない"""
        hook = self._make_hook()
        hook._is_subagent = True
        hook._current_agent_id = "agent-abc"
        hook._current_agent_type = "general-purpose"
        hook._resolved_config = hook._resolve_subagent_config("general-purpose")
        mock_session_repo = MagicMock()
        hook._session_repo = mock_session_repo
        mock_subagent_repo = MagicMock()
        hook._subagent_repo = mock_subagent_repo

        hook.process({"session_id": "test-session"})

        mock_session_repo.register.assert_not_called()
        # mark_processedが呼ばれたことを確認
        mock_subagent_repo.mark_processed.assert_called_once_with("agent-abc")

    def test_main_agent_creates_db_record(self):
        """main agent処理時はSessionRepository.registerが呼ばれる"""
        hook = self._make_hook()
        hook._is_subagent = False
        hook._resolved_config = None
        mock_session_repo = MagicMock()
        hook._session_repo = mock_session_repo

        with patch.object(hook, '_get_execution_count', return_value=1):
            with patch.object(hook, '_get_current_context_size', return_value=5000):
                hook.process({"session_id": "test-session"})

        mock_session_repo.register.assert_called_once_with("test-session", "SessionStartupHook", 5000)


# ============================================================
# SubagentEventHook テスト（DBベース）
# ============================================================

class TestSubagentEventHook:
    """SubagentEventHookのテスト（DBベース）"""

    def _run_main_with_stdin(self, input_data):
        """stdin経由でmain()を実行するヘルパー。SystemExit例外をキャッチ。"""
        stdin_text = json.dumps(input_data) if isinstance(input_data, dict) else input_data
        with patch('sys.stdin', io.StringIO(stdin_text)):
            with pytest.raises(SystemExit) as exc_info:
                subagent_event_main()
        return exc_info.value.code

    def test_start_event_calls_register(self):
        """SubagentStartイベントでSubagentRepository.registerが呼ばれる"""
        input_data = {
            "hook_event_name": "SubagentStart",
            "session_id": "session-123",
            "agent_id": "agent-abc",
            "agent_type": "general-purpose",
        }

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()

        with patch('src.domain.hooks.subagent_event_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.subagent_event_hook.SubagentRepository', return_value=mock_subagent_repo):
                exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        mock_subagent_repo.register.assert_called_once()

    def test_stop_event_calls_unregister(self):
        """SubagentStopイベントでSubagentRepository.unregisterが呼ばれる"""
        input_data = {
            "hook_event_name": "SubagentStop",
            "session_id": "session-123",
            "agent_id": "agent-abc",
        }

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()

        with patch('src.domain.hooks.subagent_event_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.subagent_event_hook.SubagentRepository', return_value=mock_subagent_repo):
                exit_code = self._run_main_with_stdin(input_data)

        assert exit_code == 0
        mock_subagent_repo.unregister.assert_called_once_with(
            "agent-abc", agent_transcript_path=None
        )


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
    """should_processでのROLE解析統合テスト（DBベース）"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_role_parsed_and_stored_in_db(self, tmp_path):
        """transcript解析でroleがDBに保存される（retry_matchがNoneの場合のフォールバック）"""
        hook = self._make_hook()

        # トランスクリプトファイル作成
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:coder]\nFix bug."}}) + '\n')

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-role-test"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record
        # retry_matchがNoneを返す（フォールバックテスト）
        mock_subagent_repo.retry_match_from_agent_progress.return_value = None

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": str(transcript),
                    })

        assert result is True
        # update_roleがrole=coderで呼ばれたことを確認
        mock_subagent_repo.update_role.assert_called_once_with("agent-role-test", "coder", "transcript_parse")

    def test_existing_role_not_overwritten(self, tmp_path):
        """マーカーに既存roleがある場合はtranscript解析しない"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:reviewer]\nReview."}}) + '\n')

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-existing-role"
        mock_record.role = "coder"  # 既にroleがある
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": str(transcript),
                    })

        assert result is True
        # update_roleはroleで呼ばれない（roleが既にある）
        mock_subagent_repo.update_role.assert_not_called()

    def test_no_role_in_transcript_no_update(self, tmp_path):
        """transcriptにROLEがない場合はupdate_role呼ばれない（retry_matchもNone）"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "No role here."}}) + '\n')

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-no-role"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record
        # retry_matchもNoneを返す
        mock_subagent_repo.retry_match_from_agent_progress.return_value = None

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": str(transcript),
                    })

        assert result is True
        mock_subagent_repo.update_role.assert_not_called()

    def test_role_passed_to_resolve_subagent_config(self, tmp_path):
        """解析されたroleが_resolve_subagent_configに渡される（retry_matchがNoneでフォールバック時）"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:coder]\nWork."}}) + '\n')

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-resolve-test"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record
        # retry_matchがNoneを返す（フォールバックテスト）
        mock_subagent_repo.retry_match_from_agent_progress.return_value = None

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    with patch.object(hook, '_resolve_subagent_config', return_value={"enabled": True, "messages": {}, "behavior": {}}) as mock_resolve:
                        hook.should_process({
                            "session_id": "test-session",
                            "transcript_path": str(transcript),
                        })

                    # roleがresolve_subagent_configに渡される
                    mock_resolve.assert_called_once_with("general-purpose", role="coder")


# ============================================================
# 案D簡易版（ハイブリッドアプローチ）テスト (#5947)
# ============================================================

class TestRetryMatchFromAgentProgress:
    """retry_match_from_agent_progressのユニットテスト"""

    def test_successful_retry_match(self, tmp_path):
        """agent_progressからの再マッチが成功するケース"""
        from src.infrastructure.db.nagger_state_db import NaggerStateDB
        from src.infrastructure.db.subagent_repository import SubagentRepository

        # tmp_path配下のDBファイルを使用
        db_path = tmp_path / "state.db"
        db = NaggerStateDB(db_path)
        repo = SubagentRepository(db)

        session_id = "test-session"
        agent_id = "agent-retry-test"
        tool_use_id = "toolu_01ABC"

        # subagentを登録（role=NULLで）
        repo.register(agent_id, session_id, "general-purpose", role=None)

        # task_spawnを登録（role付き）
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (session_id, 1, "general-purpose", "coder", "hash123", tool_use_id),
        )
        db.conn.commit()

        # agent_progressを含むtranscriptを作成
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {
                    "type": "agent_progress",
                    "agentId": agent_id,
                }
            }) + '\n')

        # 再マッチ試行
        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))

        assert result == "coder"

        # subagentのroleが更新されたか確認
        record = repo.get(agent_id)
        assert record.role == "coder"
        assert record.role_source == "retry_match"

        db.close()

    def test_no_agent_progress_returns_none(self, tmp_path):
        """agent_progressがない場合はNoneを返す"""
        from src.infrastructure.db.nagger_state_db import NaggerStateDB
        from src.infrastructure.db.subagent_repository import SubagentRepository

        db_path = tmp_path / "state.db"
        db = NaggerStateDB(db_path)
        repo = SubagentRepository(db)

        session_id = "test-session"
        agent_id = "agent-no-progress"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # agent_progressのないtranscript
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "Hello"}}) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result is None

        db.close()

    def test_no_matching_task_spawn_returns_none(self, tmp_path):
        """task_spawnが見つからない場合はNoneを返す"""
        from src.infrastructure.db.nagger_state_db import NaggerStateDB
        from src.infrastructure.db.subagent_repository import SubagentRepository

        db_path = tmp_path / "state.db"
        db = NaggerStateDB(db_path)
        repo = SubagentRepository(db)

        session_id = "test-session"
        agent_id = "agent-no-task-spawn"
        tool_use_id = "toolu_01XYZ"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # agent_progressはあるがtask_spawnがない
        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {
                    "type": "agent_progress",
                    "agentId": agent_id,
                }
            }) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result is None

        db.close()

    def test_already_matched_task_spawn_returns_none(self, tmp_path):
        """既に他のagentにマッチ済みのtask_spawnはNoneを返す"""
        from src.infrastructure.db.nagger_state_db import NaggerStateDB
        from src.infrastructure.db.subagent_repository import SubagentRepository

        db_path = tmp_path / "state.db"
        db = NaggerStateDB(db_path)
        repo = SubagentRepository(db)

        session_id = "test-session"
        agent_id = "agent-late"
        other_agent_id = "agent-early"
        tool_use_id = "toolu_01MATCHED"

        repo.register(agent_id, session_id, "general-purpose", role=None)

        # 既にマッチ済みのtask_spawn
        db.conn.execute(
            """
            INSERT INTO task_spawns (session_id, transcript_index, subagent_type, role, prompt_hash, tool_use_id, matched_agent_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (session_id, 1, "general-purpose", "coder", "hash123", tool_use_id, other_agent_id),
        )
        db.conn.commit()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({
                "type": "progress",
                "parentToolUseID": tool_use_id,
                "data": {
                    "type": "agent_progress",
                    "agentId": agent_id,
                }
            }) + '\n')

        result = repo.retry_match_from_agent_progress(session_id, agent_id, str(transcript))
        assert result is None

        db.close()


class TestShouldProcessRetryMatch:
    """should_processでのretry_match統合テスト"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_retry_match_called_when_role_is_none(self, tmp_path):
        """role=Noneの場合にretry_match_from_agent_progressが呼ばれる"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-retry"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record
        mock_subagent_repo.retry_match_from_agent_progress.return_value = "coder"

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": str(transcript),
                    })

        assert result is True
        mock_subagent_repo.retry_match_from_agent_progress.assert_called_once_with(
            "test-session", "agent-retry", str(transcript)
        )
        # retry_matchが成功したのでupdate_roleは呼ばれない
        mock_subagent_repo.update_role.assert_not_called()

    def test_fallback_to_transcript_parse_when_retry_fails(self, tmp_path):
        """retry_matchが失敗した場合はtranscript解析にフォールバック"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        with open(transcript, 'w') as f:
            f.write(json.dumps({"type": "user", "message": {"content": "[ROLE:reviewer]\nReview."}}) + '\n')

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-fallback"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record
        mock_subagent_repo.retry_match_from_agent_progress.return_value = None

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": str(transcript),
                    })

        assert result is True
        # retry_matchが失敗したのでtranscript解析でupdate_roleが呼ばれる
        mock_subagent_repo.update_role.assert_called_once_with("agent-fallback", "reviewer", "transcript_parse")

    def test_retry_match_not_called_when_role_exists(self, tmp_path):
        """既にroleがある場合はretry_matchが呼ばれない"""
        hook = self._make_hook()

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("")

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-has-role"
        mock_record.role = "coder"  # 既にroleがある
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        "transcript_path": str(transcript),
                    })

        assert result is True
        mock_subagent_repo.retry_match_from_agent_progress.assert_not_called()

    def test_retry_match_not_called_without_transcript_path(self):
        """transcript_pathがない場合はretry_matchが呼ばれない"""
        hook = self._make_hook()

        mock_db = MagicMock()
        mock_subagent_repo = MagicMock()
        mock_session_repo = MagicMock()

        mock_subagent_repo.is_any_active.return_value = True
        mock_record = MagicMock()
        mock_record.agent_type = "general-purpose"
        mock_record.agent_id = "agent-no-transcript"
        mock_record.role = None
        mock_subagent_repo.claim_next_unprocessed.return_value = mock_record

        with patch('src.domain.hooks.session_startup_hook.NaggerStateDB', return_value=mock_db):
            with patch('src.domain.hooks.session_startup_hook.SubagentRepository', return_value=mock_subagent_repo):
                with patch('src.domain.hooks.session_startup_hook.SessionRepository', return_value=mock_session_repo):
                    result = hook.should_process({
                        "session_id": "test-session",
                        # transcript_pathなし
                    })

        assert result is True
        mock_subagent_repo.retry_match_from_agent_progress.assert_not_called()


class TestStripNumericSuffix:
    """_strip_numeric_suffix関数の単体テスト"""

    def test_strip_single_digit(self):
        """末尾-1桁数字を除去"""
        assert _strip_numeric_suffix("tester-2") == "tester"

    def test_strip_different_digit(self):
        """末尾-異なる1桁数字を除去"""
        assert _strip_numeric_suffix("scribe-3") == "scribe"

    def test_no_suffix(self):
        """サフィックスなしはそのまま返す"""
        assert _strip_numeric_suffix("coder") == "coder"

    def test_non_numeric_suffix_unchanged(self):
        """末尾が数字でないハイフン付き名前は変化なし"""
        assert _strip_numeric_suffix("tech-lead") == "tech-lead"

    def test_strip_multi_digit(self):
        """末尾-2桁数字を除去"""
        assert _strip_numeric_suffix("agent-10") == "agent"

    def test_empty_string(self):
        """空文字列はそのまま返す"""
        assert _strip_numeric_suffix("") == ""


class TestResolveSubagentConfigSuffixFallback:
    """_resolve_subagent_configのsuffix除去フォールバックテスト"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        """テスト用hookインスタンス生成"""
        config = config if config is not None else self.BASE_CONFIG
        with patch.object(SessionStartupHook, '_load_config', return_value=config):
            return SessionStartupHook()

    def test_exact_match_priority(self):
        """完全一致がsuffix除去より優先される"""
        # config.yamlにtesterがあるので、tester-2用の独自設定を追加
        config = _load_real_config()
        config.setdefault("overrides", {}).setdefault("subagent_types", {})
        config["overrides"]["subagent_types"]["tester-2"] = {
            "messages": {"first_time": {"title": "tester-2専用規約"}}
        }
        hook = self._make_hook(config)
        resolved = hook._resolve_subagent_config("general-purpose", role="tester-2")
        # tester-2の完全一致設定が使われる
        assert resolved["messages"]["first_time"]["title"] == "tester-2専用規約"

    def test_suffix_fallback_role(self):
        """suffix除去でベースロール設定にフォールバック"""
        hook = self._make_hook()
        # config.yamlにtesterはあるがtester-2はない → testerにフォールバック
        resolved = hook._resolve_subagent_config("general-purpose", role="tester-2")
        assert resolved["messages"]["first_time"]["title"] == "tester subagent規約"

    def test_existing_role_no_suffix(self):
        """既存のsuffix無しロール名は変化なく動作（回帰テスト）"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("general-purpose", role="coder")
        assert resolved["messages"]["first_time"]["title"] == "coder subagent規約"

    def test_existing_role_tester(self):
        """testerロールの既存動作確認（回帰テスト）"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("general-purpose", role="tester")
        assert resolved["messages"]["first_time"]["title"] == "tester subagent規約"

    def test_colon_separator_still_works(self):
        """':'区切りフォールバックが引き続き動作"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("ticket-tasuki:coder")
        assert resolved["messages"]["first_time"]["title"] == "coder subagent規約"

    def test_agent_type_suffix_fallback(self):
        """agent_typeにsuffix付きの場合もフォールバック"""
        hook = self._make_hook()
        # roleがNoneでagent_type="tester-2" → testerにフォールバック
        resolved = hook._resolve_subagent_config("tester-2", role=None)
        assert resolved["messages"]["first_time"]["title"] == "tester subagent規約"

    def test_agent_type_no_suffix_still_works(self):
        """agent_typeにsuffixなしの通常動作（回帰テスト）"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("tester")
        assert resolved["messages"]["first_time"]["title"] == "tester subagent規約"

    def test_no_match_returns_default(self):
        """どのルールにもマッチしない場合はsubagent_defaultにフォールバック"""
        hook = self._make_hook()
        resolved = hook._resolve_subagent_config("unknown-agent", role="nonexistent-5")
        # subagent_defaultの設定が使われる
        assert resolved["messages"]["first_time"]["title"] == "subagent規約"
        assert "作業完了後に結果を報告すること" in resolved["messages"]["first_time"]["main_text"]


class TestParseRoleFromTranscriptHyphen:
    """_parse_role_from_transcriptのハイフン対応テスト"""

    BASE_CONFIG = TestSessionStartupHookSubagentOverride.BASE_CONFIG

    def _make_hook(self, config=None):
        """テスト用hookインスタンス生成"""
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

    def test_role_with_numeric_suffix(self, tmp_path):
        """[ROLE:coder-2]がマッチすること"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": "[ROLE:coder-2]\nPlease fix the bug."}},
        ])
        assert hook._parse_role_from_transcript(path) == "coder-2"

    def test_role_without_suffix_still_works(self, tmp_path):
        """[ROLE:coder]が引き続きマッチすること（回帰テスト）"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": "[ROLE:coder]\nPlease fix the bug."}},
        ])
        assert hook._parse_role_from_transcript(path) == "coder"

    def test_role_with_hyphen_non_numeric(self, tmp_path):
        """[ROLE:tech-lead]がマッチすること"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": "[ROLE:tech-lead]\nReview this code."}},
        ])
        assert hook._parse_role_from_transcript(path) == "tech-lead"

    def test_role_tester_with_suffix(self, tmp_path):
        """[ROLE:tester-3]がマッチすること"""
        hook = self._make_hook()
        path = self._write_transcript(tmp_path, [
            {"type": "user", "message": {"content": "[ROLE:tester-3]\nRun tests."}},
        ])
        assert hook._parse_role_from_transcript(path) == "tester-3"
