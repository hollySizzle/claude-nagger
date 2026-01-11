# Claude Code Hooks API対応 - チケット一覧

**バージョン**: Claude Code Hooks API対応 (v2.0.0)
**期限**: 2026-01-20

---

## UserStory 4: 終了コードの明確化
**Feature**: PreToolUseフック (#3828)
**優先度**: 高

### 概要
終了コード0/2/その他の使い分けを明確化

### 背景
現状は曖昧。APIは「終了コード2=ブロッキングエラー」と明確に定義

### 受け入れ条件
- [ ] 終了コード定数定義（EXIT_SUCCESS=0, EXIT_BLOCK=2, EXIT_ERROR=1）
- [ ] ブロック時は終了コード2 + stderr使用に統一
- [ ] JSON出力時は終了コード0 + stdout
- [ ] 既存コードの`sys.exit()`呼び出し整理

### Task
1. 終了コード定数定義
2. ブロック時の出力修正（終了コード2 + stderr）
3. JSON出力時の明確化（終了コード0 + stdout）
4. 既存コードの修正

### 参考
- API Doc: /workspace/docs/apis/ClaudeCodeHooks.md (624-646行)

---

## UserStory 2: 環境変数の活用
**Feature**: 設定・拡張 (#3831)
**優先度**: 中

### 概要
`CLAUDE_PROJECT_DIR`, `CLAUDE_CODE_REMOTE`を活用してコードをシンプル化

### 背景
現状は`cwd`を手動処理し`os.getcwd()`にフォールバック

### 受け入れ条件
- [ ] `CLAUDE_PROJECT_DIR`でパス正規化をシンプル化
- [ ] `CLAUDE_CODE_REMOTE`でリモート実行時の挙動変更
- [ ] BaseHookに`project_dir`/`is_remote`プロパティ追加
- [ ] 既存の`normalize_file_path`を環境変数ベースに修正

### Task
1. BaseHookにプロパティ追加（project_dir, is_remote）
2. パス正規化の修正
3. リモート判定の活用

### 参考
- API Doc: /workspace/docs/apis/ClaudeCodeHooks.md (1056-1058行)

---

## UserStory 1: hookSpecificOutput形式の完全対応
**Feature**: PreToolUseフック (#3828)
**優先度**: 高

### 概要
新JSON出力形式`hookSpecificOutput`を完全サポート

### 背景
現状は`permissionDecision`のみ。以下が未実装:
- `updatedInput`: ツール入力を修正可能
- `additionalContext`: コンテキストに情報追加
- `continue`: 処理続行制御
- `suppressOutput`: 詳細モードでの出力抑制
- `ask` decision: ユーザー確認を求める

### 受け入れ条件
- [ ] `updatedInput`で危険なコマンドを安全な代替に置換可能
- [ ] `additionalContext`で規約情報を注入可能
- [ ] `ask`で確認を求める判定を実装
- [ ] `suppressOutput`オプションを実装
- [ ] 既存テストの更新

### Task
1. HookResponse型定義（updated_input, additional_context, continue, suppress_output）
2. `updatedInput`実装
3. `additionalContext`実装
4. `ask` decision実装
5. 出力メソッド刷新

### 参考
- API Doc: /workspace/docs/apis/ClaudeCodeHooks.md (679-711行)

---

## UserStory 3: permission_modeによるスマートスキップ
**Feature**: PreToolUseフック (#3828)
**優先度**: 中

### 概要
入力JSONの`permission_mode`フィールドを活用

### 背景
現状は完全に無視。APIは以下のモードを提供:
- `default`: 通常モード
- `plan`: 計画モード
- `acceptEdits`: 編集自動承認
- `dontAsk`: 確認なし
- `bypassPermissions`: 権限バイパス

### 受け入れ条件
- [ ] `bypassPermissions`モードでは全てスキップ
- [ ] `dontAsk`モードでは警告のみ（ブロックしない）
- [ ] `plan`モードでは規約確認を厳格化（オプション）
- [ ] モード別の挙動を設定可能にする

### Task
1. モード検出実装
2. スキップロジック（bypassPermissions）
3. 警告のみモード（dontAsk）
4. 設定化

### 参考
- API Doc: /workspace/docs/apis/ClaudeCodeHooks.md (483行)

---

## UserStory 5: テスト拡充
**Feature**: 品質・テスト (#3847)
**優先度**: 高

### 概要
新スキーマ・終了コード・環境変数のテスト追加

### 背景
現状のスキーマバリデータは`ask`未対応、終了コードテスト不足

### 受け入れ条件
- [ ] スキーマバリデータに`ask`追加、全イベント名対応
- [ ] 終了コード0/2/1の挙動テスト
- [ ] 環境変数のモックテスト
- [ ] permission_modeテスト
- [ ] updatedInputテスト

### Task
1. スキーマバリデータ更新
2. 終了コードテスト
3. 環境変数モックテスト
4. permission_modeテスト
5. updatedInputテスト

---

## UserStory 6: デバッグ機能の改善（オプション）
**Feature**: 設定・拡張 (#3831)
**優先度**: 低

### 概要
Claude Code `--debug`モードとの連携

### 背景
現状はログが分散。構造化ログで統合可能

### 受け入れ条件
- [ ] 構造化ログ（JSON形式）実装
- [ ] ログ出力先統一
- [ ] デバッグモード検出

### Task
1. 構造化ログ実装
2. ログ出力先統一
3. デバッグモード検出

---

## 依存関係

```
UserStory 4 (終了コード) ──┐
                          ├──→ UserStory 1 (hookSpecificOutput)
UserStory 2 (環境変数) ───┘
                          │
                          ▼
                   UserStory 3 (permission_mode)
                          │
                          ▼
                   UserStory 5 (テスト)
```

## 推奨実装順序

1. UserStory 4: 終了コード明確化（基盤）
2. UserStory 2: 環境変数活用（基盤）
3. UserStory 1: hookSpecificOutput完全対応（主機能）
4. UserStory 3: permission_mode対応（拡張）
5. UserStory 5: テスト拡充（品質保証）
6. UserStory 6: デバッグ改善（オプション）
