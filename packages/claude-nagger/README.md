# claude-nagger

[![PyPI version](https://badge.fury.io/py/claude-nagger.svg)](https://pypi.org/project/claude-nagger/)
[![Python](https://img.shields.io/pypi/pyversions/claude-nagger.svg)](https://pypi.org/project/claude-nagger/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Claude Code（Anthropic公式CLI）のHooksシステムと統合する、宣言的な規約管理・フック制御ツール。**

セッション管理、ファイル/コマンド規約、フック制御をYAML設定で宣言的に定義し、Claude Codeのフックイベント（PreToolUse / PostToolUse / Stop 等）経由で自動的に強制できます。

## 主な特徴

- **宣言的YAML設定** - フック動作・規約をコードを書かずにYAMLで定義
- **ファイル規約** - globパターンでファイル操作時に警告/ブロックを自動適用
- **コマンド規約** - Bash実行時に危険なコマンドを検知・制御
- **セッション管理** - SQLiteベースの状態管理でセッション横断の一貫性を確保
- **サブエージェント対応** - Agent Teamsのsubagent別に規約をオーバーライド可能
- **規約提案** - セッション中のフック入力を分析し、新しい規約候補をYAML出力
- **Discord通知** - セッションイベントをDiscordに通知

## Quick Start

### 1. インストール

```bash
pip install claude-nagger
```

### 2. フックのセットアップ

```bash
# .claude/settings.json にフック設定を自動インストール
claude-nagger install-hooks

# dry-runで変更内容を事前確認
claude-nagger install-hooks --dry-run

# 既存設定を上書き
claude-nagger install-hooks --force
```

### 3. 設定ファイルの配置

プロジェクトルートに `.claude-nagger/` ディレクトリを作成し、以下のファイルを配置します。

```
.claude-nagger/
  config.yaml              # メイン設定
  file_conventions.yaml    # ファイル規約
  command_conventions.yaml # コマンド規約
  vault/                   # シークレット管理
    secrets.yaml
```

### 4. 動作確認

```bash
# 環境診断
claude-nagger diagnose

# フック発火テスト
claude-nagger test-hook --tool Write --file "src/main.py"

# パターンマッチングdry-run
claude-nagger match-test --pattern "**/*.py" --file "src/main.py"
```

## CLIコマンド

| コマンド | 説明 |
|---------|------|
| `install-hooks` | フック設定を `.claude/settings.json` にインストール |
| `diagnose` | 環境診断・設定ファイルの検証 |
| `test-hook` | フック発火テスト（`--tool`, `--cmd`, `--file`） |
| `match-test` | パターンマッチングdry-run（`--pattern`, `--file`, `--command`） |
| `suggest-rules` | フック入力JSONから規約候補をYAML出力（`--min-count`, `--top`, `--type`, `--session`） |
| `notify` | Discord通知送信 |

## フック一覧

`claude-nagger hook <name>` で各フックを実行します。Claude Codeの Hooks 設定から自動的に呼び出されます。

| フック名 | イベント | 説明 |
|---------|---------|------|
| `session-startup` | セッション開始 | 規約確認・宣言強制 |
| `implementation-design` | PreToolUse | 実装設計確認 |
| `compact-detected` | PostToolUse | compact検知 |
| `suggest-rules-trigger` | Stop | セッション終了時の規約提案 |
| `subagent-event` | PreToolUse/PostToolUse | サブエージェントStart/Stopイベント管理 |
| `sendmessage-guard` | PreToolUse | SendMessageガード（Redmine基盤通信強制） |
| `leader-constraint` | PreToolUse | leader行動制約（subagent存在時の直接作業ブロック） |
| `task-spawn-guard` | PreToolUse | Task spawnガード |

## 設定ファイル

### config.yaml（メイン設定）

セッション開始メッセージ、各種フック設定、サブエージェント別オーバーライドを定義します。

```yaml
# セッション開始時の規約表示
session_startup:
  enabled: true
  messages:
    first_time:
      title: "プロジェクトセットアップ"
      main_text: |
        以下の規約を確認し遵守を宣言せよ
        [ ] hookブロック後はリトライ
        [ ] 意思決定はチケットに記録する
      severity: "block"

  # subagent別override
  overrides:
    subagent_default:
      messages:
        first_time:
          title: "subagent規約"
          main_text: |
            [ ] 作業完了後に結果を報告すること
    subagent_types:
      coder:
        messages:
          first_time:
            title: "coder規約"
            main_text: |
              [ ] チケット番号をコミットメッセージに含めること

# SendMessageガード
sendmessage_guard:
  enabled: true
  pattern: "issue_\\d+"
  max_content_length: 100

# 規約提案
suggest_rules:
  enabled: true
```

### file_conventions.yaml（ファイル規約）

globパターンでファイル操作に対する規約を定義します。

```yaml
rules:
  - name: "テストファイル編集規約"
    patterns:
      - "**/tests/test_*.py"
    severity: "warn"           # warn: 警告のみ, block: 完全ブロック
    token_threshold: 30000
    message: |
      テスト仕様書を確認してから編集してください

  - name: "フック開発規約"
    patterns:
      - "**/src/domain/hooks/*.py"
    severity: "block"
    token_threshold: 20000
    message: |
      フック開発規約を熟読してから作業してください
```

### command_conventions.yaml（コマンド規約）

Bash実行時のコマンドに対する規約を定義します。

```yaml
rules:
  - name: "pytest実行規約"
    patterns:
      - "pytest*"
      - "python3 -m pytest*"
    severity: "warn"
    token_threshold: 25000
    message: |
      カバレッジ付きで実行してください
```

## アーキテクチャ

```
src/
  application/       # CLI・エントリーポイント
  domain/
    hooks/           # フック実装
    services/        # 規約マッチャー、フック管理
    entities/        # ドメインエンティティ
    models/          # ドメインモデル
  infrastructure/    # DB（SQLite）・外部連携
  shared/            # 共通ユーティリティ
```

## 動作要件

- Python >= 3.10
- Claude Code（Anthropic公式CLI）

### 依存パッケージ

`questionary`, `pytz`, `json5`, `pyyaml`, `typing-extensions`, `rich`, `aiohttp`, `wcmatch`

## 開発

```bash
# テスト実行
python3 -m pytest tests/ -v

# カバレッジ付きテスト
python3 -m pytest --cov=src --cov-report=term-missing

# 開発用依存インストール
pip install -e ".[dev]"
```

## ライセンス

[MIT License](https://opensource.org/licenses/MIT)

## リンク

- [GitHub](https://github.com/HollySizzle/claude-nagger)
- [PyPI](https://pypi.org/project/claude-nagger/)
- [Claude Code Hooks ドキュメント](https://docs.anthropic.com/en/docs/claude-code/hooks)
