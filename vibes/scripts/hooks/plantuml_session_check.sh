#!/bin/bash

# セッション内で変更されたPlantUMLファイルのみをチェックするHookスクリプト
# PostToolUseイベントで実行され、.puファイルが変更された場合のみチェック

# JSON入力を読み取り
INPUT=$(cat)

# セッションIDを取得
SESSION_ID=$(echo "$INPUT" | jq -r '.session.id // "default"')

# スクリプトのディレクトリを取得
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/log"

# セッション追跡ファイルのパスを変更
SESSION_TRACKING_FILE="$LOG_DIR/claude_session_${SESSION_ID}"

# ツール名とツール入力を取得
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // ""')
TOOL_INPUT=$(echo "$INPUT" | jq -r '.tool_input // {}')

# .puファイルが変更されたかチェック
PU_FILE_MODIFIED=false

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
        
        # .puファイルが変更された場合
        if [[ "$FILE_PATH" == *.pu ]]; then
            PU_FILE_MODIFIED=true
        fi
        ;;
esac

# .puファイルが変更された場合のみPlantUMLチェックを実行
if [ "$PU_FILE_MODIFIED" = true ]; then
    echo "PlantUMLファイルが変更されました。セッション内変更ファイルをチェックします..."
    
    # PlantUMLチェックスクリプトを実行（セッションモード）
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
    
    # セッション内の変更ファイルのみをチェック
    export CLAUDE_SESSION_ID="$SESSION_ID"
    cd "$PROJECT_ROOT"
    bash "$SCRIPT_DIR/plantuml_check_all.sh"
    CHECK_EXIT_CODE=$?
    
    if [ $CHECK_EXIT_CODE -ne 0 ]; then
        # エラーが検出された場合、Claude에게 피드백 제공
        echo "PlantUMLエラーが検出されました。詳細を確認してください。" >&2
        exit 2  # Blocking error - Claudeにフィードバック
    fi
fi

# 正常終了
exit 0