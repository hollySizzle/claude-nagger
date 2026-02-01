# ticket-tasuki

TiDD基盤のleader/coder分離プラグイン。

## 概要

1セッション内でleader（意思決定）とcoder（実装）を分離し、コンテキスト保護・バイアス排除・レビュー品質向上を実現する。

## アーキテクチャ

```
leader（メインエージェント）
  やること: 読む・判断する・指示する・レビューする
  やらないこと: コード編集
  │
  ├── coder subagent → コード実装
  ├── ticket-manager subagent → チケット操作
  ├── Explore subagent → コード調査
  └── Bash subagent → テスト実行
```

## インストール

```bash
claude --plugin-dir ./packages/ticket-tasuki
```

または `/plugin install` で導入。

## 依存

- **必須**: Claude Code、redmine-epic-grid MCP
- **推奨**: claude-nagger

## 構成

```
packages/ticket-tasuki/
  .claude-plugin/plugin.json    ← マニフェスト
  agents/coder.md               ← coder subagent定義（tools制限あり）
  skills/tasuki-setup/SKILL.md  ← セットアップskill
  skills/tasuki-delegate/SKILL.md ← coder委譲skill
  hooks/hooks.json              ← フック定義
  CLAUDE.md                     ← leader規約（ソフト制約）
```

## 制御方式

| 対象 | 制御手段 | 強制力 |
|------|---------|--------|
| leader | CLAUDE.md指示 | ソフト制約 |
| coder | agents/coder.mdのtools:フィールド | 物理的制限 |
| coder | claude-nagger subagent_types.coder | 通知レベル |
