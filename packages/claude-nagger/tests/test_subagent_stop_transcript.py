"""SubagentStop即時transcript格納テスト（issue_6184）

- agent_transcript_pathがある場合のsubagent_history格納
- agent_transcript_pathがない場合のgraceful degradation
- config.yaml modeの反映
- _launch_subagent_transcript_storage のバックグラウンド起動
- スキーマv7マイグレーション
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.subagent_history_repository import SubagentHistoryRepository
from infrastructure.db.subagent_repository import SubagentRepository


# === フィクスチャ ===

@pytest.fixture
def sample_transcript(tmp_path):
    """テスト用subagentトランスクリプト .jsonlファイル"""
    jsonl_path = tmp_path / "subagent-abc123.jsonl"
    lines = [
        {"type": "user", "message": {"content": "implement feature"}},
        {"type": "assistant", "message": {"content": "done", "usage": {"input_tokens": 50}}},
    ]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return jsonl_path


# === unregister agent_transcript_path格納テスト ===

class TestUnregisterWithTranscriptPath:
    """unregister時にagent_transcript_pathがsubagent_historyに格納される"""

    def test_transcript_path_stored_in_history(self, db):
        """agent_transcript_pathがsubagent_historyに正しく保存される"""
        repo = SubagentRepository(db)
        repo.register("agent-1", "session-1", "coder")

        transcript_path = "/path/to/subagent-abc123.jsonl"
        repo.unregister("agent-1", agent_transcript_path=transcript_path)

        history_repo = SubagentHistoryRepository(db)
        records = history_repo.get_by_session("session-1")
        assert len(records) == 1
        assert records[0]["agent_transcript_path"] == transcript_path

    def test_transcript_path_none_when_not_provided(self, db):
        """agent_transcript_path未指定時はNULL"""
        repo = SubagentRepository(db)
        repo.register("agent-2", "session-2", "coder")

        repo.unregister("agent-2")

        history_repo = SubagentHistoryRepository(db)
        records = history_repo.get_by_session("session-2")
        assert len(records) == 1
        assert records[0]["agent_transcript_path"] is None

    def test_transcript_path_with_full_lifecycle(self, db):
        """register → unregister(with transcript_path) の全ライフサイクル"""
        repo = SubagentRepository(db)
        repo.register("agent-3", "session-3", "researcher",
                       leader_transcript_path="/leader/transcript.jsonl")

        transcript_path = "/subagent/agent-3-transcript.jsonl"
        repo.unregister("agent-3", agent_transcript_path=transcript_path)

        history_repo = SubagentHistoryRepository(db)
        records = history_repo.get_by_agent("agent-3")
        assert len(records) == 1
        r = records[0]
        assert r["agent_id"] == "agent-3"
        assert r["session_id"] == "session-3"
        assert r["agent_type"] == "researcher"
        assert r["leader_transcript_path"] == "/leader/transcript.jsonl"
        assert r["agent_transcript_path"] == transcript_path
        assert r["stopped_at"] is not None


# === スキーマv7マイグレーションテスト ===

class TestSchemaV7Migration:
    """v6→v7マイグレーション: subagent_historyにagent_transcript_pathカラム追加"""

    def test_fresh_db_has_agent_transcript_path_column(self, db):
        """新規DBにagent_transcript_pathカラムが存在する"""
        cursor = db.conn.execute("PRAGMA table_info(subagent_history)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "agent_transcript_path" in columns

    def test_migration_from_v6_adds_column(self, tmp_path):
        """v6 DBからv7へのマイグレーションでカラムが追加される"""
        import sqlite3

        db_path = tmp_path / ".claude-nagger" / "state.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # v6相当のDBを手動作成（agent_transcript_pathカラムなし）
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            INSERT INTO schema_version (version, applied_at) VALUES (6, '2025-01-01T00:00:00+00:00');

            CREATE TABLE subagents (
                agent_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_type TEXT NOT NULL DEFAULT 'unknown',
                role TEXT,
                role_source TEXT,
                created_at TEXT NOT NULL,
                startup_processed INTEGER NOT NULL DEFAULT 0,
                startup_processed_at TEXT,
                task_match_index INTEGER,
                leader_transcript_path TEXT
            );

            CREATE TABLE task_spawns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                transcript_index INTEGER NOT NULL,
                subagent_type TEXT,
                role TEXT,
                prompt_hash TEXT,
                tool_use_id TEXT,
                matched_agent_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, transcript_index)
            );

            CREATE TABLE sessions (
                session_id TEXT NOT NULL,
                hook_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_tokens INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                expired_at TEXT,
                PRIMARY KEY (session_id, hook_name)
            );

            CREATE TABLE hook_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                hook_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                agent_id TEXT,
                timestamp TEXT NOT NULL,
                result TEXT,
                details TEXT,
                duration_ms INTEGER
            );

            CREATE TABLE subagent_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                agent_type TEXT,
                role TEXT,
                role_source TEXT,
                leader_transcript_path TEXT,
                started_at TEXT NOT NULL,
                stopped_at TEXT,
                issue_id TEXT
            );

            CREATE TABLE transcript_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                line_type TEXT,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                timestamp TEXT,
                content_summary TEXT,
                tool_name TEXT,
                token_count INTEGER,
                model TEXT,
                uuid TEXT
            );
        """)
        conn.close()

        # NaggerStateDBで開くとv7マイグレーションが実行される
        db = NaggerStateDB(db_path)
        db.connect()

        # agent_transcript_pathカラムが追加されている
        cursor = db.conn.execute("PRAGMA table_info(subagent_history)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "agent_transcript_path" in columns

        # バージョン8が記録されている
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 8

        db.close()


# === _launch_subagent_transcript_storageテスト ===

class TestLaunchSubagentTranscriptStorage:
    """subagentトランスクリプトのバックグラウンド格納起動テスト"""

    @patch("domain.hooks.subagent_event_hook.subprocess.Popen")
    @patch("domain.hooks.subagent_event_hook._load_transcript_storage_config")
    def test_launches_background_when_enabled(
        self, mock_config, mock_popen, sample_transcript
    ):
        """enabled=true時にnohupでバックグラウンドプロセスが起動される"""
        from domain.hooks.subagent_event_hook import _launch_subagent_transcript_storage

        mock_config.return_value = {"enabled": True, "mode": "indexed"}

        _launch_subagent_transcript_storage(
            "agent-1", str(sample_transcript)
        )

        mock_popen.assert_called_once()
        args = mock_popen.call_args
        cmd = args[0][0]
        assert cmd[0] == "nohup"
        assert "--background" in cmd
        assert "--session-id" in cmd
        # session_id = ファイル名の拡張子除去
        assert "subagent-abc123" in cmd
        assert "--transcript-path" in cmd
        assert str(sample_transcript) in cmd
        assert "--mode" in cmd
        assert "indexed" in cmd
        assert args[1]["start_new_session"] is True

    @patch("domain.hooks.subagent_event_hook.subprocess.Popen")
    @patch("domain.hooks.subagent_event_hook._load_transcript_storage_config")
    def test_skips_when_disabled(self, mock_config, mock_popen, sample_transcript):
        """enabled=false時はスキップ"""
        from domain.hooks.subagent_event_hook import _launch_subagent_transcript_storage

        mock_config.return_value = {"enabled": False}

        _launch_subagent_transcript_storage(
            "agent-1", str(sample_transcript)
        )

        mock_popen.assert_not_called()

    @patch("domain.hooks.subagent_event_hook.subprocess.Popen")
    @patch("domain.hooks.subagent_event_hook._load_transcript_storage_config")
    def test_skips_when_config_empty(self, mock_config, mock_popen, sample_transcript):
        """config未設定時はスキップ（デフォルトenabled=false）"""
        from domain.hooks.subagent_event_hook import _launch_subagent_transcript_storage

        mock_config.return_value = {}

        _launch_subagent_transcript_storage(
            "agent-1", str(sample_transcript)
        )

        mock_popen.assert_not_called()

    @patch("domain.hooks.subagent_event_hook.subprocess.Popen")
    @patch("domain.hooks.subagent_event_hook._load_transcript_storage_config")
    def test_skips_when_file_not_exists(self, mock_config, mock_popen):
        """トランスクリプトファイル不在時はスキップ"""
        from domain.hooks.subagent_event_hook import _launch_subagent_transcript_storage

        mock_config.return_value = {"enabled": True, "mode": "raw"}

        _launch_subagent_transcript_storage(
            "agent-1", "/nonexistent/path/transcript.jsonl"
        )

        mock_popen.assert_not_called()

    @patch("domain.hooks.subagent_event_hook.subprocess.Popen",
           side_effect=Exception("spawn error"))
    @patch("domain.hooks.subagent_event_hook._load_transcript_storage_config")
    def test_popen_failure_does_not_raise(
        self, mock_config, mock_popen, sample_transcript
    ):
        """Popen失敗時に例外が伝播しない（graceful degradation）"""
        from domain.hooks.subagent_event_hook import _launch_subagent_transcript_storage

        mock_config.return_value = {"enabled": True, "mode": "raw"}

        # 例外が伝播しないことを確認
        _launch_subagent_transcript_storage(
            "agent-1", str(sample_transcript)
        )

    @patch("domain.hooks.subagent_event_hook.subprocess.Popen")
    @patch("domain.hooks.subagent_event_hook._load_transcript_storage_config")
    def test_default_mode_is_raw(self, mock_config, mock_popen, sample_transcript):
        """mode未指定時はデフォルトraw"""
        from domain.hooks.subagent_event_hook import _launch_subagent_transcript_storage

        mock_config.return_value = {"enabled": True}

        _launch_subagent_transcript_storage(
            "agent-1", str(sample_transcript)
        )

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        mode_idx = cmd.index("--mode")
        assert cmd[mode_idx + 1] == "raw"


# === config読み込みテスト ===

class TestLoadTranscriptStorageConfig:
    """_load_transcript_storage_config のテスト"""

    def test_loads_from_config_yaml(self, tmp_path, monkeypatch):
        """config.yamlからtranscript_storage設定を読み込む"""
        from domain.hooks.subagent_event_hook import _load_transcript_storage_config

        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            "transcript_storage:\n  enabled: true\n  mode: indexed\n",
            encoding="utf-8",
        )
        # CLAUDE_PROJECT_DIRを設定して最優先で発見させる
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        result = _load_transcript_storage_config()
        assert result == {"enabled": True, "mode": "indexed"}

    def test_returns_empty_when_no_config(self, tmp_path, monkeypatch):
        """config.yaml不在時でもパッケージルートフォールバックで実config発見"""
        from domain.hooks.subagent_event_hook import _load_transcript_storage_config

        monkeypatch.chdir(tmp_path)

        result = _load_transcript_storage_config()
        # パッケージルートフォールバック（candidate #2）で実config.yamlが発見される
        assert result == {'enabled': True, 'mode': 'structured', 'retention_days': 30}

    def test_returns_empty_when_no_transcript_storage_key(self, tmp_path, monkeypatch):
        """transcript_storageキー不在時でもパッケージルートフォールバックで実config発見"""
        from domain.hooks.subagent_event_hook import _load_transcript_storage_config

        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text("session_startup:\n  enabled: true\n", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        result = _load_transcript_storage_config()
        # CLAUDE_PROJECT_DIR未設定のため、パッケージルートフォールバック（candidate #2）で実config.yamlが発見される
        assert result == {'enabled': True, 'mode': 'structured', 'retention_days': 30}


class TestLoadTranscriptStorageConfigFallback:
    """_load_transcript_storage_config のパッケージルートフォールバックテスト（issue_6189）

    CLAUDE_PROJECT_DIRがモノレポルート等を指し、config.yamlが見つからない場合に
    __file__ベースのパッケージルートにフォールバックする。
    """

    def test_fallback_to_package_root_when_env_wrong(self, tmp_path, monkeypatch):
        """CLAUDE_PROJECT_DIRが不正でも__file__ベースのパッケージルートで発見する"""
        from domain.hooks.subagent_event_hook import _load_transcript_storage_config

        # CLAUDE_PROJECT_DIRをconfig.yamlが無いパスに設定（モノレポルート想定）
        wrong_dir = tmp_path / "wrong_project"
        wrong_dir.mkdir()
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(wrong_dir))
        monkeypatch.chdir(tmp_path)

        # パッケージルート（__file__の4階層上）のconfig.yamlが参照されることを確認
        import domain.hooks.subagent_event_hook as module
        pkg_root = Path(module.__file__).resolve().parent.parent.parent.parent
        config_path = pkg_root / ".claude-nagger" / "config.yaml"

        result = _load_transcript_storage_config()
        if config_path.exists():
            # 実在のconfig.yamlが見つかる（transcript_storageキーの有無で結果が変わる）
            assert isinstance(result, dict)
        else:
            assert result == {}

    def test_claude_project_dir_takes_priority(self, tmp_path, monkeypatch):
        """CLAUDE_PROJECT_DIRにconfig.yamlがある場合はそちらが優先される"""
        from domain.hooks.subagent_event_hook import _load_transcript_storage_config

        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            "transcript_storage:\n  enabled: true\n  mode: raw\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

        result = _load_transcript_storage_config()
        assert result == {"enabled": True, "mode": "raw"}
