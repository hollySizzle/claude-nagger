#!/bin/bash

# Markdownファイル編集・作成時のドキュメント参照チェックフック

# ログファイルのパス
LOG_FILE="/tmp/claude_hooks_markdown_debug.log"

# ログ出力関数
log_debug() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log_debug "========== Markdown Hook Started =========="

# JSON入力を読み取り
input=$(cat)
log_debug "Input JSON length: ${#input}"

# jqが利用可能かチェック
if ! command -v jq &> /dev/null; then
    log_debug "ERROR: jq command not found"
    exit 0
fi

# セッションIDを抽出
SESSION_ID=$(echo "$input" | jq -r '.session_id // ""' 2>/dev/null)
log_debug "Session ID: $SESSION_ID"

# file_pathを抽出
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
log_debug "File path: $file_path"

# ファイルパスが取得できない場合はスキップ
if [[ -z "$file_path" ]]; then
    log_debug "No file path found, skipping"
    exit 0
fi

# Markdownファイル（.md）でない場合はスキップ
if [[ "$file_path" != *.md ]]; then
    log_debug "Not a markdown file, skipping"
    exit 0
fi

# セッションIDが取得できない場合はスキップ
if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
    log_debug "No valid session ID, skipping"
    exit 0
fi

# デフォルト値設定
TEMP_DIR=${TEMP_DIR:-"/tmp"}

# セッション専用のマーカーファイル
SESSION_MARKER="${TEMP_DIR}/claude_markdown_hook_session_${SESSION_ID}"
log_debug "Session marker file: $SESSION_MARKER"

# 既に実行済みの場合はスキップ
if [ -f "$SESSION_MARKER" ]; then
    log_debug "Session marker exists, skipping"
    exit 0
fi

# 実行済みマーカーを作成
touch "$SESSION_MARKER"
log_debug "Created session marker file"

# ブロックメッセージを構築
REASON_MESSAGE="⚠️  Markdownドキュメントの編集・作成時は @CLAUDE.md の ## ドキュメント 項をよく確認し従うこと\\n\\n📋 ドキュメント規約: @vibes/rules/documentation_standards.md を参照してください\\n\\n作業を続けるには、ドキュメント規約を確認したことを示してください。"
log_debug "Reason message constructed"

# JSON形式で出力（jqを使用して適切にエスケープ）
OUTPUT=$(jq -n --arg reason "$REASON_MESSAGE" '{decision: "block", reason: $reason}' 2>/dev/null)
EXIT_CODE=$?

log_debug "jq output generation exit code: $EXIT_CODE"
log_debug "Generated output: $OUTPUT"

if [ $EXIT_CODE -eq 0 ] && [ -n "$OUTPUT" ]; then
    echo "$OUTPUT"
    log_debug "Successfully output JSON"
else
    log_debug "ERROR: Failed to generate JSON output"
    exit 0
fi

log_debug "========== Markdown Hook Ended =========="