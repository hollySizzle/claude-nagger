#!/bin/bash
# リリース自動化スクリプト
# Usage: ./scripts/release.sh <version> [--release-only]
# Example: ./scripts/release.sh 1.1.0
# Example: ./scripts/release.sh 1.1.0 --release-only  # GitHubリリース作成のみ
#
# 機能:
#   - バージョンバンプ強制チェック（config/hooks変更検出）
#   - pyproject.toml / version.py / plugin.json の同期更新
#   - CHANGELOG.md 自動生成
#   - GitHubリリース作成
set -e

cd "$(dirname "$0")/.."

# .env読み込み（GH_TOKEN等）
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# 引数チェック
if [ -z "$1" ]; then
    echo "Usage: $0 <version> [--release-only]"
    echo "Example: $0 1.1.0"
    echo "Example: $0 1.1.0 --release-only  # GitHubリリース作成のみ"
    exit 1
fi

VERSION="$1"
TAG="v$VERSION"
RELEASE_ONLY=false

if [ "$2" = "--release-only" ]; then
    RELEASE_ONLY=true
fi

# gh CLI認証チェック
if ! gh auth status &>/dev/null; then
    echo "Error: GitHub CLI not authenticated"
    echo "Run: gh auth login"
    echo "Or set GH_TOKEN in .env"
    exit 1
fi

# --- バージョンバンプ強制チェック ---
# 前回タグ以降にconfig/hooks/agents変更があれば、バージョンが前回と異なることを確認
check_version_bump() {
    # 前回タグ取得
    local last_tag
    last_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
    if [ -z "$last_tag" ]; then
        echo "Info: 前回タグなし（初回リリース）"
        return 0
    fi

    # 設定・フック関連ファイルの変更検出
    local config_changes
    config_changes=$(git diff --name-only "$last_tag"..HEAD -- \
        '.claude-nagger/config.yaml' \
        'src/domain/hooks/' \
        'src/domain/services/' \
        '.claude/plugins/' \
        2>/dev/null || echo "")

    if [ -n "$config_changes" ]; then
        echo ""
        echo "=== バージョンバンプチェック ==="
        echo "前回タグ($last_tag)以降に設定/フック変更を検出:"
        echo "$config_changes" | sed 's/^/  - /'
        echo ""

        # バージョン比較（前回タグからvプレフィックス除去）
        local last_version="${last_tag#v}"
        if [ "$VERSION" = "$last_version" ]; then
            echo "Error: config/hooks変更があるのにバージョンが前回($last_version)と同一です"
            echo "バージョンを上げてから再実行してください"
            exit 1
        fi
        echo "OK: バージョンバンプ確認 ($last_version → $VERSION)"
    fi
}

# --- CHANGELOG自動生成 ---
generate_changelog() {
    local last_tag
    last_tag=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
    local today
    today=$(date +%Y-%m-%d)

    echo "Generating CHANGELOG entry..."

    # git logからissue付きコミットを抽出
    local log_range
    if [ -n "$last_tag" ]; then
        log_range="${last_tag}..HEAD"
    else
        log_range="HEAD"
    fi

    local commits
    commits=$(git log "$log_range" --pretty=format:"- %s" --no-merges \
        | grep -v "^- Bump version" \
        || echo "")

    if [ -z "$commits" ]; then
        echo "Info: CHANGELOG対象コミットなし"
        return 0
    fi

    # 新エントリ作成
    local new_entry
    new_entry="## [$VERSION] - $today

$commits
"

    # CHANGELOG.mdの先頭ヘッダ直後に挿入
    if [ -f CHANGELOG.md ]; then
        # 最初の"## ["行の行番号を取得（既存エントリの先頭）
        local header_end
        header_end=$(grep -n '^## \[' CHANGELOG.md | head -1 | cut -d: -f1)
        if [ -n "$header_end" ]; then
            # 既存エントリの前に挿入
            {
                head -n $((header_end - 1)) CHANGELOG.md
                echo "$new_entry"
                tail -n +"$header_end" CHANGELOG.md
            } > CHANGELOG.md.tmp
            mv CHANGELOG.md.tmp CHANGELOG.md
        else
            echo "" >> CHANGELOG.md
            echo "$new_entry" >> CHANGELOG.md
        fi
    else
        cat > CHANGELOG.md << CHEOF
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

$new_entry
CHEOF
    fi

    echo "CHANGELOG.md updated"
}

# --- plugin.jsonバージョン同期 ---
update_plugin_json() {
    local plugin_json=".claude/plugins/ticket-tasuki/.claude-plugin/plugin.json"
    if [ -f "$plugin_json" ]; then
        echo "Updating plugin.json version..."
        sed -i "s/\"version\": \".*\"/\"version\": \"$VERSION\"/" "$plugin_json"
    fi
}

echo "=== Release $TAG ==="

if [ "$RELEASE_ONLY" = false ]; then
    # 未コミットの変更チェック
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "Error: Uncommitted changes exist"
        echo "Commit or stash changes before release"
        exit 1
    fi

    # バージョンバンプ強制チェック
    check_version_bump

    # 1. バージョン更新（pyproject.toml + version.pyフォールバック + plugin.json）
    echo "Updating version to $VERSION..."
    sed -i "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml
    sed -i "s/__version__ = \".*\"/__version__ = \"$VERSION\"/" src/shared/version.py
    update_plugin_json

    # 2. CHANGELOG生成
    generate_changelog

    # 3. コミット
    echo "Committing..."
    git add pyproject.toml src/shared/version.py CHANGELOG.md
    if [ -f ".claude/plugins/ticket-tasuki/.claude-plugin/plugin.json" ]; then
        git add -f ".claude/plugins/ticket-tasuki/.claude-plugin/plugin.json"
    fi
    git commit -m "Bump version to $VERSION"

    # 4. Push
    echo "Pushing..."
    git push origin main
else
    echo "Skipping version update/commit/push (--release-only)"
fi

# 5. GitHubリリース作成
echo "Creating GitHub release..."
gh release create "$TAG" --title "$TAG" --generate-notes --repo hollySizzle/claude-nagger

echo ""
echo "=== Release $TAG created ==="
echo "GitHub Actions will automatically publish to PyPI"
echo "Check: https://github.com/hollySizzle/claude-nagger/actions"
