#!/bin/bash

# PlantUMLエラー詳細表示スクリプト
# 使用方法: bin/plantuml_error_detail.sh [ファイルパス]

# カラー定義
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

PLANTUML_JAR="/usr/local/bin/plantuml.jar"

if [ $# -eq 0 ]; then
    echo "使用方法: $0 <PlantUMLファイルパス>"
    exit 1
fi

FILE_PATH="$1"

if [ ! -f "$FILE_PATH" ]; then
    echo -e "${RED}エラー: ファイルが見つかりません: $FILE_PATH${NC}"
    exit 1
fi

echo -e "${BLUE}PlantUMLエラー詳細解析${NC}"
echo "ファイル: $FILE_PATH"
echo "=========================================="

# エラー検出（軽量なSVG生成でエラーチェック）
# -syntaxよりも高速で確実なエラー検出
TEMP_SVG="/tmp/plantuml_check_$$.svg"
ERROR_OUTPUT=$(timeout 15s java -Djava.awt.headless=true -jar "$PLANTUML_JAR" -tsvg "$FILE_PATH" -o /tmp/ 2>&1)
EXIT_CODE=$?

# SVGファイルのクリーンアップ設定
SVG_FILE="/tmp/$(basename "${FILE_PATH%.*}").svg"
CLEANUP_SVG=true

if [ $EXIT_CODE -eq 124 ]; then
    echo -e "${YELLOW}⚠ タイムアウトが発生しました${NC}"
    # SVGファイルが存在する場合は削除
    if [ "$CLEANUP_SVG" = true ] && [ -f "$SVG_FILE" ]; then
        rm -f "$SVG_FILE"
        echo -e "${GRAY}✓ SVGファイルをクリーンアップしました: $SVG_FILE${NC}"
    fi
    exit 1
fi

# エラー行を抽出
ERROR_LINES=$(echo "$ERROR_OUTPUT" | grep -E "Error line [0-9]+" | head -5)

if [ -n "$ERROR_LINES" ]; then
    echo -e "${RED}エラーが検出されました${NC}"
    echo ""
    
    # 各エラー行について詳細表示
    echo "$ERROR_LINES" | while IFS= read -r error_line; do
        LINE_NUM=$(echo "$error_line" | grep -o "Error line [0-9]*" | grep -o "[0-9]*")
        
        if [ -n "$LINE_NUM" ]; then
            echo -e "${YELLOW}エラー行 $LINE_NUM:${NC}"
            echo "  $error_line"
            echo ""
            
            # 前後の行も表示（コンテキスト）
            echo -e "${BLUE}コンテキスト:${NC}"
            START_LINE=$((LINE_NUM - 2))
            END_LINE=$((LINE_NUM + 2))
            
            # 負の値チェック
            if [ $START_LINE -lt 1 ]; then
                START_LINE=1
            fi
            
            sed -n "${START_LINE},${END_LINE}p" "$FILE_PATH" | nl -ba -v"$START_LINE" | while IFS= read -r line; do
                line_number=$(echo "$line" | awk '{print $1}')
                line_content=$(echo "$line" | cut -c8-)
                
                if [ "$line_number" -eq "$LINE_NUM" ]; then
                    echo -e "  ${RED}→ $line_number: $line_content${NC}"
                else
                    echo -e "    ${GRAY}$line_number: $line_content${NC}"
                fi
            done
            echo ""
        fi
    done
else
    # その他のエラーメッセージをチェック
    OTHER_ERRORS=$(echo "$ERROR_OUTPUT" | grep -E "Some diagram|Cannot find|not found|Syntax Error|No diagram found" | head -5)
    if [ -n "$OTHER_ERRORS" ]; then
        echo -e "${RED}エラーが検出されました${NC}"
        echo ""
        echo "$OTHER_ERRORS" | while IFS= read -r error_msg; do
            echo -e "${YELLOW}エラー:${NC} $error_msg"
        done
    else
        echo -e "${GREEN}✓ エラーは検出されませんでした${NC}"
    fi
fi

echo ""
echo "=========================================="

# ファイルの基本情報
echo -e "${BLUE}ファイル情報:${NC}"
echo "- 総行数: $(wc -l < "$FILE_PATH")"
echo "- ファイルサイズ: $(ls -lh "$FILE_PATH" | awk '{print $5}')"
echo "- 図の数: $(grep -c "@startuml" "$FILE_PATH" 2>/dev/null || echo "0")"

# includeファイルの一覧
INCLUDES=$(grep -E "^!include" "$FILE_PATH" 2>/dev/null || true)
if [ -n "$INCLUDES" ]; then
    echo "- includeファイル:"
    echo "$INCLUDES" | while IFS= read -r inc_line; do
        inc_file=$(echo "$inc_line" | sed 's/!include //' | sed 's/^[[:space:]]*//')
        echo "  - $inc_file"
    done
else
    echo "- includeファイル: なし"
fi

# SVGファイルのクリーンアップ
if [ "$CLEANUP_SVG" = true ] && [ -f "$SVG_FILE" ]; then
    rm -f "$SVG_FILE"
    echo ""
    echo -e "${GRAY}✓ SVGファイルをクリーンアップしました: $SVG_FILE${NC}"
fi

# 終了コードを設定
if [ $EXIT_CODE -eq 124 ]; then
    # タイムアウトの場合
    exit 1
elif [ -n "$ERROR_LINES" ] || [ -n "$OTHER_ERRORS" ]; then
    # エラーが検出された場合
    exit 1
else
    # エラーなしの場合
    exit 0
fi