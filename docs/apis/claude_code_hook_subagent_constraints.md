# Claude Code Hook API: Subagent制約

調査日: 2026/02/18 (v2.1.45で再検証), 2026/02/26 (v2.1.62で実測検証追加)

## 問題の2層構造

### 層A: PreToolUse hookでleader/subagent区別不能

PreToolUse入力フィールド（8フィールド）にagent識別情報が不在。

| 提供フィールド | 不在フィールド |
|---|---|
| tool_name, tool_input, session_id, transcript_path, hookType等 | agent_name, agent_id, agent_context, agent_type, agent_transcript_path |

- session_id・環境変数(70件)・**transcript_path**もleader/subagent間で同一値（v2.1.62実測確認済み）
- hookはセッション単位適用 → leaderのhookがsubagentに一律適用
- 対処済: Plan C (commit f2bc052) でhooks.jsonからmatcher削除 → ソフト制約化
- 経緯: agent_nameフィルタ(commit 4407449)を試みたが、PreToolUseにagent_name自体が来ないため機能せず
- **issue_6057のtranscript_path比較は機能しない**: SubagentStart時のleader_transcript_pathとsubagent PreToolUseのtranscript_pathが同一のため常にTrue

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
| #16424 | OPEN | 統合追跡Issue: hook API全般の改善（**tool_use_id回避策あり**） |
| #21460 | OPEN | **[SECURITY]** PreToolUse hookがsubagent tool callsで発火しない |
| #23983 | OPEN | PermissionRequest hookがAgent Teamsで発火しない |
| #29068 | OPEN | Include agent_id in all hook event inputs (2026-02-26起票) |

- v2.1.4→v2.1.62(全リリースノート精査): PreToolUseフィールド変化なし
- Anthropic staffのコメントなし。実装時期不明
- Agent SDKは内部でtool_use_id↔agent関連を追跡済み（#16424 @mr-lee指摘）

## claude-nagger側の現行対処

| 対処 | チケット | commit | 内容 |
|---|---|---|---|
| ROLE識別機構 | #5825 | 複数 | [ROLE:xxx]タグ+transcript解析+マーカーroleフィールド |
| 実環境ROLE修正 | #5861 | 98e789d, ebcc090 | SubagentStart時のrole解析バグ修正 |
| 並列subagent対応 | #5935 | 複数 | SQLite状態管理(Registry+2段階Claim) |
| タイミング問題 | #5947 | 9c78df4 | ハイブリッドアプローチ(SubagentStart+PreToolUse補正) |
| Plan C | #6170/6205 | f2bc052 | hooks.jsonからmatcher削除(ソフト制約化) |

## 回避策: tool_use_id transcript parse (v2.1.62 実測検証済み)

#16424 @Butanium提案。PreToolUseペイロードの`tool_use_id`でmain/subagentを判定。

### 手法
1. PreToolUseの`tool_use_id`を取得
2. main transcript(JSONL)をparse → `type="tool_use"` + `id==target` を検索
3. 見つかった→leader、見つからない→subagent
4. subagent特定: `<session>/subagents/agent-*.jsonl`をparse

### 実測結果 (v2.1.62)
- **tool_use.id厳密マッチは完全に排他的**（main: 86件, subagent: 16件, 重複0）
- 単純grepは不可（substring出現あり）。JSON parse + 厳密マッチ必須
- レイテンシ: worst case **~10ms**

### 制約
- transcript構造はundocumented（バージョン変更リスク）
- 詳細: Redmine US #6928

## 改善見込み判定

| 問題 | 待てば改善? | 根拠 |
|---|---|---|
| hook区別(層A) | **不明（未実装）** | #6885/#16424がOPENだが実装時期不明。Anthropic staffコメントなし |
| role=(none)(層B) | **いいえ** | claude-nagger/運用側の問題。[ROLE:xxx]タグ付与の仕組みが必要 |

## 今後の対応方針

- **層A**: tool_use_id手法(US #6928)で暫定対処可能。Anthropic公式対応(#16424)を待ちつつ採否検討中
- **層A(物理制限)**: agent frontmatter disallowedTools(#6171)で対処可能（subagentのみ）
- **層B**: config.yamlのsubagent_types規約で[ROLE:xxx]タグ付与を強制する運用改善が必要
- **追跡**: Redmine Feature #6926「Hook API subagent識別 追跡」で管理

## 関連ファイル

- hooks仕様: @docs/apis/ClaudeCodeHooks.md
- アーキテクチャ: @docs/specs/architecture.md
- 並列subagent設計: @docs/specs/parallel_subagent_state_management.md
- 追跡Feature: Redmine #6926
