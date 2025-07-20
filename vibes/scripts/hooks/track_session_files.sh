#!/bin/bash

# セッション内でのファイル変更を追跡するHookスクリプト
# PostToolUseイベントで実行され、変更されたファイルをセッションファイルに記録

# JSON入力を読み取り
INPUT=$(cat)

# セッションIDを取得
SESSION_ID=$(echo "$INPUT" | jq -r '.session.id // "default"')

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/log"
mkdir -p "$LOG_DIR"

# セッション追跡ファイルのパスを変更
SESSION_TRACKING_FILE="$LOG_DIR/claude_session_${SESSION_ID}"

# ツール名とツール入力を取得
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // {}')

# ファイル変更を追跡するツールのみ処理
case "$TOOL_NAME" in
    "Edit"|"MultiEdit"|"Write"|"NotebookEdit")
        # ファイルパスを取得
        FILE_PATH=""
        case "$TOOL_NAME" in
            "Edit"|"Write"|"NotebookEdit")
                FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // ""')
                ;;
            "MultiEdit")
                FILE_PATH=$(echo "$TOOL_INPUT" | jq -r '.file_path // ""')
                ;;
        esac
        
        # ファイルパスが取得できた場合のみ記録
        if [ -n "$FILE_PATH" ] && [ "$FILE_PATH" != "null" ]; then
            # 絶対パスに変換
            if [[ ! "$FILE_PATH" == /* ]]; then
                FILE_PATH="$(pwd)/$FILE_PATH"
            fi
            
            # セッション追跡ファイルに記録（重複を避けるため、既存をチェック）
            if ! grep -Fxq "$FILE_PATH" "$SESSION_TRACKING_FILE" 2>/dev/null; then
                echo "$FILE_PATH" >> "$SESSION_TRACKING_FILE"
            fi
        fi
        ;;
esac

# 正常終了
exit 0