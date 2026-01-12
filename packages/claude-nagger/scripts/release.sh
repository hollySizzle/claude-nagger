#!/bin/bash
# リリース自動化スクリプト
# Usage: ./scripts/release.sh <version> [--release-only]
# Example: ./scripts/release.sh 1.1.0
# Example: ./scripts/release.sh 1.1.0 --release-only  # GitHubリリース作成のみ
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

echo "=== Release $TAG ==="

if [ "$RELEASE_ONLY" = false ]; then
    # 未コミットの変更チェック
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "Error: Uncommitted changes exist"
        echo "Commit or stash changes before release"
        exit 1
    fi

    # 1. バージョン更新
    echo "Updating version to $VERSION..."
    sed -i "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml
    sed -i "s/^__version__ = \".*\"/__version__ = \"$VERSION\"/" src/shared/version.py

    # 2. コミット
    echo "Committing..."
    git add pyproject.toml src/shared/version.py
    git commit -m "Bump version to $VERSION"

    # 3. Push
    echo "Pushing..."
    git push origin main
else
    echo "Skipping version update/commit/push (--release-only)"
fi

# 4. GitHubリリース作成
echo "Creating GitHub release..."
gh release create "$TAG" --title "$TAG" --generate-notes --repo hollySizzle/claude-nagger

echo ""
echo "=== Release $TAG created ==="
echo "GitHub Actions will automatically publish to PyPI"
echo "Check: https://github.com/hollySizzle/claude-nagger/actions"
