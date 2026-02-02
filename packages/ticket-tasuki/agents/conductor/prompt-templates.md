# Conductor用promptテンプレート

## 概要

Conductorパターンの最小構成: **Conductor(Leader) + scribe + coder**

- Task tool で subagent を呼び出す（`subagent_type: "general-purpose"`）
- prompt 先頭に必ず `[ROLE:xxx]` を付与する
- 各 role の規約は `agents/conductor/{role}.md` を参照

## coder 呼び出しテンプレート

Task tool の prompt パラメータに渡す:

```
[ROLE:coder]

## タスク: #{チケット番号} {タスク名}

issue_{チケット番号} の作業を実行してください。

### 実装意図
{なぜこの変更が必要か}

### 対象ファイル
- {ファイルパス1}
- {ファイルパス2}

### 実装指示
{具体的な変更内容}

### 注意事項
- {あれば記載}
```

## scribe 呼び出しテンプレート

```
[ROLE:scribe]

## タスク: {操作内容}

### 操作指示
{具体的なチケット操作内容}

### 対象チケット
- #{チケット番号}: {チケット名}
```

## tester 呼び出しテンプレート

```
[ROLE:tester]

## タスク: #{チケット番号} テスト実行

issue_{チケット番号} のテストを実行してください。

### テスト対象
{テスト対象の仕様・要件}

### 期待動作
- 正常系: {期待結果}
- 異常系: {期待結果}

### テストコマンド
{具体的なテスト実行コマンド}
```

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
