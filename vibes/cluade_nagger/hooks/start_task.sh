#!/bin/bash

# ログファイルのパス
LOG_FILE="/tmp/claude_hooks_debug.log"

# ログ出力関数
log_debug() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log_debug "========== Hook Script Started =========="

# 引数とstdinの状況をログに記録
log_debug "Script arguments: $@"
log_debug "Number of arguments: $#"

# 設定ファイルを読み込み
if [ -f "vibes/scripts/.env" ]; then
    source "vibes/scripts/.env"
    log_debug "Loaded .env file"
fi

# デフォルト値設定
INDEX_MD_PATH=${INDEX_MD_PATH:-"vibes/docs/INDEX.md"}
TEMP_DIR=${TEMP_DIR:-"/tmp"}
ADDITIONAL_MESSAGE="0. @docs/rules/ai_collaboration_standards.md を参照しプロジェクト進行フローを確認してください."
# HOOK_MESSAGE_PREFIX=${HOOK_MESSAGE_PREFIX:-"⚠️ "}
# HOOK_MESSAGE_SUFFIX=${HOOK_MESSAGE_SUFFIX:-"タスクの実行を続けるならば､以下を実行してください.\\n 1.参照するドキュメントを全て決定し出力してください 2."}

log_debug "Default values set: INDEX_MD_PATH=$INDEX_MD_PATH, TEMP_DIR=$TEMP_DIR"

# 標準入力が利用可能かチェック（タイムアウト付き）
log_debug "Checking if stdin is available..."
if timeout 5 cat /dev/null 2>/dev/null; then
    log_debug "stdin is available"
else
    log_debug "stdin is not available or timed out"
fi

# 標準入力からJSONを読み取る（タイムアウト付き）
log_debug "Attempting to read from stdin..."
INPUT=$(timeout 10 cat 2>/dev/null || echo "")
log_debug "stdin read completed"
log_debug "Input JSON length: ${#INPUT}"
log_debug "Input JSON: $INPUT"

# 引数からJSONを読み取る場合の処理
if [ -z "$INPUT" ] && [ $# -gt 0 ]; then
    log_debug "No stdin input, trying to parse arguments as JSON"
    INPUT="$1"
    log_debug "Argument JSON: $INPUT"
fi

# まだINPUTが空の場合は、基本的な情報でテスト
if [ -z "$INPUT" ]; then
    log_debug "No JSON input found, using default values"
    INPUT='{"session_id":"test_session","hook_event_name":"test_event"}'
    log_debug "Using default INPUT: $INPUT"
fi

# jqが利用可能かチェック
if ! command -v jq &> /dev/null; then
    log_debug "ERROR: jq command not found"
    echo '{"decision": "continue", "stopReason": "jq command not found"}' 
    exit 1
fi

log_debug "jq command found"

# jqを使用したJSONパース
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // ""' 2>/dev/null)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // ""' 2>/dev/null)
HOOK_EVENT_NAME=$(echo "$INPUT" | jq -r '.hook_event_name // ""' 2>/dev/null)
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)

log_debug "Parsed values: SESSION_ID=$SESSION_ID, TRANSCRIPT_PATH=$TRANSCRIPT_PATH, HOOK_EVENT_NAME=$HOOK_EVENT_NAME, STOP_HOOK_ACTIVE=$STOP_HOOK_ACTIVE"

# JSONパースのエラーチェック
if [ -z "$SESSION_ID" ] || [ "$SESSION_ID" = "null" ]; then
    log_debug "ERROR: Failed to parse session_id from input JSON"
    echo '{"decision": "continue", "stopReason": "Invalid JSON input"}' 
    exit 1
fi

# セッション専用のマーカーファイル
SESSION_MARKER="${TEMP_DIR}/claude_hooks_session_${SESSION_ID}"
log_debug "Session marker file: $SESSION_MARKER"

# 既に実行済みの場合はスキップ
if [ -f "$SESSION_MARKER" ]; then
    log_debug "Session marker exists, skipping"
    exit 0
fi

# 実行済みマーカーを作成
touch "$SESSION_MARKER"
log_debug "Created session marker file"

# INDEX.mdの存在チェックと動的メッセージ生成
if [ -f "$INDEX_MD_PATH" ]; then
    INDEX_MESSAGE="タスクの実行を続けるならば､以下を実行してください ${ADDITIONAL_MESSAGE} 1.${INDEX_MD_PATH}からタスクに関連するドキュメントを全て決定し出力してください"
    log_debug "INDEX.md found"
else
    INDEX_MESSAGE="⚠️ INDEX.mdが見つかりません (パス: ${INDEX_MD_PATH})"
    log_debug "INDEX.md not found"
fi

# reasonメッセージを構築
# REASON_MESSAGE="${HOOK_MESSAGE_PREFIX}\\n\\n${INDEX_MESSAGE}\\n\\n${HOOK_MESSAGE_SUFFIX}"
REASON_MESSAGE="${INDEX_MESSAGE}"
log_debug "Reason message constructed: $REASON_MESSAGE"

# exit code 2でblockingエラーとして出力（JSONではなく単純なstderr出力）
log_debug "Outputting blocking error via stderr"
echo "$REASON_MESSAGE" >&2
log_debug "Successfully output blocking message to stderr"
exit 2

log_debug "========== Hook Script Ended =========="