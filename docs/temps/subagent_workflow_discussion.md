# ticket-tasuki - サブエージェント活用方針 調査・検討メモ

## 概要
**目的**: claude-nagger subagent機能の活用方針決定
**課題**: マルチセッション手動切替コストの削減
**期間**: 2026-02-01

## 背景: 現行ワークフロー

Agent1(PM) → Agent2(開発) → Agent3(レビュー) を手動切替で運用中。
切替コスト・コンテキスト喪失が課題。

## 検討した選択肢

### A. tmux + マルチセッション（multi-agent-shogun方式）
- **概要**: tmux send-keys + YAMLファイルで複数Claude Codeセッションを連携
- **参考**: [multi-agent-shogun](https://github.com/yohey-w/multi-agent-shogun)
- **却下理由**:
  - send-keys通信が脆弱（2回分割ルール等のバグ源）
  - 並列化が強みだが、当ワークフローは直列（dev→review→fix）
  - YAML通信プロトコルはClaude Code既存機能の再発明

### B. 1セッション統合 + subagent活用
- **概要**: leader役のメインエージェントが判断・レビューを担当、実装はcoder subagentに委譲
- **利点**: コンテキスト維持、切替コスト削減、実装と判断の分離
- **課題**: subagentの出力フィルタリング問題、Context low問題

### C. claude-nagger にオーケストレーション追加
- **概要**: チケットステータス変更をトリガーに引き継ぎ情報を自動生成
- **利点**: 既存TiDD規約との親和性

### 採択: B + C ハイブリッド
TiDD規約 + claude-nagger のフック強制により、チケットコメントがセッション間の「共有メモリ」として機能する。

## 決定: エージェント設計

### システム名称
**ticket-tasuki**: TiDD基盤のエージェント間コンテキストリレー機構
- `ticket-` でTiDD基盤を明示、`tasuki` で駅伝の襷リレー（コンテキスト受け渡し）を暗示

### 命名規則
`-er` 統一: leader / coder / tester
- 業界標準で説明不要、SIer臭なし、責務が名前から直接読める
- 軍制メタファー（shogun等）は却下: 技術ドキュメントとしての可読性優先

### 設計思想
- **leaderとcoderの分離**: 意思決定者は実装しない、実装者は判断しない
- **バイアス排除**: leaderは自分が書いていないコードを客観的にレビューできる
- **コンテキスト保護**: leaderのコンテキストを実装詳細で圧迫させない
- **1US = 1セッション**: USの完了とセッションの完了が一致

### エージェント構成

```
leader（メインエージェント）
  責務: 意思決定・レビュー・オーナー窓口・タスク分解
  やること: 読む・判断する・指示する・レビューする
  やらないこと: コード編集
  │
  ├── coder subagent → コード実装（判断しない、指示通りに実装）
  │     - leaderがUSをTask粒度に分解してから渡す
  │     - Context low対策: 1Task = 1subagent起動
  │
  ├── ticket-manager subagent → チケット操作
  │     - ステータス変更・コメント記載・構造確認
  │
  ├── Explore subagent → コード調査（読取専用）
  │
  ├── Bash subagent → テスト実行・ビルド確認
  │
  ├── general-purpose subagent → Web調査
  │
  └── （将来）tester subagent → テスト設計・実行・結果報告
```

### 分離の根拠
| 観点 | leaderが実装兼務 | leader/coder分離 |
|------|-----------------|-------------------|
| コンテキスト | 実装詳細で圧迫される | 意図・判断・経緯が残る |
| レビュー品質 | 自作バイアスが混入 | 他人のコードとして客観評価 |
| タスク分解 | 実装中に視野が狭まる | 俯瞰的に設計・分解できる |

### Context low対策
leaderがUSをTask粒度に分解してからsubagentに渡す:
```
US#123「ユーザー登録機能」
  → Task1: バリデーション追加（1ファイル）→ coder subagent A
  → Task2: DB保存処理（1ファイル）→ coder subagent B
  → Task3: エラーハンドリング（1ファイル）→ coder subagent C
```
これはleaderの本来の仕事（設計・分解）であり、責務と一致する。

## 調査結果: subagent の実態（Reddit・GitHub・事例）

### 有効なユースケース
- 読取専用の探索・検索（Explore）
- チケット操作の委譲（ticket-manager）
- 並列コードベース検索
- 明確な境界を持つ小タスク
- **指示が明確な実装タスク（判断不要・1ファイル程度）**

### 既知の問題
| 問題 | 深刻度 | 出典 |
|------|--------|------|
| コンテキスト喪失（白紙起動） | 高 | [GitHub #4908](https://github.com/anthropics/claude-code/issues/4908) |
| 親エージェントが出力を美化 | 高 | [Medium記事](https://medium.com/@gabi.beyo/the-hidden-truth-about-claude-code-sub-agents-when-your-ai-assistant-filters-reality-cdc39af32309) |
| 並列時のコンテキスト枯渇 | 中 | [GitHub #14867](https://github.com/anthropics/claude-code/issues/14867) |
| ネスト不可（subagent→subagent） | 中 | [GitHub #19077](https://github.com/anthropics/claude-code/issues/19077) |
| ~20kトークンのオーバーヘッド/subagent | 低 | [iBuildWith.ai](https://www.ibuildwith.ai/blog/task-tool-vs-subagents-how-agents-work-in-claude-code/) |
| resume時のコンテキスト漂流 | 中 | [GitHub #11712](https://github.com/anthropics/claude-code/issues/11712) |

### 業界事例
- **Boris Cherny（Claude Code作者）**: マルチターミナル方式を採用（subagentではない）
- **PubNub**: フック連鎖パターンでsubagentパイプライン構築（PM→Architect→Implementer）
- **命名の罠**: `code-reviewer`等の名前はClaude組込み動作を誘発。抽象名を推奨

## TiDD規約によるコンテキスト維持の評価

### コンテキスト復元の情報源
1. **git log + コミットメッセージ**（issue_{id}付き）→ 何をどう変えたか
2. **git diff** → 実際のコード変更
3. **チケットコメント**（構造化テンプレート）→ なぜそうしたか、判断事項
4. **親チケット** → 上位の意図・経緯
5. **規約**（redmine_driven_dev.yaml）→ プロジェクトルール
6. **claude-nagger** → 規約の強制実行

### 既存の保護機構（redmine_driven_dev.yaml）
- `must`: 中間報告の強制（意思決定のたびにチケットへ書出し）
- `must_not`: 中間報告なしの作業続行禁止
- `must`: 親チケット読込による上位コンテキスト復元
- コメントテンプレート: 判断事項・実施済み・実施予定を構造化

### claude-nagger による強制
- `session_startup`: セッション開始時に規約提示（subagent種別ごとにオーバーライド可能）
- `PreToolUse`: ファイル変更前にチケット追跡を強制
- subagentマーカー管理: SubagentStart/Stop イベントでライフサイクル追跡

### 評価: 90%以上のケースで機能
- 中間報告強制により暗黙知の大部分が形式知化される
- フックが規約違反を実行時検知
- チケットがtmux send-keysの上位互換（永続・構造化・検索可能）
- コミットID + チケット番号の紐付けでソースコード追跡も可能

### 残存リスクと対策
- **却下案の記録漏れ**: コメントテンプレートに「却下案」欄追加を推奨
- **コメント量爆発（20件超）**: 長期USでは要約が必要
- **出力美化問題**: leaderがレビューを担当することで構造的に回避

## 次のアクション

1. `redmine_driven_dev.yaml` のコメントテンプレートに「却下案」欄追加
2. `.claude-nagger/config.yaml` のsubagent_types に委譲ルール明文化
3. coder subagentの定義・プロンプト設計

## 関連文書
- @docs/specs/ticket_tasuki.md（ticket-tasuki要件定義）
- @docs/rules/redmine_driven_dev.yaml
- packages/claude-nagger/.claude-nagger/config.yaml
- packages/claude-nagger/src/domain/hooks/subagent_event_hook.py
- packages/claude-nagger/src/domain/services/subagent_marker_manager.py
