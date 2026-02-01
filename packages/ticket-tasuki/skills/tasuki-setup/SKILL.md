---
name: tasuki-setup
description: ticket-tasukiプラグインのセットアップ。leader/coder分離の動作確認と初期設定を行う。
---

# tasuki-setup

ticket-tasukiプラグインのセットアップを行います。

## 確認事項

1. プラグインが正しくロードされているか確認（/helpでticket-tasuki:が表示されること）
2. coder subagentが利用可能か確認（/agentsでcoderが表示されること）
3. CLAUDE.mdのleader規約が読み込まれているか確認
4. claude-naggarのcoder override設定が有効か確認

## 前提条件

- redmine-epic-grid MCPサーバーが設定済みであること
- claude-naggarが導入済みであること（推奨）
