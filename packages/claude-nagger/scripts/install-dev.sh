#!/bin/bash
# 開発版インストール/アップデート
# Usage: ./scripts/install-dev.sh
set -e

cd "$(dirname "$0")/.."

# uv toolのインストール先をPATHに追加
export PATH="$HOME/.local/bin:$PATH"

echo "Installing claude-nagger (dev)..."
uv tool install -e . --force

echo "Installing hooks..."
claude-nagger install-hooks

echo "Done."
