#!/bin/bash

# Markdownファイル編集・作成時のドキュメント参照チェックフック

# JSON入力を読み取り
input=$(cat)

# file_pathを抽出
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)

# ファイルパスが取得できない場合はスキップ
if [[ -z "$file_path" ]]; then
    exit 0
fi

# Markdownファイル（.md）でない場合はスキップ
if [[ "$file_path" != *.md ]]; then
    exit 0
fi

# Markdownファイルの場合、ドキュメント参照を促すメッセージを表示
echo "⚠️  ドキュメントは @CLAUDE.md の ## ドキュメント 項をよく確認し従うこと" >&2