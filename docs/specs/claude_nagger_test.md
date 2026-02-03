# claude-nagger テスト仕様書

## テスト戦略

### テストピラミッド

| 層 | 比率 | 手法 | 目的 |
|---|---|---|---|
| ユニット | 65% | mock/patch | 単体機能・メソッド検証 |
| 統合 | 20% | 実ファイルシステム | モジュール間連携 |
| E2Eリプレイ | 15% | subprocess+フィクスチャ | hookスクリプト実行の実環境検証 |

### 実行コマンド

```bash
python3 -m pytest tests/ -v                    # 全テスト
python3 -m pytest tests/ -k "keyword" -v       # キーワード指定
python3 -m pytest --cov=src --cov-report=term-missing  # カバレッジ
python3 -m pytest tests/test_hook_schema_validation.py::TestSessionStartupHookReplay -v  # E2Eリプレイ
```

## テストファイル一覧

### domainレイヤ - hooks

| ファイル | 対象 | 種別 | クラス数 | 概要 |
|---|---|---|---|---|
| test_base_hook.py | base_hook.py | ユニット | 20+ | 初期化,ログ,マーカー管理,終了コード,レスポンス型 |
| test_session_startup_hook.py | session_startup_hook.py | ユニット | 16 | 設定読込,マーカー,処理判定,メッセージ構築,規約提案 |
| test_implementation_design_hook.py | implementation_design_hook.py | ユニット | 12 | パス正規化,ツール検出,閾値,マーカー |
| test_compact_detected_hook.py | compact_detected_hook.py | ユニット | 1 | compact検出 |
| test_test_hook.py | test_hook.py | ユニット | 1 | テストフック |

### domainレイヤ - マッチャー/サービス

| ファイル | 対象 | 種別 | 概要 |
|---|---|---|---|
| test_file_convention_matcher.py | ファイルパターンマッチング | ユニット | glob/正規表現マッチ |
| test_command_convention_matcher.py | コマンドパターンマッチング | ユニット | コマンド文字列マッチ |
| test_match_test.py | マッチング全般 | ユニット | 複合マッチ検証 |
| test_rule_suggester.py | rule_suggester.py | ユニット | ルール提案ロジック |
| test_hook_manager.py | hook_manager.py | ユニット(8) | フック登録・実行管理 |

### applicationレイヤ

| ファイル | 対象 | 種別 | クラス数 | 概要 |
|---|---|---|---|---|
| test_suggest_rules.py | suggest_rules.py | ユニット | 5 | ルール提案CLI |
| test_suggest_rules_trigger.py | suggest_rulesトリガー | ユニット | - | トリガー条件 |
| test_install_hooks.py | install_hooks.py | ユニット+統合+E2E | 20+ | ディレクトリ作成,settings更新,マージ,dry-run,CLI統合 |
| test_cli.py | cli.py | ユニット+統合 | 4 | version,install-hooks,notify,subcommands |
| test_base_cli.py | base_cli.py | ユニット | 2 | 基底CLIクラス |

### infrastructureレイヤ

| ファイル | 対象 | 種別 | クラス数 | 概要 |
|---|---|---|---|---|
| test_config_manager.py | config_manager.py | ユニット+統合 | 30+ | 優先順位,YAML/JSON/JSON5,環境変数展開,secrets |
| test_hook_executor.py | hook_executor.py | ユニット | 10 | マッチング,subprocess実行,内蔵フック |
| test_discord_notifier.py | Discord通知 | ユニット | - | 通知送信 |

### sharedレイヤ

| ファイル | 対象 | 種別 | クラス数 | 概要 |
|---|---|---|---|---|
| test_session_manager.py | session_manager.py | ユニット | 15 | セッションID,エージェント名,ツール情報 |
| test_structured_logging.py | structured_logging.py | ユニット | 10 | JSON formatter,ロガー設定 |

### クロスカッティング

| ファイル | 対象 | 種別 | クラス数 | 概要 |
|---|---|---|---|---|
| test_subagent_override.py | MarkerManager,override解決 | ユニット+統合 | 10 | 辞書操作,マーカーCRUD,override解決 |
| test_hook_schema_validation.py | フック出力スキーマ準拠 | ユニット+統合+E2E | 15+ | HookSchemaValidator,HookRunner,フィクスチャ検証,リプレイ |
| test_permission_mode.py | permission_mode機能 | ユニット+フィクスチャ | 5 | 各permission_modeの動作検証 |
| test_sanitizer.py | sanitizer.py | ユニット | 1 | フィクスチャサニタイズ |
| test_diagnose.py | 診断機能 | ユニット | - | 診断出力 |

