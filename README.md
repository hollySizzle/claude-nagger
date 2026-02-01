# claude-nagger

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![PyPI](https://img.shields.io/pypi/v/claude-nagger.svg)](https://pypi.org/project/claude-nagger/)

**Conditional convention injection + automatic re-injection after context compacting** for Claude Code.

Feeds project conventions to Claude Code **only when relevant files are touched** — and re-injects them when the context window compacts.

> **Japanese version is available below.** See [日本語版](#日本語版)

## The Problem

| Problem | Description |
|---------|-------------|
| **Context bloat** | Writing all conventions in CLAUDE.md consumes massive tokens |
| **Convention amnesia** | Context compacting causes conventions to be "forgotten" |
| **Irrelevant information** | CSS conventions are unnecessary when editing models, and vice versa |

## How It Works

```
User: "Fix this CSS"
  → Claude calls Edit tool (*.css)
    → PreToolUse Hook (claude-nagger)
      1. Pattern match: "**/*.css" ✓
      2. Load & inject matching conventions
  → Claude edits CSS while referencing conventions
```

CLAUDE.md alone cannot achieve **conditional injection via PreToolUse hooks** — claude-nagger can.

## Key Features

### 1. File-pattern conditional injection

Conventions fire **only when matching files are edited**:

```yaml
rules:
  - name: "CSS conventions"
    patterns: ["**/*.css", "**/*.scss"]
    severity: "warn"
    message: |
      - Use BEM naming convention
      - !important is prohibited
```

CSS rules fire only for CSS files. Model rules fire only for model files. No wasted tokens.

### 2. Compact detection & auto re-injection

When Claude Code compacts its context, conventions are silently dropped. claude-nagger detects compacting via `SessionStart[compact]` hook and resets marker files — conventions re-inject on the next tool call. **No configuration required.**

### 3. Token-threshold re-injection

Each rule can define a `token_threshold`. When token count since last injection exceeds the threshold, the convention re-injects — even without compacting:

```yaml
rules:
  - name: "Model conventions"
    patterns: ["**/models/**/*.py"]
    severity: "block"
    token_threshold: 35000
    message: |
      - Field names in snake_case
      - Docstrings required
```

### 4. Automatic rule suggestion (suggest-rules)

Starting with an empty convention file? claude-nagger analyzes your actual tool usage and **automatically suggests rules**:

```
Session ends (Stop hook)
  → Analyze hook_input_*.json (file paths, commands)
    → Pattern aggregation + Claude LLM analysis
      → .claude-nagger/suggested_rules.yaml generated
        → Next session: notification with proposals
```

Run manually anytime:

```bash
claude-nagger suggest-rules                        # Analyze & output suggestions
claude-nagger suggest-rules --min-count 5 --top 5  # Filter by frequency
```

### 5. Subagent-aware convention enforcement

When Claude Code spawns subagents (via the Task tool), conventions are enforced there too — with **per-type override** support:

```yaml
# config.yaml
session_startup:
  overrides:
    subagent_default:          # Applied to ALL subagents
      messages:
        first_time:
          title: "Subagent rules"
          main_text: "No out-of-scope edits"

    subagent_types:            # Per-type overrides (highest priority)
      ticket-manager:
        messages:
          first_time:
            title: "Ticket agent rules"
            main_text: "Redmine operations only"
      Explore:
        enabled: false         # Skip for Explore subagents
```

claude-nagger tracks subagent lifecycle via `SubagentStart`/`SubagentStop` hooks, resolves the appropriate config override (`base → subagent_default → subagent_types.{type}`), and injects the right conventions — once per subagent, non-blocking after first display.

### Comparison with similar tools

| Feature | claude-nagger | bmad-context-injection | meridian |
|---------|:---:|:---:|:---:|
| **File-pattern conditional injection** | Yes | Yes | No (session-level) |
| **Command-pattern conditional injection** | Yes | No | No |
| **Compact detection + re-injection** | Yes | No | Yes |
| **Per-rule token-threshold re-injection** | Yes | No | Session-level |
| **Automatic rule suggestion** | Yes | No | No |
| **Subagent-aware enforcement** | Yes | No | No |
| **Distribution** | `pip install` (PyPI) | Copy to project | curl installer |
| **License** | MIT | MIT (unconfirmed) | Not specified |

## Quick Start

```bash
# Install (uv tool recommended)
uv tool install claude-nagger && claude-nagger install-hooks

# or pip
pip install claude-nagger && claude-nagger install-hooks

# Update
uv tool upgrade claude-nagger   # or: pip install --upgrade claude-nagger

# Verify
claude-nagger install-hooks --dry-run
```

> **Note**: `uvx claude-nagger install-hooks` is not recommended — uvx runs in a temporary environment and hooks will not work.

<details>
<summary><b>Command not found? (PATH)</b></summary>

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```
</details>

Then edit `.claude-nagger/*.yaml` to set project-specific conventions:

```
.claude-nagger/
├── config.yaml              # Session management & context thresholds
├── file_conventions.yaml    # Conventions for file editing
├── command_conventions.yaml # Conventions for command execution
└── suggested_rules.yaml     # Auto-generated rule suggestions (by suggest-rules)
```

## Configuration

### file_conventions.yaml

```yaml
rules:
  - name: "CSS conventions"
    patterns: ["**/*.css", "**/*.scss"]
    severity: "warn"           # warn | block
    token_threshold: 30000     # Optional: re-inject threshold
    message: |
      - Use BEM naming convention
      - !important is prohibited
```

<details>
<summary><b>config.yaml</b></summary>

```yaml
session_startup:
  enabled: true
  messages:
    first_time:
      title: "Project Setup"
      main_text: "Please review the project conventions"
      severity: "block"

  # Subagent overrides (base → subagent_default → subagent_types.{type})
  overrides:
    subagent_default:
      messages:
        first_time:
          title: "Subagent rules"
          main_text: "No out-of-scope file edits"
    subagent_types:
      Explore:
        enabled: false

context_management:
  reminder_thresholds:
    light_warning: 30000
    medium_warning: 60000
    critical_warning: 100000
```
</details>

<details>
<summary><b>command_conventions.yaml</b></summary>

```yaml
rules:
  - name: "Git conventions"
    patterns: ["git push*", "git commit*"]
    severity: "warn"
    token_threshold: 25000
    message: |
      - Write commit messages in the project language
      - Run tests before pushing
```
</details>

## Commands

```bash
claude-nagger install-hooks              # Install hooks
claude-nagger install-hooks --dry-run    # Preview (no changes)
claude-nagger install-hooks --force      # Force overwrite
claude-nagger --version                  # Version
claude-nagger diagnose                   # Environment diagnostics
claude-nagger suggest-rules              # Suggest rules from usage history
claude-nagger hook <name>               # Direct hook execution
claude-nagger match-test --file "path" --pattern "glob"   # Test pattern matching
```

## Requirements / Links / License

- **Requires**: Python 3.10+, Claude Code CLI
- [Bug reports](https://github.com/HollySizzle/claude-nagger/issues/new?template=bug_report.yml) (attach `claude-nagger diagnose` output) | [Feature requests](https://github.com/HollySizzle/claude-nagger/issues/new?template=feature_request.yml) | [Discussions](https://github.com/HollySizzle/claude-nagger/discussions)
- [Developer setup](https://github.com/HollySizzle/claude-nagger): `git clone` & `./scripts/install-dev.sh`
- **License**: MIT — See [LICENSE](LICENSE)

---
---

# 日本語版

Claude Codeに**条件付き規約注入 + コンテキスト圧縮後の自動再注入**を提供するフックツール。

関連ファイルが編集された時**だけ**プロジェクト規約をClaude Codeに注入し、コンテキスト圧縮時に自動で再注入します。

## 解決する問題

| 問題 | 説明 |
|------|------|
| **コンテキスト肥大化** | 全規約をCLAUDE.mdに書くとトークン消費が膨大 |
| **規約の忘却** | コンテキスト圧縮(compacting)により規約が「忘れられる」 |
| **無関係な情報** | モデル編集時にCSS規約は不要、逆も然り |

## 動作原理

```
ユーザー: "このCSSを修正して"
  → Claude: Editツール呼び出し (*.css)
    → PreToolUse Hook (claude-nagger)
      1. パターン照合: "**/*.css" ✓
      2. 対応する規約を読み込み・注入
  → Claude: 規約を参照しながらCSS編集
```

CLAUDE.md単体では実現できない**PreToolUseフックによる条件付き注入**を提供します。

## 主な機能

### 1. ファイルパターン条件付き注入

対象ファイルが編集された時**だけ**規約を注入：

```yaml
rules:
  - name: "CSS編集規約"
    patterns: ["**/*.css", "**/*.scss"]
    severity: "warn"
    message: |
      - BEM命名規則を使用
      - !important は禁止
```

CSS規約はCSS編集時のみ発火。モデル規約はモデル編集時のみ。トークンの無駄がありません。

### 2. compact検知・自動再注入

Claude Codeがコンテキストを圧縮すると規約は暗黙的に失われます。claude-naggerは`SessionStart[compact]`フックで圧縮を検知しマーカーファイルをリセット — 次のツール呼び出しで規約が自動再注入されます。**設定不要。**

### 3. トークン閾値再注入

ルールごとに`token_threshold`を設定可能。前回注入時からのトークン増加量が閾値を超えると、compactなしでも再注入：

```yaml
rules:
  - name: "モデル編集規約"
    patterns: ["**/models/**/*.py"]
    severity: "block"
    token_threshold: 35000
    message: |
      - フィールド名はsnake_case
      - 必ずdocstringを記載
```

### 4. 自動規約提案（suggest-rules）

規約ファイルが空の状態からでも、実際のツール使用履歴を分析して**規約候補を自動提案**：

```
セッション終了（Stop hook）
  → hook_input_*.json分析（ファイルパス・コマンド集約）
    → Python統計前処理 + Claude LLM分析
      → .claude-nagger/suggested_rules.yaml 生成
        → 次回セッション開始時に提案内容を通知
```

手動実行も可能：

```bash
claude-nagger suggest-rules                        # 使用履歴から規約候補を出力
claude-nagger suggest-rules --min-count 5 --top 5  # 出現頻度でフィルタ
```

### 5. subagent対応の規約適用

Claude Codeがsubagent（Taskツール）を起動した場合も、**タイプ別オーバーライド**で規約を自動適用：

```yaml
# config.yaml
session_startup:
  overrides:
    subagent_default:          # 全subagent共通
      messages:
        first_time:
          title: "subagent規約"
          main_text: "スコープ外の編集禁止"

    subagent_types:            # タイプ別オーバーライド（最優先）
      ticket-manager:
        messages:
          first_time:
            title: "チケット管理agent規約"
            main_text: "Redmine操作のみ"
      Explore:
        enabled: false         # Exploreでは規約表示をスキップ
```

`SubagentStart`/`SubagentStop`フックでsubagentのライフサイクルを追跡し、設定を解決（`base → subagent_default → subagent_types.{type}`）して適切な規約を注入します。初回表示後はノンブロッキング。

### 類似ツールとの比較

| 機能 | claude-nagger | bmad-context-injection | meridian |
|------|:---:|:---:|:---:|
| **ファイルパターン条件付き注入** | Yes | Yes | No（セッション単位） |
| **コマンドパターン条件付き注入** | Yes | No | No |
| **compact検知＋再注入** | Yes | No | Yes |
| **ルール単位トークン閾値再注入** | Yes | No | セッション単位 |
| **自動規約提案** | Yes | No | No |
| **subagent対応規約適用** | Yes | No | No |
| **配布方式** | `pip install`（PyPI） | プロジェクトにコピー | curlインストーラ |
| **ライセンス** | MIT | MIT（未確認） | 未指定 |

## クイックスタート

```bash
# インストール（uv tool推奨）
uv tool install claude-nagger && claude-nagger install-hooks

# または pip
pip install claude-nagger && claude-nagger install-hooks

# アップデート
uv tool upgrade claude-nagger   # or: pip install --upgrade claude-nagger

# 動作確認
claude-nagger install-hooks --dry-run
```

> **注意**: `uvx claude-nagger install-hooks`は非推奨 — uvxは一時実行のためフックが動作しません。

<details>
<summary><b>コマンドが見つからない場合（PATH設定）</b></summary>

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc
```
</details>

`.claude-nagger/*.yaml` を編集してプロジェクト固有の規約を設定：

```
.claude-nagger/
├── config.yaml              # セッション管理・コンテキスト閾値
├── file_conventions.yaml    # ファイル編集時の規約
├── command_conventions.yaml # コマンド実行時の規約
└── suggested_rules.yaml     # 自動生成された規約候補（suggest-rules）
```

## 設定

### file_conventions.yaml

```yaml
rules:
  - name: "CSS編集規約"
    patterns: ["**/*.css", "**/*.scss"]
    severity: "warn"           # warn | block
    token_threshold: 30000     # 任意: 再注入閾値
    message: |
      - BEM命名規則を使用
      - !important は禁止
```

<details>
<summary><b>config.yaml</b></summary>

```yaml
session_startup:
  enabled: true
  messages:
    first_time:
      title: "プロジェクトセットアップ"
      main_text: "プロジェクトの規約を確認してください"
      severity: "block"

  # subagentオーバーライド（base → subagent_default → subagent_types.{type}）
  overrides:
    subagent_default:
      messages:
        first_time:
          title: "subagent規約"
          main_text: "スコープ外の編集禁止"
    subagent_types:
      Explore:
        enabled: false

context_management:
  reminder_thresholds:
    light_warning: 30000
    medium_warning: 60000
    critical_warning: 100000
```
</details>

<details>
<summary><b>command_conventions.yaml</b></summary>

```yaml
rules:
  - name: "Git操作規約"
    patterns: ["git push*", "git commit*"]
    severity: "warn"
    token_threshold: 25000
    message: |
      - コミットメッセージは日本語で記載
      - プッシュ前にテストを実行
```
</details>

## コマンド一覧

```bash
claude-nagger install-hooks              # フックインストール
claude-nagger install-hooks --dry-run    # プレビュー（変更なし）
claude-nagger install-hooks --force      # 強制上書き
claude-nagger --version                  # バージョン表示
claude-nagger diagnose                   # 環境診断
claude-nagger suggest-rules              # 使用履歴から規約候補を提案
claude-nagger hook <name>               # フック直接実行
claude-nagger match-test --file "path" --pattern "glob"   # パターンテスト
```

## 要件 / リンク / ライセンス

- **要件**: Python 3.10以上、Claude Code CLI
- [バグ報告](https://github.com/HollySizzle/claude-nagger/issues/new?template=bug_report.yml)（`claude-nagger diagnose` 出力を添付）| [機能リクエスト](https://github.com/HollySizzle/claude-nagger/issues/new?template=feature_request.yml) | [ディスカッション](https://github.com/HollySizzle/claude-nagger/discussions)
- [開発者向け](https://github.com/HollySizzle/claude-nagger): `git clone` & `./scripts/install-dev.sh`
- **ライセンス**: MIT — [LICENSE](LICENSE)
