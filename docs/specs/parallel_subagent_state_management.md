# 並列subagent状態管理 設計仕様書

## 概要

issue #5934/#5935/#5936対応。現行の個別JSONファイルベースマーカー管理をSQLiteベース集中管理に移行。並列subagent起動時のROLE識別・規約注入の正確性を実現する。

## 背景・問題

### 現行アーキテクチャの限界

現行: `/tmp/claude-nagger-{uid}/{session_id}/subagents/{agent_id}.json` に個別ファイル

問題点:
1. `get_active_subagent()`が最新マーカー1件のみ返す → 並列時に誤対応
2. `_parse_role_from_transcript()`が最後のTask promptのROLEを返す → 並列時に上書き
3. PreToolUse `input_data`に`agent_id`なし → Claude Code API制約、subagent識別不可
4. アトミック操作不在 → レースコンディションのリスク
5. ディレクトリリストが「クエリ」代替 → 横断的状態管理が困難

### Claude Code API制約（不変）

| イベント | agent_id | agent_transcript_path |
|---------|----------|----------------------|
| SubagentStart | あり | なし |
| PreToolUse | **なし** | なし |
| SubagentStop | あり | あり |

PreToolUseで「どのsubagentが呼んだか」を直接識別する手段がAPI側に存在しない。

## 設計方針

### 解決戦略: Registry + 2段階Claim

**Phase 1 - SubagentStart時（agent_idあり）**:
- DB登録 + 親transcript解析でTask tool_useとマッチング → ROLE割当

**Phase 2 - PreToolUse時（agent_idなし）**:
- 未処理subagentをFIFO Claimで割当（排他消去法を優先）

### ストレージ選択: SQLite

理由:
- Python stdlib（`sqlite3`）で依存追加なし
- ACID トランザクション → アトミックなClaim操作
- WALモード → 並行読み取り
- 単一ファイル → 管理容易
- スキーマ拡張容易（テーブル追加のみ）

## DB仕様

### 配置場所

`{project_root}/.claude-nagger/state.db`

- プロジェクト単位で永続化
- `.gitignore`に追加必要
- WALモード有効（`PRAGMA journal_mode=WAL`）
- 接続タイムアウト: 5秒（`sqlite3.connect(timeout=5)`）
- パス解決優先順: 環境変数`CLAUDE_PROJECT_DIR` → `Path.cwd()` → エラー
- `NaggerStateDB.__init__`にて解決。呼び出し元はパスを意識しない

### 初期化タイミング

遅延初期化方式。各hook実行時に`NaggerStateDB.connect()`内で`_ensure_schema()`を呼び出し。
- 初回: DBファイル作成 + スキーマ適用 + WAL有効化
- 2回目以降: バージョン確認のみ（マイグレーション必要時は自動実行）
- `install_hooks`での明示的初期化は不要
- 並列hook初回起動時の安全性: `CREATE TABLE IF NOT EXISTS`で競合回避。SQLiteのファイルロックが排他制御を保証

### スキーマ（v1）

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- スキーマバージョン管理
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- subagentライフサイクル管理
CREATE TABLE subagents (
    agent_id            TEXT PRIMARY KEY,
    session_id          TEXT NOT NULL,
    agent_type          TEXT NOT NULL DEFAULT 'unknown',
    role                TEXT,
    role_source         TEXT,       -- 'task_match' / 'transcript_parse' / 'manual'
    created_at          TEXT NOT NULL,
    startup_processed   INTEGER NOT NULL DEFAULT 0,
    startup_processed_at TEXT,
    task_match_index    INTEGER     -- 対応するtask_spawnsのid
);

-- 親transcript内のTask tool_use追跡
CREATE TABLE task_spawns (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id          TEXT NOT NULL,
    transcript_index    INTEGER NOT NULL,  -- transcript内の行位置
    subagent_type       TEXT,
    role                TEXT,              -- prompt内[ROLE:xxx]
    prompt_hash         TEXT,              -- SHA256先頭16文字
    matched_agent_id    TEXT,              -- NULLなら未マッチ
    created_at          TEXT NOT NULL,
    UNIQUE(session_id, transcript_index)  -- register_task_spawns冪等性保証
);

-- セッション処理状態管理（BaseHookマーカー代替）
CREATE TABLE sessions (
    session_id          TEXT NOT NULL,
    hook_name           TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    last_tokens         INTEGER DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'active',
    expired_at          TEXT,
    PRIMARY KEY (session_id, hook_name)
);

