# claude-nagger

Claude Codeに「必要な時だけ」規約を読ませるフックツール

## 解決する問題

Claude Codeで中〜大規模プロジェクトを扱う際、以下の問題が発生します:

| 問題 | 説明 |
|------|------|
| **コンテキスト肥大化** | 全規約をCLAUDE.mdに書くとトークン消費が膨大 |
| **規約の忘却** | コンテキスト圧縮(compacting)により規約が「忘れられる」 |
| **無関係な情報** | モデル編集時にCSS規約は不要、逆も然り |

## 解決策: 操作に応じた規約の動的注入

```
EditツールでCSS編集 → CSS規約のみ注入
Editツールでモデル編集 → モデル規約のみ注入
```

CLAUDE.mdでは実現できない「PreToolUseフックによる条件付き規約注入」を提供します。

## インストール

```bash
# uvx (推奨)
uvx claude-nagger

# pip
pip install claude-nagger
```

## セットアップ

```bash
# プロジェクトルートで初期化
claude-nagger init
```

以下の構造が生成されます:

```
your-project/
├── .claude-nagger/
│   ├── config.yaml          # メイン設定
│   ├── rules/               # 規約ファイル
│   │   ├── css.md
│   │   ├── models.md
│   │   └── api.md
│   └── messages/            # セッションメッセージ
│       ├── first_session.md
│       └── continue_session.md
└── .claude/
    └── settings.json        # ← claude-naggerが自動設定
```

## 設定例

### .claude-nagger/config.yaml

```yaml
# 操作別規約マッピング
rules:
  # CSSファイル編集時
  - matcher: "Edit:**/*.css"
    inject: "rules/css.md"

  # モデルファイル編集時
  - matcher: "Edit:**/models/**/*.py"
    inject: "rules/models.md"

  # API関連ファイル編集時
  - matcher: "Edit:**/api/**"
    inject: "rules/api.md"

# セッション開始メッセージ
session:
  first_time: "messages/first_session.md"
  continued: "messages/continue_session.md"

# 通知設定 (オプション)
notifications:
  discord:
    enabled: true
    webhook_url: "${DISCORD_WEBHOOK_URL}"  # 環境変数参照
```

### 規約ファイル例: .claude-nagger/rules/css.md

```markdown
## CSS規約

- BEM命名規則を使用すること
- !important は禁止
- ネストは3階層まで
```

## 動作原理

```
┌─────────────────────────────────────────────────────────┐
│ Claude Code                                             │
│                                                         │
│  ユーザー: "このCSSを修正して"                          │
│       ↓                                                 │
│  Claude: Edit ツール呼び出し (*.css)                    │
│       ↓                                                 │
│  ┌─────────────────────────────────────┐               │
│  │ PreToolUse Hook (claude-nagger)     │               │
│  │                                     │               │
│  │ 1. matcher照合: "Edit:**/*.css" ✓   │               │
│  │ 2. rules/css.md を読み込み          │               │
│  │ 3. 規約をコンテキストに注入         │               │
│  └─────────────────────────────────────┘               │
│       ↓                                                 │
│  Claude: 規約を参照しながらCSS編集                      │
└─────────────────────────────────────────────────────────┘
```

## コマンド

```bash
# 初期化
claude-nagger init

# 設定の検証
claude-nagger validate

# フックのインストール（.claude/settings.jsonに追記）
claude-nagger install-hooks

# 規約ファイルのテンプレート生成
claude-nagger add-rule <name>
```

## Discord通知 (オプション)

セッション停止時などにDiscord通知を送信できます。

```yaml
# .claude-nagger/config.yaml
notifications:
  discord:
    enabled: true
    webhook_url: "${DISCORD_WEBHOOK_URL}"
    events:
      - stop      # セッション停止時
      - error     # エラー発生時
```

## なぜCLAUDE.mdだけでは不十分か

| アプローチ | コンテキスト消費 | 規約遵守率 | 柔軟性 |
|-----------|-----------------|-----------|--------|
| 全規約をCLAUDE.mdに記載 | 高 (常時) | 低 (忘却) | 低 |
| claude-nagger | 低 (必要時のみ) | 高 | 高 |

## ライセンス

MIT
