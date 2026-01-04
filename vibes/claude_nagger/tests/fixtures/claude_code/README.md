# Claude Code テストフィクスチャ

## 概要
Claude Codeフックの結合テスト用実データフィクスチャ

## ディレクトリ構成
```
claude_code/
├── README.md           # 本ファイル
├── pre_tool_use/       # PreToolUseイベントのフィクスチャ
│   ├── edit/           # Editツール
│   ├── bash/           # Bashツール
│   └── write/          # Writeツール
└── post_tool_use/      # PostToolUseイベントのフィクスチャ
```

## 命名規則
`{event}_{tool}_{scenario}_{yyyymmdd}.json`

例: `pre_tool_use_edit_design_doc_20260104.json`

## フィクスチャ取得
```bash
# /tmp/claude/から最新データを取り込み（サニタイズ付き）
python scripts/capture_fixture.py --sanitize
```

## 注意事項
- コミット前に必ずサニタイズ実行
- 秘密情報（パス、ユーザー名等）は自動マスク