-- hook実行ログ（監査・メトリクス）
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
```

## クラス設計

### 全体構造

```
NaggerStateDB (接続管理・スキーマ・マイグレーション)
├── SubagentRepository (subagents + task_spawns操作)
├── SessionRepository (sessions操作)
└── HookLogRepository (hook_log操作)
```

### NaggerStateDB

DB接続管理・スキーマバージョニング担当。

```python
class NaggerStateDB:
    """SQLiteベース集中状態管理。

    配置: {project_root}/.claude-nagger/state.db
    モード: WAL（並行読み取り対応）
    """

    SCHEMA_VERSION = 1

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def connect(self) -> sqlite3.Connection:
        """接続取得。未接続なら新規作成。WAL有効化・スキーマ保証含む。"""

    def close(self) -> None:
        """接続クローズ。"""

    def __enter__(self) -> 'NaggerStateDB': ...
    def __exit__(self, *args) -> None: ...

    def _ensure_schema(self) -> None:
        """スキーマ未作成なら作成。バージョン差異があればマイグレーション実行。"""

    def _migrate(self, from_ver: int, to_ver: int) -> None:
        """スキーママイグレーション。"""

    @property
    def conn(self) -> sqlite3.Connection:
        """アクティブな接続を返す。未接続ならconnect()呼び出し。"""
```

### SubagentRepository

subagentライフサイクル＋Claimパターン担当。

```python
class SubagentRepository:
    """subagentの登録・識別・Claim操作。"""

    def __init__(self, db: NaggerStateDB): ...

    # === ライフサイクル ===
    def register(self, agent_id: str, session_id: str, agent_type: str, role: str = None) -> None:
        """SubagentStart時。INSERT INTO subagents。"""

    def unregister(self, agent_id: str) -> None:
        """SubagentStop時。DELETE FROM subagents + task_spawns cleanup。"""

    # === Task tool_useマッチング（Phase 1） ===
    def register_task_spawns(self, session_id: str, transcript_path: str) -> int:
        """親transcriptからTask tool_useを解析し、未登録分をINSERT。
        戻り値: 新規登録件数。
        冪等性: prompt_hash + transcript_indexの組で重複排除。"""

    def match_task_to_agent(self, session_id: str, agent_id: str, agent_type: str) -> Optional[str]:
        """未マッチのtask_spawnから、agent_typeが一致する最古を取得し、マッチング。
        戻り値: role（マッチ成功時）/ None（失敗時）。
        トランザクション内でアトミック実行。"""

    # === Claimパターン（Phase 2） ===
    def claim_next_unprocessed(self, session_id: str) -> Optional[SubagentRecord]:
        """PreToolUse時。未処理(startup_processed=0)の最古subagentを取得。
        排他消去法: 未処理1件なら確定。複数ならFIFO。
        startup_processed=1にアトミック更新。
        戻り値: UPDATE前の状態のSubagentRecord or None。"""

    # === クエリ ===
    def get(self, agent_id: str) -> Optional[SubagentRecord]: ...
    def get_active(self, session_id: str) -> List[SubagentRecord]: ...
    def get_unprocessed_count(self, session_id: str) -> int: ...
    def is_any_active(self, session_id: str) -> bool: ...

    # === 更新 ===
    def update_role(self, agent_id: str, role: str, source: str) -> None: ...

    # === クリーンアップ ===
    def cleanup_session(self, session_id: str) -> int: ...
```

### SubagentRecord

```python
@dataclass
class SubagentRecord:
    agent_id: str
    session_id: str
    agent_type: str
    role: Optional[str]
    role_source: Optional[str]
    created_at: str
    startup_processed: bool
    startup_processed_at: Optional[str]
    task_match_index: Optional[int]
```

### SessionRepository

セッション処理状態管理（現行BaseHookマーカーの代替）。

```python
class SessionRepository:
    """セッション処理状態の管理。"""

    def __init__(self, db: NaggerStateDB): ...

    def register(self, session_id: str, hook_name: str, tokens: int = 0) -> None:
        """処理済みマーク。INSERT OR REPLACE。"""

    def is_processed(self, session_id: str, hook_name: str) -> bool:
        """処理済みか判定。"""

    def is_processed_context_aware(self, session_id: str, hook_name: str,
                                    current_tokens: int, threshold: int) -> bool:
        """トークン増加量ベースの判定。閾値超過時はexpireしてFalse返却。"""

    def expire(self, session_id: str, hook_name: str, reason: str = 'expired') -> None:
        """セッションを期限切れに。"""

    def expire_all(self, session_id: str, reason: str = 'compact_expired') -> None:
        """セッション全hookを期限切れに（compact時）。"""

    def get(self, session_id: str, hook_name: str) -> Optional[SessionRecord]: ...
