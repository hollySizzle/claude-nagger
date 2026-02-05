# task_spawnsテーブル調査結果

## 1. テーブルスキーマ定義（v1/v2）

### スキーマ v1（初期）
```sql
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
```

### マイグレーション v1→v2（issue_5947）
- `tool_use_id` カラムが追加
- 新インデックス: `CREATE INDEX idx_task_spawns_tool_use_id ON task_spawns(tool_use_id)`

### 最終スキーマ v2
- id: 自動採番
- session_id: セッションID（FK）
- transcript_index: トランスクリプト行番号
- subagent_type: タスク対象subagent種別（e.g., "coder", "reviewer"）
- role: [ROLE:xxx]タグから抽出した役割値
- prompt_hash: SHA256(prompt)[:16]
- tool_use_id: Task tool_useのID（issue_5947で追加）
- matched_agent_id: マッチ済みのagent_id（FK）
- created_at: ISO8601 UTC

### インデックス
- `idx_task_spawns_session`: session_id
- `idx_task_spawns_unmatched`: (session_id, matched_agent_id) WHERE matched_agent_id IS NULL
- `idx_task_spawns_tool_use_id`: tool_use_id（v2以降）

---

## 2. INSERT処理（role値の登録箇所）

### 処理フロー
**SubagentStart→SubagentEventHook→subagent_event_hook.main()**

```
subagent_event_hook.py:main()
  ↓
SubagentRepository.register(agent_id, session_id, agent_type)  # subagent登録
  ↓
SubagentRepository.register_task_spawns(session_id, transcript_path)
  ↓
  親transcriptを解析：
  - トップレベル type='assistant' かつ
  - message.content[] 内の type='tool_use' name='Task' を抽出
  - tool_input から subagent_type, prompt を取得
  - tool_use.id を取得（issue_5947）
  ↓
  正規表現で [ROLE:xxx] を抽出
    - pattern = r"\[ROLE:([^\]]+)\]"
    - ROLEなしはスキップ（issue_5947）
  ↓
  INSERT OR IGNORE (冪等性)：
    - role = 抽出値（NULL不可）
    - tool_use_id = content_item.get("id")
    - prompt_hash = SHA256(prompt)[:16]
    - created_at = datetime.now(UTC).isoformat()
```

### Key Point
- **role値の決定時期**: 親transcriptのTask tool_use時
- **登録タイミング**: SubagentStart発生時（transcript_pathが提供される場合）
- **冪等性保証**: UNIQUE(session_id, transcript_index)で重複排除
- **ROLEバリデーション**: ROLEタグがないTask tool_useは全スキップ

---

## 3. フォールバックマッチング処理（ROLEマッチングロジック）

### match_task_to_agent() のアルゴリズム（issue_5947改善版）

#### Step 0: agent_progressベースの正確マッチング（優先）
```
IF transcript_path が提供されている:
  ├─ find_parent_tool_use_id(transcript_path, agent_id)
  │   └─ agent_progressイベントから parentToolUseID を検索
  ├─ find_task_spawn_by_tool_use_id(parent_tool_use_id)
  │   └─ 該当task_spawnを取得
  └─ task_spawn.matched_agent_id IS NULL なら
      └─ UPDATE task_spawns SET matched_agent_id = agent_id
      └─ UPDATE subagents SET role = ..., role_source = 'task_match'
      └─ return role（正確マッチ成功）
ELSE
  └─ フォールバックへ
```

#### Step 1: roleパラメータを指定されている場合
```sql
SELECT id, role, transcript_index FROM task_spawns
WHERE session_id = ? AND role = ? AND matched_agent_id IS NULL
ORDER BY transcript_index ASC
LIMIT 1
```
- roleで完全一致マッチング
- 最古エントリを取得

#### Step 2: roleマッチなければsubagent_typeでマッチ
```sql
SELECT id, role, transcript_index FROM task_spawns
WHERE session_id = ? AND subagent_type = ? AND role IS NOT NULL AND matched_agent_id IS NULL
ORDER BY transcript_index ASC
LIMIT 1
```
- **重要**: `role IS NOT NULL` 条件あり（ROLEありエントリのみ）
- subagent_typeでマッチング
- 最古エントリを取得

#### Step 3: マッチ結果の処理
```
IF row FOUND:
  └─ BEGIN EXCLUSIVE （アトミックな更新）
  ├─ UPDATE task_spawns SET matched_agent_id = agent_id WHERE id = ?
  ├─ UPDATE subagents SET role = ?, role_source = 'task_match', task_match_index = ?
  └─ COMMIT
  return matched_role
ELSE
  return None
```

