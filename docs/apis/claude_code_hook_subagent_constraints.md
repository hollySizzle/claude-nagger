# Claude Code Hook API: Subagent制約

調査日: 2026/02/18 (v2.1.45で再検証)

## 問題の2層構造

### 層A: PreToolUse hookでleader/subagent区別不能

PreToolUse入力フィールド（8フィールド）にagent識別情報が不在。

| 提供フィールド | 不在フィールド |
|---|---|
| tool_name, tool_input, session_id, transcript_path, hookType等 | agent_name, agent_id, agent_context, agent_type, agent_transcript_path |

- session_id・環境変数(70件)もleader/subagent間で同一値
- hookはセッション単位適用 → leaderのhookがsubagentに一律適用
- 対処済: Plan C (commit f2bc052) でhooks.jsonからmatcher削除 → ソフト制約化
- 経緯: agent_nameフィルタ(commit 4407449)を試みたが、PreToolUseにagent_name自体が来ないため機能せず

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

## GitHub Issue状況

リポジトリ: `https://github.com/anthropics/claude-code/issues/`

| Issue | Status | 内容 | thumbup |
|---|---|---|---|
| #6885 | OPEN | 元祖リクエスト: subagentのhookイベントにagent情報追加 | 16 |
| #15998 | CLOSED(重複) | agent_id/type追加提案。ボットにより#6885等の重複として自動クローズ。**未実装** | - |
| #16424 | OPEN | 統合追跡Issue: hook API全般の改善（より包括的提案） | 8 |

- #15998は実装ではなく重複自動クローズ（2026-01-01）。リンクされたPR/コミットなし
- v2.1.45(2026-02-17)時点でPreToolUseフィールド変化なし（8フィールドのまま）

## claude-nagger側の現行対処

| 対処 | チケット | commit | 内容 |
|---|---|---|---|
| ROLE識別機構 | #5825 | 複数 | [ROLE:xxx]タグ+transcript解析+マーカーroleフィールド |
| 実環境ROLE修正 | #5861 | 98e789d, ebcc090 | SubagentStart時のrole解析バグ修正 |
| 並列subagent対応 | #5935 | 複数 | SQLite状態管理(Registry+2段階Claim) |
| タイミング問題 | #5947 | 9c78df4 | ハイブリッドアプローチ(SubagentStart+PreToolUse補正) |
| Plan C | #6170/6205 | f2bc052 | hooks.jsonからmatcher削除(ソフト制約化) |

## 改善見込み判定

| 問題 | 待てば改善? | 根拠 |
|---|---|---|
| hook区別(層A) | **不明（未実装）** | #15998は重複クローズで未実装。#6885/#16424がOPENだが実装時期不明 |
| role=(none)(層B) | **いいえ** | claude-nagger/運用側の問題。[ROLE:xxx]タグ付与の仕組みが必要 |

## 今後の対応方針

- **層A**: #6885/#16424でagent_context追加が実現すれば、hooks.jsonのmatcher復活+物理制約再導入が可能（#6171で準備中）。ただし実装時期は未定
- **層B**: config.yamlのsubagent_types規約で[ROLE:xxx]タグ付与を強制する運用改善が必要

## 関連ファイル

- hooks仕様: @docs/apis/ClaudeCodeHooks.md
- アーキテクチャ: @docs/specs/architecture.md
- 並列subagent設計: @docs/specs/parallel_subagent_state_management.md
