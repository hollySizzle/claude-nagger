#!/bin/bash

# 全PlantUMLファイルのエラーチェックスクリプト
# 使用方法: 
#   bash vibes/scripts/hooks/plantuml_check_all.sh       (変更されたファイルのみ)
#   bash vibes/scripts/hooks/plantuml_check_all.sh --all (全ファイル)

# カラー定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
# PWDを変更しないでそのまま実行（パス問題を回避）

# ログディレクトリとファイルの設定
LOG_DIR="$SCRIPT_DIR/log"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
LOG_FILE="$LOG_DIR/plantuml_check_${TIMESTAMP}.log"
LATEST_LOG="$LOG_DIR/plantuml_check_latest.log"

# 既存のplantuml_check_error.shのパス
PLANTUML_CHECK_SCRIPT="${SCRIPT_DIR}/lib/plantuml_check_error.sh"

# 統計変数
total_files=0
error_files=0
success_files=0

# 結果配列
declare -a error_file_list
declare -a success_file_list

# ログ出力関数
log_message() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local log_entry="[$timestamp] [$level] $message"
    
    # ログファイルに出力
    echo "$log_entry" >> "$LOG_FILE"
    
    # 最新ログファイルにも出力
    echo "$log_entry" >> "$LATEST_LOG"
}

# ログ初期化
init_log() {
    echo "===============================================" > "$LOG_FILE"
    echo "PlantUML Error Check Log - $TIMESTAMP" >> "$LOG_FILE"
    echo "Project Root: $PROJECT_ROOT" >> "$LOG_FILE"
    echo "Script Dir: $SCRIPT_DIR" >> "$LOG_FILE"
    echo "Session ID: ${CLAUDE_SESSION_ID:-default}" >> "$LOG_FILE"
    echo "===============================================" >> "$LOG_FILE"
    
    # 最新ログファイルにコピー
    cp "$LOG_FILE" "$LATEST_LOG"
}

echo -e "${BLUE}PlantUML全ファイルエラーチェック開始${NC}"
echo "プロジェクトルート: $PROJECT_ROOT"
echo "=========================================="

# ログ初期化
init_log
log_message "INFO" "PlantUML error check started"

# PlantUMLファイルを検索
echo -e "${BLUE}PlantUMLファイルを検索中...${NC}"

# セッション追跡ファイルからClaudeが変更したファイルを取得
SESSION_TRACKING_FILE="$SCRIPT_DIR/log/claude_session_${CLAUDE_SESSION_ID:-default}"
claude_modified_pu_files=""

if [ -f "$SESSION_TRACKING_FILE" ] && [ "${1:-}" != "--all" ]; then
    echo "検索方法: セッション内でClaudeが変更したファイル"
    log_message "INFO" "Using session tracking file: $SESSION_TRACKING_FILE"
    # セッション追跡ファイルから.puファイルのみを抽出
    claude_modified_pu_files=$(grep "\.pu$" "$SESSION_TRACKING_FILE" 2>/dev/null || true)
    
    if [ -n "$claude_modified_pu_files" ]; then
        echo -e "${GREEN}セッション内で変更された.puファイルを検出しました${NC}"
        log_message "INFO" "Found session-modified .pu files: $(echo "$claude_modified_pu_files" | wc -l) files"
        pu_files="$claude_modified_pu_files"
    else
        echo -e "${YELLOW}セッション内で変更された.puファイルがありません${NC}"
        echo -e "${GRAY}全ファイルをチェックする場合: $0 --all${NC}"
        log_message "INFO" "No session-modified .pu files found, exiting"
        exit 0
    fi
elif [ "${1:-}" = "--all" ] || [ "${1:-}" = "-a" ]; then
    echo "検索方法: 全PlantUMLファイル"
    log_message "INFO" "Checking all PlantUML files (--all option)"
    # gitリポジトリのルートから検索範囲を拡張
    search_root="$(cd "$PROJECT_ROOT" && cd .. && pwd 2>/dev/null || echo "$PROJECT_ROOT")"
    pu_files=$(find "$search_root" -name "*.pu" -type f | sort)
else
    echo -e "${YELLOW}セッション追跡ファイルがありません${NC}"
    echo -e "${GRAY}全ファイルをチェックする場合: $0 --all${NC}"
    log_message "INFO" "No session tracking file found, exiting"
    exit 0
