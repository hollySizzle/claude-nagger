# LLM外部ファイル参照ベストプラクティス 調査結果

## 調査日時
2026-03-17

## 主要な発見

### 1. Claude Code @syntax の仕組み
- **@記号は強制的にファイル読み込み**: ユーザーが@path/to/fileと書くと、Claude Codeは**システムレベルで**ファイルをロードする
- CLAUDE.mdでも@path/to/fileで他ファイルをインポート可能
- これはClaude APIの相対パス参照とは異なり、**実装レベルでの強制**

### 2. なぜ「参照してください」が機能しないのか
- 相対パスでの文字列指示は**LLMへの単なるテキスト指示**
- LLMはこれを「推奨」と解釈し、見落とすことがある（特にコンテキストが満杯時）
- CLAUDE.mdの指示はコンテキストとして読み込まれるが、**強制ではなく助言**
- 指示が長い（200行超）と、重要なルールが埋もれて無視される傾向

### 3. 確実に読ませる書き方

#### ✅ 効果的なパターン
1. **@記号を使う**（ユーザー側）
   - @path/to/fileで明示的に参照
   - システムレベルでファイル読み込みが強制される

2. **CLAUDE.mdでインポート**
   - @path/to/fileシンタックスを使用
   - 定期的に読み込まれる

3. **具体的な要件を明文化**
   - 「参照してください」ではなく具体的ルール
   - テンプレート形式を明示

4. **パス+説明+条件の3要素**
   - パス指定、ルール説明、適用条件を明確に

#### ❌ 避けるべきパターン
- 相対パスだけの指示（テキスト形式）
- CLAUDE.mdの200行制限無視（重要ルールが埋もれる）
- 曖昧な指示（「参照してください」など）

### 4. 条件付き vs 無条件参照
- **無条件参照が確実**: 「作業開始前に常にRead」
- **条件付き参照は弱い**: 「レビュー時にRead」は見落とされやすい
- 理由: LLMのコンテキスト圧迫や判断の裁量化のため

### 5. パスの書き方の影響

| パス形式 | 効果度 | 備考 |
|---------|--------|------|
| 相対パス（テキスト） | 低い | 単なるテキスト指示 |
| @相対パス | 高い | CLAUDE.mdやプロンプト内 |
| @~/.claude/file.md | 高い | パーソナルプリファレンス |
| 絶対パス指示 | 中程度 | パス形式より内容の具体性が重要 |

## 推奨実装

### Agent定義書での書き方
```markdown
# 作業開始前チェック
[ ] @vibes/docs/rules/ticket_comment_templates.md を確認
[ ] @vibes/docs/specs/issue_format_spec.md を確認
```

### CLAUDE.mdでの組織
```markdown
# チケット処理規約
@vibes/docs/rules/ticket_comment_templates.md

# テンプレート形式（具体的な要件）
- チケットコメントにissue_IDを含める
- **Why:** セクション記載必須
- **How:** セクション記載必須
- Markdown形式で記載
```

**重要**: CLAUDE.mdでインポート + 具体的ルール明文化の組み合わせが最強の組み合わせ。

## 参考資料
- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)
- [How Claude remembers your project](https://code.claude.com/docs/en/memory)
- [Prompting best practices - Claude API Docs](https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices)
- [Reference Files with @ in Claude Code](https://mcpcat.io/guides/reference-other-files/)