```

### HookLogRepository

監査・メトリクス用。

```python
class HookLogRepository:
    """hook実行ログの記録・照会。"""

    def __init__(self, db: NaggerStateDB): ...

    def log(self, session_id: str, hook_name: str, event_type: str,
            agent_id: str = None, result: str = None,
            details: dict = None, duration_ms: int = None) -> None:
        """hook実行を記録。"""

    def get_recent(self, session_id: str, limit: int = 50) -> List[HookLogRecord]: ...
    def get_stats(self, session_id: str) -> dict: ...
```

## 主要フロー

### SubagentStart

```
1. subagent_event_hook受信 (agent_id, agent_type, session_id, transcript_path※共通フィールド=親セッションtranscript)
2. db = NaggerStateDB(.claude-nagger/state.db)
3. repo = SubagentRepository(db)
4. repo.register(agent_id, session_id, agent_type)
5. repo.register_task_spawns(session_id, transcript_path)  # 親transcript解析
6. role = repo.match_task_to_agent(session_id, agent_id, agent_type)
7. if role: repo.update_role(agent_id, role, 'task_match')
8. hook_log.log(session_id, 'subagent_event', 'SubagentStart', agent_id=agent_id)
```

### PreToolUse（subagent内）

```
1. session_startup_hook受信 (session_id, transcript_path, tool_name, tool_input)
2. db = NaggerStateDB(.claude-nagger/state.db)
3. repo = SubagentRepository(db)
4. if not repo.is_any_active(session_id): → メインエージェント処理へ
5. record = repo.claim_next_unprocessed(session_id)  # アトミックClaim
6. if not record: → 全subagent処理済み、skip
7. if not record.role:
     role = _parse_role_from_transcript(transcript_path)
     if role: repo.update_role(record.agent_id, role, 'transcript_parse')
8. config = _resolve_subagent_config(record.agent_type, role=record.role or role)
9. return blocking_message(config)
```

### SubagentStop

```
1. subagent_event_hook受信 (agent_id)
2. repo.unregister(agent_id)  # DELETE FROM subagents + DELETE FROM task_spawns WHERE matched_agent_id = agent_id
3. hook_log.log(...)
```

### Compact検知

```
1. compact_detected_hook受信 (session_id, source='compact')
2. session_repo.expire_all(session_id, 'compact_expired')
3. 注: subagentsテーブルは操作しない（アクティブsubagentの状態を保持）
```

## Task tool_useマッチングアルゴリズム

### register_task_spawns

```
1. 親transcript (JSONL) を読み込み
2. 各行について:
   - トップレベル type='assistant' のエントリを対象
   - message.content[] 内の type='tool_use' かつ name='Task' ブロックを抽出
   - tool_use.input から subagent_type, prompt を取得
   - prompt から [ROLE:xxx] を正規表現で抽出
   - prompt_hash = SHA256(prompt)[:16]
   - transcript_index = 行番号
3. 既存task_spawns (session_id, transcript_index) と突合
4. 未登録分をINSERT
```

### match_task_to_agent

```
1. BEGIN EXCLUSIVE
2. SELECT * FROM task_spawns
   WHERE session_id = ? AND matched_agent_id IS NULL AND subagent_type = ?
   ORDER BY transcript_index ASC LIMIT 1
3. if found:
   UPDATE task_spawns SET matched_agent_id = ? WHERE id = ?
   UPDATE subagents SET role = ?, role_source = 'task_match', task_match_index = ?
   COMMIT
   return role
4. else:
   COMMIT
   return None
```

## Claimパターン詳細

### claim_next_unprocessed

```
1. BEGIN EXCLUSIVE
2. SELECT * FROM subagents
   WHERE session_id = ? AND startup_processed = 0
   ORDER BY created_at ASC
3. count = len(results)
   - 0件: COMMIT, return None (subagentではない or 全処理済み)
   - 1件: 排他消去法で確定 (100%正確)
   - 2件以上: FIFO (最古を選択, 蓋然性ベース)
4. target = results[0]
5. UPDATE subagents
   SET startup_processed = 1, startup_processed_at = ?
   WHERE agent_id = ?