fi

if [ -z "$pu_files" ]; then
    echo -e "${YELLOW}⚠ PlantUMLファイルが見つかりませんでした${NC}"
    exit 0
fi

# ファイル数を表示
total_files=$(echo "$pu_files" | wc -l)
echo -e "${GREEN}検出されたファイル数: $total_files${NC}"
echo ""

# 各ファイルをチェック
current_file=0
while IFS= read -r pu_file; do
    current_file=$((current_file + 1))
    
    # 相対パスを取得
    relative_path=$(realpath --relative-to="$PROJECT_ROOT" "$pu_file")
    
    echo -e "${BLUE}[$current_file/$total_files] チェック中: $relative_path${NC}"
    log_message "INFO" "Checking file [$current_file/$total_files]: $relative_path"
    
    # plantuml_check_error.shを実行
    if [ -f "$PLANTUML_CHECK_SCRIPT" ]; then
        check_result=$(bash "$PLANTUML_CHECK_SCRIPT" "$pu_file" 2>&1)
        check_exit_code=$?
        
        # エラーの有無を判定（終了コードで判定）
        if [ $check_exit_code -eq 0 ]; then
            echo -e "  ${GREEN}✓ OK${NC}"
            log_message "SUCCESS" "File passed: $relative_path"
            success_files=$((success_files + 1))
            success_file_list+=("$relative_path")
        else
            echo -e "  ${RED}✗ エラーあり${NC}"
            log_message "ERROR" "File failed: $relative_path"
            log_message "ERROR" "Check result: $(echo "$check_result" | tr '\n' ' ')"
            error_files=$((error_files + 1))
            error_file_list+=("$relative_path")
        fi
    else
        echo -e "  ${YELLOW}⚠ plantuml_check_error.shが見つかりません${NC}"
        log_message "WARNING" "plantuml_check_error.sh not found"
    fi
    
    echo ""
done <<< "$pu_files"

# 結果サマリー
echo "=========================================="
echo -e "${BLUE}チェック結果サマリー${NC}"
echo "総ファイル数: $total_files"
echo -e "成功: ${GREEN}$success_files${NC}"
echo -e "エラー: ${RED}$error_files${NC}"
echo ""

# エラーファイルリスト
if [ $error_files -gt 0 ]; then
    echo -e "${RED}エラーが検出されたファイル:${NC}"
    printf '%s\n' "${error_file_list[@]}" | while IFS= read -r error_file; do
        echo -e "  ${RED}✗${NC} $error_file"
    done
    echo ""
fi

# 成功ファイルリスト（詳細モード）
if [ "${1:-}" = "--verbose" ] || [ "${1:-}" = "-v" ]; then
    echo -e "${GREEN}エラーのないファイル:${NC}"
    printf '%s\n' "${success_file_list[@]}" | while IFS= read -r success_file; do
        echo -e "  ${GREEN}✓${NC} $success_file"
    done
    echo ""
fi

# ログにサマリーを記録
log_message "INFO" "Check completed. Total: $total_files, Success: $success_files, Error: $error_files"
if [ $error_files -gt 0 ]; then
    log_message "ERROR" "Error files: $(printf '%s ' "${error_file_list[@]}")"
fi

# ログファイル情報を表示
echo ""
echo -e "${BLUE}ログファイル:${NC}"
echo "  詳細ログ: $LOG_FILE"
echo "  最新ログ: $LATEST_LOG"

# 終了コード
if [ $error_files -gt 0 ]; then
    log_message "ERROR" "Exiting with error code 2"
    # stderrにエラーメッセージを出力（Claude Code hooksの仕様）
    echo -e "${RED}エラーが検出されました。個別のエラー詳細は以下のコマンドで確認できます:${NC}" >&2
    echo "  bash bin/plantuml_check_error.sh [ファイルパス]" >&2
    # エラーファイルリストもstderrに出力
    echo "" >&2
    echo "エラーが検出されたファイル:" >&2
    printf '%s\n' "${error_file_list[@]}" | while IFS= read -r error_file; do
        echo "  ✗ $error_file" >&2
    done
    exit 2
    
else
    log_message "INFO" "All files passed, exiting with success"
    echo -e "${GREEN}すべてのPlantUMLファイルは正常です${NC}"
    exit 0
fi