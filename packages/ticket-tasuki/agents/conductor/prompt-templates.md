# Conductor用promptテンプレート

## 概要

Conductorパターンの最小構成: **Conductor(Leader) + scribe + coder**

- Task tool で subagent を呼び出す（`subagent_type: "general-purpose"`）
- prompt 先頭に必ず `[ROLE:xxx]` を付与する
- 各 role の規約は `agents/conductor/{role}.md` を参照

## 委譲テンプレート

各ロールの委譲テンプレートは以下を参照:

**マスター**: `skills/tasuki-delegate/SKILL.md`

対応ロール: coder / tester / researcher / scribe

## タスク遷移フロー

Conductor が TaskCreate/TaskUpdate/TaskList で内部進捗を管理する:

```
1. TaskCreate で全子タスクを作成（status: pending）
2. TaskUpdate で依存関係を設定（addBlockedBy）
3. 各タスク実行時:
   a. TaskUpdate で status: in_progress に変更
   b. Task tool で subagent を呼び出し
   c. レビュー後、TaskUpdate で status: completed に変更
4. TaskList で次の未ブロックタスクを確認
```

## blockedBy 依存関係パターン例

典型的な UserStory 実行時:

```
TaskCreate: "技術調査・設計検討"     → id: 1 (blockedBy: なし)
TaskCreate: "実装"                  → id: 2 (blockedBy: [1])
TaskCreate: "テストケース作成・実行"   → id: 3 (blockedBy: [2])
TaskCreate: "ドキュメント更新"        → id: 4 (blockedBy: [2])
```

- id:3 と id:4 は id:2 完了後に並行実行可能
- 依存関係は TaskUpdate の addBlockedBy で宣言
