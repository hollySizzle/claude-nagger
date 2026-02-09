# ticket-tasuki 要件定義

## 概要
**名称**: ticket-tasuki（TiDD基盤のエージェント間コンテキストリレー機構）
**目的**: 1セッション内でleader（意思決定）とcoder（実装）を分離し、コンテキスト保護・バイアス排除・レビュー品質向上を実現
**配布形態**: Claude Codeプラグイン（`.claude-plugin/plugin.json`）
**依存**: claude-nagger（推奨）、redmine-epic-grid MCP（必須）、Claude Code（必須）

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
  ├── coder subagent → コード実装・単体テスト
  ├── tester subagent → 受入テスト・E2Eテスト
  ├── scribe subagent → Redmineチケット管理（CRUD・階層管理・バージョン管理）
  ├── Explore subagent → コード調査
  ├── Bash subagent → コマンド実行
  └── general-purpose subagent → Web調査
```

**コンテキスト共有**: チケットコメント + コミットID（issue_{id}紐付け）
**コンテキスト復元**: チケット読込 + git log + 親チケット + 規約

## 配布設計

### プラグイン構成
```
packages/ticket-tasuki/
  .claude-plugin/
    plugin.json                ← マニフェスト
  agents/
    coder.md                   ← coder subagent定義（REQ-2、tools:制限あり）
    tester.md                  ← tester subagent定義（REQ-5、受入・E2Eテスト）
    scribe.md                  ← scribe subagent定義（チケット読み取り専門）
  skills/
    tasuki-setup/
      SKILL.md                 ← /tasuki-setup セットアップ用skill
    tasuki-delegate/
      SKILL.md                 ← /tasuki-delegate coder委譲用skill
  hooks/
    hooks.json                 ← SubagentStart/Stop等
  CLAUDE.md                    ← leader規約定義（REQ-1、ソフト制約）
  README.md