6. COMMIT
7. return SubagentRecord(target)  # UPDATE前の状態（startup_processed=0）を返却
```

### 正確性の分析

| 並列数 | 識別方式 | 正確性 |
|--------|---------|--------|
| 1 | 排他消去法 | 100% |
| 2 | 1つ目Claim後、2つ目は排他消去 | 実用上100%（1つ目のFIFO順序依存） |
| 3+ | FIFO | 蓋然性ベース。SubagentStart順≒PreToolUse順の前提 |

最悪ケース: ROLEの入れ違い（testerにscribe規約注入等）。規約注入自体は行われるため、致命的ではない。

## 影響範囲・変更計画

### 新規作成

| ファイル | 内容 |
|---------|------|
| `src/infrastructure/db/nagger_state_db.py` | DB接続管理・スキーマ・マイグレーション |
| `src/infrastructure/db/subagent_repository.py` | subagent + task_spawns操作 |
| `src/infrastructure/db/session_repository.py` | session操作 |
| `src/infrastructure/db/hook_log_repository.py` | hook_log操作 |
| `src/infrastructure/db/__init__.py` | エクスポート |
| `src/domain/models/records.py` | SubagentRecord, SessionRecord等 |

### 変更

| ファイル | 変更内容 |
|---------|---------|
| `src/domain/hooks/subagent_event_hook.py` | SubagentMarkerManager → SubagentRepository |
| `src/domain/hooks/session_startup_hook.py` | should_process/process内のマーカー操作 → DB操作、Claimパターン導入 |
| `src/domain/hooks/base_hook.py` | is_session_processed_context_aware → SessionRepository |
| `src/domain/hooks/compact_detected_hook.py` | マーカーリネーム → DB expire |
| `.claude-nagger/.gitignore` | state.db追加（新規作成） |
| テスト全般 | fixture変更（tmp_marker_dir → テスト用DB） |

### 削除候補（移行完了後）

| ファイル | 理由 |
|---------|------|
| `src/domain/services/subagent_marker_manager.py` | SubagentRepository に置換 |

## マイグレーション戦略

1. 新クラス体系を実装（既存と並行）
2. hook内の呼び出しを新クラスに切り替え
3. テスト全面更新
4. 旧SubagentMarkerManager削除
5. /tmp内の旧マーカーファイルは自然消滅に任せる（明示的削除不要）
6. 並行期間の安全性: 新コードは旧マーカーファイルを参照しない設計のため、切り替え時の不整合は発生しない

## テスト戦略

### 単体テスト
- NaggerStateDB: スキーマ作成、マイグレーション、WAL設定
- SubagentRepository: 全メソッド + 並列Claimのスレッドセーフ性
- SessionRepository: 全メソッド + トークンベース判定
- HookLogRepository: 記録・照会

### 結合テスト
- SubagentStart → PreToolUse → SubagentStop フルフロー
- 並列subagent（2並列、3並列）のClaim正確性
- Compact検知時のDB状態遷移
- task_spawnsマッチング（同一agent_type複数、異なるROLE）

### 回帰テスト
- 単一subagent時の既存動作維持
- メインエージェント（subagentなし）の動作維持

## 既知のリスクと限界

| リスク | 影響 | 緩和策 |
|-------|------|--------|
| FIFO順序不一致 | ROLE入れ違い | task_spawnsマッチングで軽減。最悪でも規約注入自体は行われる |
| SQLiteファイルロック | hook並行実行時の待ち | WAL + timeout=5s。hookは数ms〜数十msで完了 |
| DB破損 | 状態喪失 | WALジャーナリング保護。最悪DB再作成（一時データのみ） |
| SubagentStart fire-and-forget | マーカー作成前のPreToolUse | 現行と同じ制約。DBアトミック操作で中途半端状態は排除 |
| transcript解析の脆弱性 | ROLE取得失敗 | subagent_defaultフォールバック維持 |
| SubagentStart非公式性 | Claude Codeアップデートで破壊的変更の可能性 | イベント廃止時はPreToolUseのみでsubagent検出（現行is_subagent_active相当）にフォールバック。SubagentStart依存ロジックを分離し、差し替え容易な設計とする |

## 関連チケット

- #5934: 並列subagent対応（Feature）
- #5935: 並列subagent時のマーカー対応付け・ROLE解析の正確性（UserStory）
- #5936: 並列subagent起動時にSessionStartupHookが誤ったROLE規約を注入する（Bug）
- #5862: 実環境subagentでROLE識別が機能せずsubagent_defaultにフォールバック（Bug、修正済み）
- #5933: base_hook.pyセッション管理リファクタリング（技術負債）
