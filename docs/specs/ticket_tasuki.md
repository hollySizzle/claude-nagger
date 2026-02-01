# ticket-tasuki 要件定義

## 概要
**名称**: ticket-tasuki（TiDD基盤のエージェント間コンテキストリレー機構）
**目的**: 1セッション内でleader（意思決定）とcoder（実装）を分離し、コンテキスト保護・バイアス排除・レビュー品質向上を実現
**範囲**: claude-nagger設定、CLAUDE.md、redmine_driven_dev.yaml
**依存**: claude-nagger（hooks/subagent管理）、redmine-epic-grid MCP、Claude Code Task tool

## 背景・意図

### 解決する課題
- マルチセッション手動切替のコスト
- 実装詳細によるメインエージェントのコンテキスト圧迫
- 実装者が自身のコードをレビューする際のバイアス

### 設計判断の経緯
- tmux連携（multi-agent-shogun方式）: 通信が脆弱、直列ワークフローに並列化は不適合 → 却下
- 判断者が実装兼務: コンテキスト圧迫・レビューバイアス → 却下
- **leader/coder分離 + TiDDによるコンテキスト共有**: 採択
- 詳細: @docs/temps/subagent_workflow_discussion.md

## アーキテクチャ

```
leader（メインエージェント）
  やること: 読む・判断する・指示する・レビューする
  やらないこと: コード編集
  │
  ├── coder subagent（general-purpose）→ コード実装
  ├── ticket-manager subagent → チケット操作
  ├── Explore subagent → コード調査
  ├── Bash subagent → テスト実行
  ├── general-purpose subagent → Web調査
  └── （将来）tester subagent → テスト設計・実行
```

**コンテキスト共有**: チケットコメント + コミットID（issue_{id}紐付け）
**コンテキスト復元**: チケット読込 + git log + 親チケット + 規約

## 要件

### REQ-1: leaderの役割定義
**対象**: CLAUDE.md または session_startup メッセージ
**内容**:
- leaderはコードを直接編集しない（must_not）
- USをTask粒度に分解してからsubagentに渡す（must）
- subagent成果物を必ずレビューする（must）
- 判断が必要な場面ではオーナーに確認する（must）

### REQ-2: codersubagentプロンプトテンプレート
**対象**: CLAUDE.md または専用テンプレートファイル
**内容**:
- Task tool起動時のpromptに含める定型情報:
  - チケット番号（issue_{id}）
  - 実装意図（leaderが記載）
  - 対象ファイル（leaderが指定）
  - 実装指示（leaderが記載）
  - 制約: 判断が必要な場合は実装せず報告すること
- コミットメッセージにissue_{id}を含める指示

### REQ-3: claude-nagger subagent_types更新
**対象**: `.claude-nagger/config.yaml`
**内容**:
- coder役（general-purpose）のオーバーライド追加
  - 規約: スコープ外編集禁止、判断せず報告、コミット規約遵守
- 既存subagent_typesの整理（Explore無効化の維持等）

### REQ-4: 却下案テンプレート追加
**対象**: `docs/rules/redmine_driven_dev.yaml`
**内容**:
- comment_templateに「却下案」欄追加
  - 試して不採用にしたアプローチと理由を記録
  - コンテキスト喪失の最大残存リスクへの対策

## 制約・前提

### 新規ツール開発なし
全てclaude-nagger設定・CLAUDE.md・規約YAMLの変更で完結する。
新規MCP/CLIの開発は行わない。

### subagentの既知制約（Claude Code本体）
- Context low時の自動compact不可 → 1Task=1subagent起動で緩和
- 親エージェントの出力美化 → leaderがレビュー担当で構造的回避
- ネスト不可（subagent→subagent） → leaderが全subagentを直接起動
- ~20kトークン/subagentのオーバーヘッド → 小タスクの過剰委譲を避ける

### 1US = 1セッション
- USの完了とセッションの完了が一致
- 次のUS開始時はチケットからコンテキスト復元

## 関連文書
- @docs/temps/subagent_workflow_discussion.md（検討経緯）
- @docs/rules/redmine_driven_dev.yaml（TiDD規約）
- @docs/specs/architecture.md
- packages/claude-nagger/.claude-nagger/config.yaml
