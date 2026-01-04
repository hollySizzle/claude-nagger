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
uvx claude-nagger install-hooks

# pip
pip install claude-nagger
claude-nagger install-hooks
```

## セットアップ

```bash
# プロジェクトルートでフックをインストール
claude-nagger install-hooks

# dry-runで確認
claude-nagger install-hooks --dry-run
```

以下の構造が生成されます:

```
your-project/
├── .claude-nagger/
│   ├── config.yaml              # メイン設定
│   ├── file_conventions.yaml    # ファイル別規約
│   ├── command_conventions.yaml # コマンド規約
│   └── hooks/                   # フックスクリプト
└── .claude/
    └── settings.json            # ← claude-naggerが自動設定
```

## 設定例

### .claude-nagger/file_conventions.yaml

```yaml
# ファイルパターン別の規約注入
conventions:
  - pattern: "**/*.css"
    rules: |
      ## CSS規約
      - BEM命名規則を使用
      - !important は禁止
      - ネストは3階層まで

  - pattern: "**/models/**/*.py"
    rules: |
      ## モデル規約
      - フィールド名はsnake_case
      - 必ずdocstringを記載
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
│  │ 1. パターン照合: "**/*.css" ✓       │               │
│  │ 2. 対応する規約を読み込み           │               │
│  │ 3. 規約をコンテキストに注入         │               │
│  └─────────────────────────────────────┘               │
│       ↓                                                 │
│  Claude: 規約を参照しながらCSS編集                      │
└─────────────────────────────────────────────────────────┘
```

## コマンド

```bash
# フックのインストール（.claude/settings.jsonに設定追加）
claude-nagger install-hooks

# dry-run（実際には変更しない）
claude-nagger install-hooks --dry-run

# 強制上書き
claude-nagger install-hooks --force

# バージョン表示
claude-nagger --version
```

## なぜCLAUDE.mdだけでは不十分か

| アプローチ | コンテキスト消費 | 規約遵守率 | 柔軟性 |
|-----------|-----------------|-----------|--------|
| 全規約をCLAUDE.mdに記載 | 高 (常時) | 低 (忘却) | 低 |
| claude-nagger | 低 (必要時のみ) | 高 | 高 |

## 要件

- Python 3.10以上
- Claude Code CLI

## ライセンス

MIT License - 詳細は [LICENSE](LICENSE) を参照
