# TeamCreate経由subagentのin-processフォールバック問題

作成: 2026-03-06
関連: #7440, #7533
ステータス: 未起票（バグチケット化予定）

## 事象

TeamCreate + team_name指定でAgent起動 → backendType="in-process"（ローカルエージェント）にフォールバック。実subagent（tmux pane）として起動されない。

## 影響

- #7533テストシナリオが正しく実行できない（SubagentStart/PreToolUseフックが実subagent前提）
- in-processエージェントはシャットダウンリクエストに応答しない（プロセス状態確認手段なし）
- TeamDeleteが「active members」エラーでブロックされる（ゾンビメンバー）

## 原因分析

### agent_spawn_guard.py（L62-64）
- team_name指定ありなら無条件許可（backendType未検証）
- hookのPreToolUse時点ではbackendTypeは未確定（Claude Code内部で後から決定）

### 環境依存
- 前回セッションではtmuxが利用可能だった → TeamAgentが正常起動
- 今回セッションではtmux未起動/未インストール → in-processフォールバック
- tmuxの有無がセッション間で不安定

## 調査観点

1. **tmux環境**: なぜ前回セッションでは利用可能で今回は不可か。明示的インストール（Dockerfile等）が必要か
2. **PreToolUse時点のbackendType**: hookでbackendType判定が可能か（おそらく不可）
3. **SubagentStartフック**: SubagentStart時点でbackendType情報が提供されるか
4. **in-process vs tmux paneの差異**: hook発火パス（SubagentStart/PreToolUse）に実質的な差異があるか
5. **ゾンビメンバー問題**: in-processエージェント停止後にconfigからメンバーが削除されない問題の対処

## 暫定対処

- in-processでもRedmine API呼び出しは可能なため、チケット起票等の軽作業は実行可能
- #7533の実機テスト（hook発火検証）はtmux環境が確保できるまで保留

## 次アクション

- [ ] バグチケット起票（#7440配下）
- [ ] tmux環境調査（前回セッションとの差分特定）
- [ ] in-processエージェントのhook発火パス調査
