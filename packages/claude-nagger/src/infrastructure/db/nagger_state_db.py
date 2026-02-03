"""NaggerStateDB - 状態管理データベース"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


# スキーマ定義（v1）
_SCHEMA_V1 = """
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE subagents (
    agent_id            TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    agent_type          TEXT NOT NULL DEFAULT 'unknown',
    role                TEXT,
    role_source         TEXT,
    created_at          TEXT NOT NULL,
    startup_processed   INTEGER NOT NULL DEFAULT 0,
    startup_processed_at TEXT,
    task_match_index    INTEGER
);

CREATE TABLE task_spawns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    transcript_index    INTEGER NOT NULL,
    subagent_type       TEXT,
    role                TEXT,
    prompt_hash         TEXT,
    matched_agent_id    TEXT,
    created_at          TEXT NOT NULL,
    UNIQUE(session_id, transcript_index)
);

CREATE TABLE sessions (
    session_id          TEXT NOT NULL,
    hook_name           TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    last_tokens         INTEGER DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active',
    expired_at          TEXT,
    PRIMARY KEY (session_id, hook_name)
);

CREATE TABLE hook_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    hook_name           TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    agent_id            TEXT,
    timestamp           TEXT NOT NULL,
    result              TEXT,
    details             TEXT,
    duration_ms         INTEGER
);

CREATE INDEX idx_subagents_session ON subagents(session_id);
CREATE INDEX idx_subagents_unprocessed ON subagents(session_id, startup_processed) WHERE startup_processed = 0;
CREATE INDEX idx_task_spawns_session ON task_spawns(session_id);
CREATE INDEX idx_task_spawns_unmatched ON task_spawns(session_id, matched_agent_id) WHERE matched_agent_id IS NULL;
CREATE INDEX idx_sessions_status ON sessions(status);
CREATE INDEX idx_hook_log_session ON hook_log(session_id, timestamp);
"""


class NaggerStateDB:
    """状態管理SQLiteデータベース"""

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path):
        """初期化

        Args:
            db_path: データベースファイルパス
        """
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        """データベースに接続する

        未接続の場合のみ新規接続を作成。
        WALモード有効化、外部キー制約有効化、タイムアウト5秒。

        Returns:
            sqlite3.Connection: データベース接続
        """
        if self._conn is not None:
            return self._conn

        # 親ディレクトリが存在しない場合は作成
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self._db_path), timeout=5)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._ensure_schema()
        return self._conn

    def close(self) -> None:
        """接続をクローズする"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """接続プロパティ（未接続なら自動接続）"""
        if self._conn is None:
            self.connect()
        return self._conn  # type: ignore[return-value]

    def __enter__(self) -> "NaggerStateDB":
        """コンテキストマネージャ: 開始"""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """コンテキストマネージャ: 終了"""
        self.close()

    def _ensure_schema(self) -> None:
        """スキーマの確認と作成

        schema_versionテーブルが存在しない場合はスキーマ全体を作成。
        バージョン差異がある場合はマイグレーションを実行。
        """
        assert self._conn is not None

        # schema_versionテーブルの存在確認
        cursor = self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        if cursor.fetchone() is None:
            # 初回: スキーマ全体を作成
            self._conn.executescript(_SCHEMA_V1)
            now = datetime.now(timezone.utc).isoformat()
            self._conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (self.SCHEMA_VERSION, now),
            )
            self._conn.commit()
            return

        # バージョン確認
        cursor = self._conn.execute(
            "SELECT MAX(version) FROM schema_version"
        )
        row = cursor.fetchone()
        current_version = row[0] if row and row[0] is not None else 0

        if current_version < self.SCHEMA_VERSION:
            self._migrate(current_version, self.SCHEMA_VERSION)

    def _migrate(self, from_ver: int, to_ver: int) -> None:
        """マイグレーション実行（将来用）

        v1では実質空。将来のバージョンアップ時にここにマイグレーション処理を追加。

        Args:
            from_ver: 現在のスキーマバージョン
            to_ver: 目標のスキーマバージョン
        """
        pass

    @classmethod
    def resolve_db_path(cls) -> Path:
        """データベースパスを解決する

        優先順:
        1. 環境変数 CLAUDE_PROJECT_DIR
        2. Path.cwd()
        3. エラー

        Returns:
            Path: .claude-nagger/state.db のパス

        Raises:
            RuntimeError: パス解決に失敗した場合
        """
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        if project_dir:
            return Path(project_dir) / ".claude-nagger" / "state.db"

        try:
            return Path.cwd() / ".claude-nagger" / "state.db"
        except OSError as e:
            raise RuntimeError(
                "データベースパスの解決に失敗: CLAUDE_PROJECT_DIRが未設定かつcwdも取得不可"
            ) from e