### マッチング優先度
1. **agent_progress正確マッチ** (tool_use_idベース、最も正確)
2. **roleパラメータマッチ** (完全一致)
3. **subagent_typeマッチ** (フォールバック、ROLEありのみ)
4. **マッチなし**: None

### role_sourceの値
- `'task_match'`: match_task_to_agent()で設定
- `'retry_match'`: retry_match_from_agent_progress()で設定（case D簡易版）
- `'transcript_parse'`: SessionStartupHook._parse_role_from_transcript()で設定

---

## 4. バリデーション・クリーンアップ処理

### 既存バリデーション

#### register_task_spawns()内
- ファイル存在確認
- JSON解析エラースキップ
- type='assistant' のみ対象
- tool_use name='Task' のみ対象
- [ROLE:xxx] パターン検出
- **ROLEなしエントリはスキップ** (issue_5947)

### クリーンアップ処理

#### 1. cleanup_session(session_id) → int
```sql
DELETE FROM subagents WHERE session_id = ?
```
- セッション全削除（subagentのみ）
- task_spawnsは削除されない
- returns: 削除件数

#### 2. cleanup_old_task_spawns(session_id, keep_recent=100) → int
```sql
DELETE FROM task_spawns
WHERE session_id = ? AND matched_agent_id IS NULL
AND id NOT IN (
  SELECT id FROM task_spawns
  WHERE session_id = ?
  ORDER BY id DESC
  LIMIT ?
)
```
- 未マッチ(`matched_agent_id IS NULL`)で古いエントリ削除
- 最新keep_recent件を保持
- returns: 削除件数

#### 3. cleanup_null_role_task_spawns() → int
```sql
DELETE FROM task_spawns WHERE role IS NULL
```
- **初回マイグレーション用**（issue_5947）
- 既存の role=NULL エントリを全削除
- register_task_spawnsがROLEありのみ登録するため不要データクリーンアップ
- returns: 削除件数

### subagent削除時の処理

#### unregister(agent_id)
```sql
DELETE FROM task_spawns WHERE matched_agent_id = agent_id
DELETE FROM subagents WHERE agent_id = agent_id
```
- 関連task_spawnsもクリーンアップ
- 一括トランザクション

---

## 5. データライフサイクル管理

### Phase 1: Task tool_use登録（SubagentStart時）
1. **register_task_spawns()** → task_spawns テーブルに INSERT
   - role値は [ROLE:xxx] タグから抽出
   - matched_agent_id = NULL（未マッチ）
   - tool_use_idを記録

### Phase 2: ROLEマッチング（SubagentStart時 or SessionStartupHook時）
1. **match_task_to_agent()** → agent_progressベースか従来マッチング
2. **task_spawns.matched_agent_id** を更新（未→agent_id）
3. **subagents.role** を更新（NULL→matched_role）
4. role_source記録（'task_match' or 'retry_match'）

### Phase 3: フォールバック（SessionStartupHook時、role=Noneの場合）
1. **retry_match_from_agent_progress()** → agent_progressから再マッチ試行
2. 失敗時 → **_parse_role_from_transcript()** → transcriptの[ROLE:xxx]から解析
3. **update_role()** → subagents.roleを更新（role_source='transcript_parse'）

### Phase 4: クリーンアップ（セッション終了時）
1. **SubagentStop** → unregister() → 関連レコード削除
2. **自動クリーンアップ** → cleanup_old_task_spawns() （任意実行）
3. **初回マイグレーション** → cleanup_null_role_task_spawns() （一度限り）

---

## 6. 重要な制約・特性

### role値の性質
- task_spawnsテーブル: **NOT NULL（issue_5947より）**
  - ROLEタグなしTask tool_useは登録されない
- subagentsテーブル: **NULL可**
  - マッチング前、またはマッチング失敗時はNULL

### マッチングの排他性（アトミック性）
- BEGIN EXCLUSIVE でロック
- 複数agentの同時マッチングも安全（最初の1つがロック取得）

### 冪等性
- UNIQUE(session_id, transcript_index) で重複INSERT防止
- 同一transcriptの再読み込みで安全

### ログ出力
- StructuredLoggerで詳細ログ
- agent_progress関連の処理は特に詳細ログあり

