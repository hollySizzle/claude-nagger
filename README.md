# claude-nagger

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/claude-nagger.svg)](https://pypi.org/project/claude-nagger/)

Claude Codeに「必要な時だけ」規約を読ませるフックツール

## 解決する問題

Claude Codeで中〜大規模プロジェクトを扱う際、以下の問題が発生します:

| 問題 | 説明 |
|------|------|
| **コンテキスト肥大化** | 全規約をCLAUDE.mdに書くとトークン消費が膨大 |
| **規約の忘却** | コンテキスト圧縮(compacting)により規約が「忘れられる」 |
| **無関係な情報** | モデル編集時にCSS規約は不要、逆も然り |

## 解決策

```
EditツールでCSS編集 → CSS規約のみ注入
Editツールでモデル編集 → モデル規約のみ注入
```

CLAUDE.mdでは実現できない「PreToolUseフックによる条件付き規約注入」を提供します。

---

## クイックスタート

### 1. インストール

```bash
# uv tool（推奨）
uv tool install claude-nagger
claude-nagger install-hooks

# または pip
pip install claude-nagger
claude-nagger install-hooks

# dockerfileなどコンテナ向け
RUN pip install claude-nagger --break-system-packages 
```

> **注意**: `uvx claude-nagger install-hooks`は非推奨。uvxは一時実行のためフックが動作しません。

<details>
<summary><b>コマンドが見つからない場合（PATH設定）</b></summary>

`uv tool install` 後に `command not found` が出る場合、PATHを設定してください：

```bash
# PATHを通す（bash/zsh共通）
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# zshの場合は ~/.zshrc に追加
```

</details>

### アップデート

```bash
# uv tool
uv tool upgrade claude-nagger

# pip
pip install --upgrade claude-nagger
```

### 2. 動作確認

```bash
# dry-runで生成内容を確認
claude-nagger install-hooks --dry-run
```

### 3. 設定カスタマイズ

生成された `.claude-nagger/` 内のYAMLファイルを編集して、プロジェクト固有の規約を設定します。

---

## 生成されるファイル構造

```
your-project/
├── .claude-nagger/
│   ├── config.yaml              # メイン設定（セッション管理等）
│   ├── file_conventions.yaml    # ファイル編集時の規約
│   └── command_conventions.yaml # コマンド実行時の規約
└── .claude/
    └── settings.json            # ← claude-naggerが自動設定
```

---

## 設定ファイル詳細

### config.yaml（メイン設定）

セッション開始時のメッセージやコンテキスト管理を設定します。

```yaml
# セッション開始時設定
session_startup:
  enabled: true
  messages:
    first_time:
      title: "プロジェクトセットアップ"
      main_text: |
        プロジェクトの規約を確認してください
      severity: "block"  # block: 確認必須, warn: 警告のみ

# コンテキスト管理設定（トークン数に応じたリマインダー）
context_management:
  reminder_thresholds:
    light_warning: 30000     # 軽い警告
    medium_warning: 60000    # 中程度の警告
    critical_warning: 100000 # 重要な警告

# デバッグ設定
debug:
  enable_logging: false
```

### file_conventions.yaml（ファイル編集規約）

特定のファイルパターンに対して適用される規約を定義します。

```yaml
rules:
  # CSS編集時の規約
  - name: "CSS編集規約"
    patterns:
      - "**/*.css"
      - "**/*.scss"
    severity: "warn"
    token_threshold: 30000
    message: |
      ## CSS規約
      - BEM命名規則を使用
      - !important は禁止
      - ネストは3階層まで

  # モデル編集時の規約
  - name: "モデル編集規約"
    patterns:
      - "**/models/**/*.py"
      - "**/entities/**/*.py"
    severity: "block"
    token_threshold: 35000
    message: |
      ## モデル規約
      - フィールド名はsnake_case
      - 必ずdocstringを記載
      - バリデーションを実装

  # View層編集時の規約
  - name: "View層編集規約"
    patterns:
      - "**/views/**/*.erb"
      - "**/templates/**/*.html"
    severity: "warn"
    message: |
      ## View規約
      - XSS対策を徹底
      - ロジックはヘルパーに委譲
```

### command_conventions.yaml（コマンド実行規約）

危険なコマンドや確認が必要なコマンドに対して適用される規約を定義します。

```yaml
rules:
  # Git操作規約
  - name: "Git操作規約"
    patterns:
      - "git push*"
      - "git commit*"
    severity: "warn"
    token_threshold: 25000
    message: |
      ## Git規約
      - コミットメッセージは日本語で記載
      - プッシュ前にテストを実行

  # 本番環境操作規約
  - name: "本番環境操作規約"
    patterns:
      - "*production*"
      - "*deploy*"
    severity: "block"
    message: |
      ## 本番環境操作
      - 必ず承認を得てから実行
      - バックアップを確認
```

---

## ユースケース例

### Rails プロジェクト

```yaml
# file_conventions.yaml
rules:
  - name: "コントローラ規約"
    patterns: ["**/controllers/**/*.rb"]
    message: |
      - before_actionでの認証確認
      - Strong Parametersの使用必須

  - name: "マイグレーション規約"
    patterns: ["**/migrate/*.rb"]
    severity: "block"
    message: |
      - 必ずロールバック可能にする
      - 大量データ更新時はバッチ処理
```

### React プロジェクト

```yaml
# file_conventions.yaml
rules:
  - name: "コンポーネント規約"
    patterns: ["**/components/**/*.tsx"]
    message: |
      - Propsの型定義必須
      - useCallbackでメモ化検討

  - name: "フック規約"
    patterns: ["**/hooks/**/*.ts"]
    message: |
      - カスタムフックは use* で命名
      - 依存配列を正確に記述
```

### Python プロジェクト

```yaml
# file_conventions.yaml
rules:
  - name: "API規約"
    patterns: ["**/api/**/*.py", "**/routes/**/*.py"]
    message: |
      - 入力バリデーション必須
      - エラーハンドリングを実装

  - name: "テスト規約"
    patterns: ["**/tests/**/*.py"]
    message: |
      - Arrange-Act-Assertパターン
      - モックは最小限に
```

---

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

---

## compact検知機能 (v1.4.0)

Claude Codeのコンテキスト圧縮(compacting)後、自動的に規約リマインダーを再表示します。

```
compact発生
    ↓
SessionStart[compact] フック発火
    ↓
claude-nagger: マーカーファイルをリセット
    ↓
次のツール呼び出しで規約が再注入される
```

これにより「規約の忘却」問題を解決します。設定不要で自動的に動作します。

---

## コマンド一覧

```bash
# フックのインストール（.claude/settings.jsonに設定追加）
claude-nagger install-hooks

# dry-run（実際には変更しない）
claude-nagger install-hooks --dry-run

# 強制上書き（既存ファイルも再生成）
claude-nagger install-hooks --force

# バージョン表示
claude-nagger --version

# 環境診断（トラブルシュート用）
claude-nagger diagnose

# フック直接実行（内部用・トラブルシュート用）
claude-nagger hook session-startup
claude-nagger hook implementation-design
claude-nagger hook compact-detected

# パターンマッチングのテスト（設定確認用）
claude-nagger match-test --file "app/views/test.erb" --pattern "app/views/**/*.erb"
claude-nagger match-test --command "git push" --pattern "git push*"
```

---

## なぜCLAUDE.mdだけでは不十分か

| アプローチ | コンテキスト消費 | 規約遵守率 | 柔軟性 |
|-----------|-----------------|-----------|--------|
| 全規約をCLAUDE.mdに記載 | 高 (常時) | 低 (忘却) | 低 |
| claude-nagger | 低 (必要時のみ) | 高 | 高 |

---

## 開発者向け

```bash
git clone https://github.com/HollySizzle/claude-nagger.git
cd claude-nagger
./scripts/install-dev.sh  # インストール＆フック設定
```

---

## 要件

- Python 3.10以上
- Claude Code CLI

---

## 問題報告・機能リクエスト

- **バグ報告**: [GitHub Issues](https://github.com/HollySizzle/claude-nagger/issues/new?template=bug_report.yml)
- **機能リクエスト**: [GitHub Issues](https://github.com/HollySizzle/claude-nagger/issues/new?template=feature_request.yml)
- **質問・議論**: [GitHub Discussions](https://github.com/HollySizzle/claude-nagger/discussions)

バグ報告時は `claude-nagger diagnose` の出力を添付してください。

---

## ライセンス

MIT License - 詳細は [LICENSE](LICENSE) を参照
