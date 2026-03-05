# issue_7435 テスト計画・バグ報告

## テスト計画

### B案: SessionStart残骸自動削除

**対象**: `ticket-tasuki/hooks/session_cleanup.py` + `hooks.json`

| # | シナリオ | 入力 | 期待結果 |
|---|---------|------|---------|
| 1 | startup時に残骸削除 | source="startup", `~/.claude/teams/` `~/.claude/tasks/` 存在 | 両ディレクトリ削除 |
| 2 | resume時はスキップ | source="resume", 同ディレクトリ存在 | 削除されない |
| 3 | compact時はスキップ | source="compact" | 削除されない |
| 4 | clear時はスキップ | source="clear" | 削除されない |
| 5 | 対象ディレクトリ不在 | source="startup", ディレクトリなし | エラーなく正常終了 |
| 6 | 不正JSON入力 | 壊れたJSON | エラーなく正常終了(exit 0) |

### A案: leader_constraint_guard除外パターン

**対象**: `ticket-tasuki/hooks/leader_constraint_guard.py` L93-96

| # | シナリオ | 入力コマンド | 期待結果 |
|---|---------|-------------|---------|
| 1 | teams削除許可 | `rm -rf ~/.claude/teams/` | allow |
| 2 | tasks削除許可 | `rm -rf ~/.claude/tasks/` | allow |
| 3 | 両方削除許可 | `rm -rf ~/.claude/teams/ ~/.claude/tasks/` | allow |
| 4 | gitコマンド許可 | `git status` | allow(既存動作) |
| 5 | 他rmコマンド拒否 | `rm -rf /tmp/something` | deny |
| 6 | 他Bashコマンド拒否 | `ls -la` | deny |
| 7 | subagentはスキップ | agent_context="subagent", 任意コマンド | allow(既存動作) |

## バグ報告: PMO role誤認識

**発見元**: Redmine #7435 コメント #31921
**発生状況**: pmoロールが`create_task_tool`実行時、hookが「tech-leadはこのRedmineツールの使用が禁止」とブロック
**再現性**: リトライしても同一エラー（永続的ブロック）

**症状**:
- pmoがtech-leadとして誤認識される
- pmoのRedmineツール使用がtech-lead制約でブロックされる

**影響**: pmoによるTask起票が不可能。leaderによる代行が必要になる

**推定原因**: hookのロール判定ロジックがpmoをtech-leadと誤判定している可能性。`leader_constraint_guard.py`のagent_context/agent_id判定、またはclaude-nagger側のscope判定を調査する必要がある

**関連ファイル**:
- `ticket-tasuki/hooks/leader_constraint_guard.py` — agent_context判定
- claude-nagger hook — scope/role判定ロジック
