# Conductor用規約定義書

Conductorパターン（方式D）で使用する規約定義書。
Task tool経由でgeneral-purpose subagentを呼び出す際に参照する。

## ファイル一覧

| ファイル | 用途 |
|---------|------|
| coder.md | coder subagent規約 |
| tester.md | tester subagent規約 |
| scribe.md | scribe subagent規約 |
| researcher.md | researcher subagent規約 |
| prompt-templates.md | 呼び出しテンプレート・タスク遷移フロー |

## 使い方

1. Task toolでsubagentを呼び出す際、promptの先頭に `[ROLE:xxx]` を付与
2. 各role規約に従った指示を記述
3. 詳細は `prompt-templates.md` を参照
