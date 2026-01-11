#!/bin/bash
# claude-nagger ローカルテスト環境セットアップ
#
# ============================================================================
# 目的
# ============================================================================
# このスクリプトは以下をテストします:
#   ✅ install-hooks コマンドのファイル生成が正しいか
#   ✅ 生成される settings.json の構造が正しいか
#   ✅ 生成される .claude-nagger/ 設定ファイルが正しいか
#
# このスクリプトではテストできないこと:
#   ❌ フックが実際に発火するか（別セッションでのE2Eテストが必要）
#   ❌ フック発火時のメッセージ表示が正しいか
#
# ============================================================================
# E2Eテスト手順（フック発火の確認）
# ============================================================================
# 1. このスクリプトでテスト環境を作成:
#      ./scripts/setup_test_env.sh --run
#
# 2. 別ターミナルでテスト環境に移動し、Claude Codeを起動:
#      cd /tmp/claude-nagger-test
#      claude
#
# 3. Claude Codeで何かファイル編集操作をしてフック発火を確認
#
# 4. フィクスチャをキャプチャ（元のターミナルで）:
#      ./scripts/setup_test_env.sh --capture
#
# ============================================================================
# 使い方
# ============================================================================
#   ./scripts/setup_test_env.sh          # テスト環境構築
#   ./scripts/setup_test_env.sh --run    # install-hooks実行・結果確認
#   ./scripts/setup_test_env.sh --capture # フィクスチャキャプチャ
#   ./scripts/setup_test_env.sh --test   # スキーマ検証テスト
#   ./scripts/setup_test_env.sh --clean  # クリーンアップ
#   ./scripts/setup_test_env.sh --e2e    # E2Eテスト手順を表示

set -e

# 設定
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
TEST_DIR="/tmp/claude-nagger-test"
CLAUDE_NAGGER_PATH="$PROJECT_ROOT"

# 色付き出力
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

# クリーンアップ
cleanup() {
    log_info "テスト環境をクリーンアップ..."
    rm -rf "$TEST_DIR"
    log_success "クリーンアップ完了"
}

# テスト環境セットアップ
setup() {
    log_info "テスト環境を構築: $TEST_DIR"

    # ディレクトリ作成
    mkdir -p "$TEST_DIR"
    cd "$TEST_DIR"

    # 疑似プロジェクト構造を作成
    mkdir -p src tests docs

    # サンプルファイル作成
    cat > src/main.py << 'EOF'
"""サンプルプロジェクト"""

def main():
    print("Hello, World!")

if __name__ == "__main__":
    main()
EOF

    cat > README.md << 'EOF'
# Test Project

claude-nagger テスト用プロジェクト
EOF

    # pyproject.toml (テスト用)
    cat > pyproject.toml << 'EOF'
[project]
name = "test-project"
version = "0.1.0"
EOF

    log_success "テストプロジェクト作成完了"

    # 状態表示
    echo ""
    log_info "テストディレクトリ: $TEST_DIR"
    log_info "claude-nagger パス: $CLAUDE_NAGGER_PATH"
    echo ""
    echo "次のコマンドでテスト可能:"
    echo ""
    echo "  cd $TEST_DIR"
    echo "  uvx --from $CLAUDE_NAGGER_PATH claude-nagger install-hooks --dry-run"
    echo "  uvx --from $CLAUDE_NAGGER_PATH claude-nagger install-hooks"
    echo ""
}

# install-hooks実行
run_install() {
    log_info "install-hooks を実行..."
    cd "$TEST_DIR"

    # dry-run
    log_info "[dry-run]"
    uvx --from "$CLAUDE_NAGGER_PATH" claude-nagger install-hooks --dry-run
    echo ""

    # 実行
    log_info "[実行]"
    uvx --from "$CLAUDE_NAGGER_PATH" claude-nagger install-hooks
    echo ""

    # 結果確認
    log_info "生成されたファイル:"
    echo ""
    if [ -d ".claude" ]; then
        echo ".claude/"
        ls -la .claude/
        echo ""
        if [ -f ".claude/settings.json" ]; then
            echo "=== .claude/settings.json ==="
            cat .claude/settings.json
            echo ""
        fi
    fi

    if [ -d ".claude-nagger" ]; then
        echo ".claude-nagger/"
        ls -la .claude-nagger/
    fi

    log_success "install-hooks 完了"
}

# フィクスチャキャプチャ
capture() {
    log_info "フィクスチャをキャプチャ..."
    cd "$PROJECT_ROOT"
    python3 scripts/capture_fixture.py --sanitize -n 10

    log_info "フィクスチャ一覧:"
    python3 scripts/capture_fixture.py --list

    log_success "キャプチャ完了"
}

# テスト実行
run_tests() {
    log_info "スキーマ検証テスト実行..."
    cd "$PROJECT_ROOT"
    python3 -m pytest tests/test_hook_schema_validation.py -v
    log_success "テスト完了"
}

# E2Eテスト手順表示
show_e2e_guide() {
    echo ""
    echo "=============================================="
    echo "  E2Eテスト手順（フック発火の確認）"
    echo "=============================================="
    echo ""
    echo "【このスクリプトでテストできること】"
    echo "  ✅ install-hooks のファイル生成"
    echo "  ✅ settings.json の構造"
    echo ""
    echo "【E2Eテストが必要なこと】"
    echo "  ❌ フックが実際に発火するか"
    echo "  ❌ フック発火時のメッセージ表示"
    echo ""
    echo "【手順】"
    echo ""
    echo "  1. テスト環境を作成（このターミナル）:"
    echo "     ./scripts/setup_test_env.sh --run"
    echo ""
    echo "  2. 別ターミナルでClaude Codeを起動:"
    echo "     cd /tmp/claude-nagger-test"
    echo "     claude"
    echo ""
    echo "  3. Claude Codeでファイル編集操作を実行"
    echo "     → フックが発火してメッセージが表示されるか確認"
    echo ""
    echo "  4. フィクスチャをキャプチャ（このターミナル）:"
    echo "     ./scripts/setup_test_env.sh --capture"
    echo ""
    echo "=============================================="
}

# メイン処理
case "${1:-}" in
    --clean)
        cleanup
        ;;
    --run)
        if [ ! -d "$TEST_DIR" ]; then
            setup
        fi
        run_install
        ;;
    --capture)
        capture
        ;;
    --test)
        run_tests
        ;;
    --e2e)
        show_e2e_guide
        ;;
    --all)
        cleanup
        setup
        run_install
        # Note: capture/test は現在のセッションのフィクスチャを対象とする
        # E2Eテストは別セッションで手動実行が必要
        capture
        run_tests
        ;;
    --help|-h)
        echo "claude-nagger ローカルテスト環境"
        echo ""
        echo "=============================================="
        echo "  テスト範囲"
        echo "=============================================="
        echo "  ✅ install-hooks ファイル生成テスト"
        echo "  ❌ フック発火テスト（別セッションで手動確認）"
        echo ""
        echo "=============================================="
        echo "  コマンド"
        echo "=============================================="
        echo "  $0              テスト環境セットアップ"
        echo "  $0 --run        install-hooks実行・結果確認"
        echo "  $0 --capture    フィクスチャキャプチャ"
        echo "  $0 --test       スキーマ検証テスト実行"
        echo "  $0 --clean      クリーンアップ"
        echo "  $0 --e2e        E2Eテスト手順を表示"
        echo "  $0 --all        自動テスト全実行"
        echo ""
        echo "E2Eテスト手順は --e2e で確認してください"
        ;;
    *)
        setup
        ;;
esac
