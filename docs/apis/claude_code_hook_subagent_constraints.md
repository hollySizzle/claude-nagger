# Claude Code Hook API: Subagent制約

調査日: 2026/02/18 (v2.1.45), 2026/02/26 (v2.1.62), 2026/03/04 (agent_id方式正式採用)

## 問題の2層構造

### 層A: PreToolUse hookでleader/subagent区別

**現行正式手法: agent_idベース判定（issue_7350〜7353）**

`input_data['agent_id']`の有無でleader/subagentを判定。

```python
# leader判定
is_leader_tool_use(input_data: dict) -> bool
# agent_id不在 → True（leader）
# agent_id存在 → False（subagent）

# agent_id取得
find_caller_agent_id(input_data: dict) -> Optional[str]
# input_data.get('agent_id') を返却
```

フォールバック方針: agent_id不在 → subagent扱い（安全側）、input_dataがdictでない場合も同様。

実装: `src/domain/services/leader_detection.py`

旧方式（SubagentRepository.is_leader_tool_use()ラッパー）はissue_7350で削除済み。

### 層B: subagentのrole識別不能（role=(none)問題）

- 前回セッション(2026/02/17)で16件全subagentがrole=(none)
- 原因: Task promptに`[ROLE:xxx]`タグ未付与 → task_spawnsテーブル未登録 → マッチング不能
- claude-nagger側ROLE識別機構（#5825, #5861, #5935, #5947で実装済）は正常動作するが、タグがないと発動しない
- `get_stats()`がrole=NULLを`(none)`と表示

## Hook別提供フィールド

### SubagentStart

| 提供 | 不在 |
|---|---|
| session_id, transcript_path, agent_id, agent_type | agent_transcript_path, permission_mode |

### SubagentStop

| 提供 |
|---|
| session_id, transcript_path, agent_id, agent_type, agent_transcript_path, permission_mode |

### agent_progressイベント（親transcript内）

- トップレベル: type="progress", parentToolUseID, toolUseID
- data内: type="agent_progress", agentId
- タイミング: SubagentStart発火の約142ms後に書き込み（SubagentStart時点では未存在の場合あり）

## GitHub Issue状況 (2026-02-26更新)

リポジトリ: `https://github.com/anthropics/claude-code/issues/`

| Issue | Status | 内容 |
|---|---|---|
| #6885 | OPEN | 元祖リクエスト: subagentのhookイベントにagent情報追加 |
| #14859 | OPEN | Agent Hierarchy in Hook Events + SubagentStart Hook（活発、+1多数） |
| #15998 | CLOSED(重複) | agent_id/type追加提案。ボットにより自動クローズ。**未実装** |
| #16424 | OPEN | 統合追跡Issue: hook API全般の改善 |
| #21460 | OPEN | **[SECURITY]** PreToolUse hookがsubagent tool callsで発火しない |
| #23983 | OPEN | PermissionRequest hookがAgent Teamsで発火しない |
| #29068 | OPEN | Include agent_id in all hook event inputs (2026-02-26起票) |

- v2.1.4→v2.1.62(全リリースノート精査): PreToolUseフィールド変化なし
- Anthropic staffのコメントなし。実装時期不明
- Agent SDKは内部でtool_use_id↔agent関連を追跡済み（#16424 @mr-lee指摘）

## claude-nagger側の対処履歴

| 対処 | チケット | commit | 内容 |
|---|---|---|---|
| ROLE識別機構 | #5825 | 複数 | [ROLE:xxx]タグ+transcript解析+マーカーroleフィールド |
| 実環境ROLE修正 | #5861 | 98e789d, ebcc090 | SubagentStart時のrole解析バグ修正 |
| 並列subagent対応 | #5935 | 複数 | SQLite状態管理(Registry+2段階Claim) |
| タイミング問題 | #5947 | 9c78df4 | ハイブリッドアプローチ(SubagentStart+PreToolUse補正) |
| Plan C | #6170/6205 | f2bc052 | hooks.jsonからmatcher削除(ソフト制約化) |
| **agent_id方式移行** | #7350-7353 | 複数 | transcript走査全廃、input_data['agent_id']ベース判定に統一 |

## 歴史的経緯: 旧leader判定手法

### Butanium方式（tool_use_id transcript検索）— 廃止

#16424 @Butanium提案。PreToolUseの`tool_use_id`でmain transcript(JSONL)をparse → `type="tool_use"` + `id==target`検索。見つかればleader、なければsubagent。

- v2.1.62実測: tool_use.id厳密マッチは完全排他的（main: 86件, subagent: 16件, 重複0）
- 単純grepは不可（substring出現あり）、JSON parse + 厳密マッチ必須
- レイテンシ: worst case ~10ms
- 制約: transcript構造はundocumented（バージョン変更リスク）
- 詳細: Redmine US #6928
- **廃止理由**: agent_id方式でtranscript走査が不要になった（issue_7350-7353）

### coygeek方式（Task tool_use逆順走査）— 廃止

leader transcriptをJSON parse → Task/Agent tool_useの存在を逆順走査してleader/subagent判定。

- 実装: `src/domain/services/leader_detection_coygeek.py`（削除済み）
- テスト: `tests/test_leader_detection_coygeek.py`（削除済み）
- **廃止理由**: agent_id方式でtranscript走査が不要になった（issue_7350-7353）

## 改善見込み判定

| 問題 | 待てば改善? | 根拠 |
|---|---|---|
| hook区別(層A) | **解決済み** | agent_id方式で判定可能（issue_7350-7353） |
| role=(none)(層B) | **いいえ** | claude-nagger/運用側の問題。[ROLE:xxx]タグ付与の仕組みが必要 |

## 今後の対応方針

- **層A**: agent_id方式で解決済み。Anthropic公式対応(#16424)は引き続き追跡
- **層A(物理制限)**: agent frontmatter disallowedTools(#6171)で対処可能（subagentのみ）
- **層B**: config.yamlのsubagent_types規約で[ROLE:xxx]タグ付与を強制する運用改善が必要
- **追跡**: Redmine Feature #6926「Hook API subagent識別 追跡」で管理

## 関連ファイル

- hooks仕様: @docs/apis/ClaudeCodeHooks.md
- アーキテクチャ: @docs/specs/architecture.md
- 並列subagent設計: @docs/specs/parallel_subagent_state_management.md
- 追跡Feature: Redmine #6926
