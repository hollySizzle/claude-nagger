---
name: tasuki-delegate
description: coder subagentへのタスク委譲を支援する。チケット番号・実装指示の構造化を行う。
---

# tasuki-delegate

coder subagentへタスクを委譲します。

## 使い方

```
/ticket-tasuki:tasuki-delegate #チケット番号
```

## 委譲時の必須情報

以下の情報を整理してcoder subagentに渡してください:

1. **チケット番号**: issue_{id} 形式
2. **実装意図**: なぜこの変更が必要か
3. **対象ファイル**: 編集すべきファイルのパス一覧
4. **実装指示**: 具体的な変更内容（何をどう変えるか）

## 注意

- 対象ファイルが不明な場合は、先にExplore subagentで調査してください
- 1回の委譲で1タスク（チケット）を扱ってください
