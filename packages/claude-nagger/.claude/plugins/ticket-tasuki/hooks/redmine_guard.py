#!/usr/bin/env python3
"""ticket-tasuki Redmine操作ガード (プラグインhook)

PreToolUse hook: leader が直接実行するRedmine MCPツール呼び出しを検査し、
許可リスト外の操作（作成・ステータス変更等）をブロックする。
参照系 + コメント追加 + subject/description編集のみ許可。

Claude Code プラグインhook機構で ${CLAUDE_PLUGIN_ROOT}/hooks/redmine_guard.py として呼び出される。
"""

import json
import sys

# Redmine MCPツールのプレフィックス
REDMINE_TOOL_PREFIX = "mcp__redmine_epic_grid__"

# leaderに許可するツール（Read系 + 軽量Write系）
ALLOWED_TOOLS = {
    # Read系
    "mcp__redmine_epic_grid__get_issue_detail_tool",
    "mcp__redmine_epic_grid__list_epics_tool",
    "mcp__redmine_epic_grid__list_versions_tool",
    "mcp__redmine_epic_grid__list_user_stories_tool",
    "mcp__redmine_epic_grid__list_statuses_tool",
    "mcp__redmine_epic_grid__list_project_members_tool",
    "mcp__redmine_epic_grid__get_project_structure_tool",
    # 軽量Write系
    "mcp__redmine_epic_grid__add_issue_comment_tool",
    "mcp__redmine_epic_grid__update_issue_subject_tool",
    "mcp__redmine_epic_grid__update_issue_description_tool",
}

# ブロック時メッセージ
BLOCK_MESSAGE_TEMPLATE = """\
[claude-nagger] Redmine操作規約: leader直接操作の制限
━━━━━━━━━━━━━━━━━
検出: {tool_name}
対処:
1. この操作はscribeに委譲してください
2. leaderが直接実行できるRedmine操作: 参照系 + コメント追加 + subject/description編集のみ"""


def main():
    """stdinからPreToolUse入力JSONを読み、判定結果をstdoutに出力する"""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # 入力不正は無視して許可
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")

    # Redmine MCPツール以外は対象外
    if not tool_name.startswith(REDMINE_TOOL_PREFIX):
        sys.exit(0)

    # 許可リストに含まれるツールは通過
    if tool_name in ALLOWED_TOOLS:
        sys.exit(0)

    # ブロック: 許可リスト外のRedmineツール
    reason = BLOCK_MESSAGE_TEMPLATE.format(tool_name=tool_name)
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