```
**注**: leader規約はCLAUDE.mdに記載（メインエージェントはsubagent定義の対象外のため）

### 配布方法
- GitHubリポジトリとして公開
- `/plugin install` で導入可能
- マーケットプレイス登録（marketplace.json）

### 開発方針
- 独立リポジトリ: `hollySizzle/ticket-tasuki`（GitHub）
- ワークスペース内配置: `/workspace/packages/ticket-tasuki/`（親リポの`.gitignore`で除外）
- claude-naggarとは同ワークスペースで並行開発だが、git管理は独立

## エージェント制御方式

### 制御の二層構造
leaderはメインエージェント自身であり、subagent定義の`tools:`制限は適用不可。
coderはsubagentであり、`tools:`制限でClaude Code本体が物理的に強制可能。

| 対象 | 制御手段 | 強制力 |
|------|---------|--------|
| leader | CLAUDE.md指示 + claude-nagger session_startup通知 | ソフト制約（LLM遵守に依存） |
| coder | `agents/coder.md`の`tools:`フィールド | 物理的制限（Claude Code本体が強制） |
| coder | claude-nagger `subagent_types.coder` override | 通知レベルのガードレール |
| tester | `agents/tester.md`の`tools:`フィールド | 物理的制限（Read/Bash/Glob/Grep） |
| scribe | `agents/scribe.md`の`tools:`フィールド | 物理的制限（Redmine MCPのみ） |

**段階的強化**: ソフト制約で不十分な場合、`ImplementationDesignHook`にSubagentMarkerManager参照を追加し、メインエージェントのWrite/Editを物理ブロック可能（現時点では未実装・必要性未確定）。

### 既存基盤の確認状況（2026-02-01時点）
- `SessionStartupHook`: subagent種別ごとのoverride解決済み（`_resolve_subagent_config`実装済み）
- `SubagentMarkerManager`: subagentライフサイクル追跡済み（create/delete/get_active）
- `ImplementationDesignHook`: SubagentMarkerManager**未参照**（メイン/subagent区別なし）
- `file_conventions.yaml`: ルール空（`[]`）。配管済み・バルブ未開放
- `scribe.md`（旧ticket-manager.md）: `tools:`制限の実績あり（Redmine MCPのみ許可→ファイル操作不可）

## 要件

### REQ-1: leader規約定義
**対象**: CLAUDE.md / プラグインの規約ファイル（メインエージェント向け）
**注意**: leaderはsubagentではないため`agents/leader.md`のtools制限は使えない
**内容**:
- leaderはコードを直接編集しない（must_not、ソフト制約）
- USをTask粒度に分解してからsubagentに渡す（must）
- subagent成果物を必ずレビューする（must）
- 判断が必要な場面ではオーナーに確認する（must）

### REQ-2: coder subagent定義
**対象**: `agents/coder.md`
**内容**:
- `tools:`でEdit/Write/Bash/Read等に制限（物理的強制）
- チケット番号（issue_{id}）を受け取る
- 実装意図・対象ファイル・実装指示に従う
- 判断が必要な場合は実装せず報告する（must）
- コミットメッセージにissue_{id}を含める（must）
- スコープ外のファイルを編集しない（must_not）

### REQ-3: claude-nagger連携
**対象**: `.claude-nagger/config.yaml`
**内容**:
- `subagent_types.coder` overrideを追加（規約通知）
- leader向け: session_startup messagesに「コード編集禁止・coder委譲」を明記
- 既存subagent_typesとの整合性確認

### REQ-5: tester subagent定義
**対象**: `agents/tester.md`
**内容**:
- `tools:`でRead/Bash/Glob/Grepに制限（コード読み取り+テスト実行のみ、編集不可）
- 受入テスト・E2Eテストの設計と実行が責務
- 単体テストはcoderの責務（実装と密結合のため）
- テスト結果・失敗箇所・再現手順を報告する（must）
- coderの実装バイアスを排除するため、実装詳細ではなく仕様・要件からテストを設計する

### REQ-6: scribe subagent定義（旧ticket-manager）
**対象**: `agents/scribe.md`
**内容**:
- ticket-managerからリネーム（leader/coder/scribeの命名一貫性）
- `tools:`でRedmine MCPツールのみに制限（コード関連操作は一切不可）
- Redmineチケット管理（CRUD・階層管理・バージョン管理）が主責務
- leaderのコンテキスト削減にも寄与（チケット操作の委譲先）

### REQ-4: 却下案テンプレート追加
**対象**: `docs/rules/redmine_driven_dev.yaml`
**内容**:
- comment_templateに「却下案」欄追加
  - 試して不採用にしたアプローチと理由を記録
  - コンテキスト喪失の最大残存リスクへの対策

## 制約・前提

### subagentの既知制約（Claude Code本体）
- Context low時の自動compact不可 → 1Task=1subagent起動で緩和
- 親エージェントの出力美化 → leaderがレビュー担当で構造的回避
- ネスト不可（subagent→subagent） → leaderが全subagentを直接起動
- ~20kトークン/subagentのオーバーヘッド → 小タスクの過剰委譲を避ける

### leader制御の制約
- メインエージェントはsubagent定義の`tools:`制限対象外
- CLAUDE.md指示はソフト制約（物理的強制ではない）
- claude-nagger session_startupは通知・ガードレールであり、ファイル編集の物理ブロックではない
- 物理ブロックが必要な場合: ImplementationDesignHookへのSubagentMarkerManager統合で実現可能（将来対応）

### 1US = 1セッション（推奨運用）
- USの完了とセッションの完了が一致
- 大きなUSでセッションが長期化してもメインエージェントのcompact conversationで継続可能
- 次のUS開始時はチケットからコンテキスト復元

## 関連文書
- @docs/temps/subagent_workflow_discussion.md（検討経緯）
- @docs/rules/redmine_driven_dev.yaml（TiDD規約）
- @docs/specs/architecture.md
- packages/claude-nagger/.claude-nagger/config.yaml
- https://code.claude.com/docs/en/plugins（Claude Codeプラグイン公式ドキュメント）
- https://code.claude.com/docs/en/sub-agents（subagent公式ドキュメント）
- https://code.claude.com/docs/en/plugin-marketplaces（マーケットプレイス公式ドキュメント）