## フィクスチャ体系

### ディレクトリ構成

```
tests/fixtures/claude_code/
├── permission_mode/          # permission_mode別入力 (5ファイル)
│   # default, plan, acceptEdits, dontAsk, bypass
└── pre_tool_use/             # ツール別PreToolUse入力
    ├── bash/                 # 13ファイル (通常12 + subagent1)
    ├── edit/                 # 7ファイル
    ├── read/                 # 3ファイル (通常2 + subagent1)
    ├── write/                # 2ファイル
    ├── task/                 # 1ファイル (subagent spawn)
    └── mcp__redmine_*/       # 6ファイル (Redmine MCP各ツール)
```

### フィクスチャ管理

- **キャプチャ**: `scripts/capture_fixture.py --sanitize`でClaude Codeの実hook入力JSONを記録
- **サニタイズ**: ホームディレクトリ→testuser、セッションID→ゼロ埋め、APIキー除去
- **用途**: E2Eリプレイテスト・スキーマ検証の入力データとして使用

## E2Eリプレイテスト

### 仕組み

1. **HookRunner**: hookスクリプトをsubprocess.runで実行
   - `run_with_fixture(path)`: フィクスチャJSONをstdin入力
   - `run_with_data(dict)`: 辞書→JSON→stdin入力
   - 出力をHookSchemaValidatorでClaude Code公式スキーマ準拠チェック

2. **TestSessionStartupHookReplay** (issue_5779):
   - SubagentMarkerManagerで実ディレクトリにマーカー作成
   - フィクスチャ→session_startup_hook subprocess実行
   - 名前空間マッチング(`ticket-tasuki:coder`→`coder`)のE2E検証

3. **TestHooksWithCapturedFixtures**:
   - 全フィクスチャを各hookに流して正常終了・スキーマ準拠を確認

### Claude Code公式hookスキーマ

| フィールド | 型 | 説明 |
|---|---|---|
| decision | "block" \| "allow" \| "deny" \| "ask" | permissionDecision |
| reason | string | ブロック理由テキスト |
| hookSpecificOutput | object | フック固有出力 |
| hookEventName | string | PreToolUse, PostToolUse, Notification, Stop, SessionStart, SessionEnd等 |

### 終了コード規約

| コード | 意味 |
|---|---|
| 0 | 成功(出力なし or 許可) |
| 1 | エラー |
| 2 | ブロック(出力あり) |

## Issue対応テストマップ

| Issue | テストファイル | 検証内容 |
|---|---|---|
| #3876 | test_config_manager.py | CI環境設定優先順位 |
| #3889 | test_config_manager.py | YAML設定読込 |
| #3910 | test_install_hooks.py | config.yaml自動生成 |
| #4009,#4010 | test_install_hooks.py | フックマージ、SubagentStart/Stop |
| #5332 | test_base_hook.py等 | 例外ログ出力 |
| #5778 | test_base_hook.py | output_response()非PreToolUse分岐 |
| #5779 | test_hook_schema_validation.py, test_subagent_override.py | 名前空間マッチング |
| #5862 | test_subagent_override.py | is_session_processed_context_aware無条件バイパス、マーカー状態別検証 |

## テストアンチパターン

### AP-1: should_process()直接呼び出しのみのテスト

**問題**: `should_process()` を直接呼び出すテストは、`run()` メソッド内のガード条件（`is_session_processed_context_aware`, `should_skip_by_permission_mode` 等）を検証できない。実環境では `run()` が呼ばれるため、ガード条件で早期リターンし `should_process()` に到達しないケースを見逃す。

**事例**: issue #5862 - `is_session_processed_context_aware` の条件付きバイパスが実環境で機能せず、テスト全824件パスしたが実環境で失敗。

**対策**: セッションマーカー存在状態での `run()` 経由フルパステストを必須とする。特に以下の組み合わせ:
- セッションマーカー存在 + subagentマーカー存在
- セッションマーカー存在 + subagentマーカー非存在
- セッションマーカー非存在（初回）

### AP-2: hook間連携のモック過剰使用

**問題**: SubagentStart → PreToolUse 間のデータフローをテストする際、マーカーを手動作成してSubagentStart処理をスキップすると、実際のhook間連携パスが未検証になる。

**対策**: `TestCrossHookRolePropagation` のように、SubagentStart処理（`subagent_event_main()`）を実行してマーカーを作成し、その後PreToolUseの `should_process()` を呼ぶ連携テストを必須とする。
