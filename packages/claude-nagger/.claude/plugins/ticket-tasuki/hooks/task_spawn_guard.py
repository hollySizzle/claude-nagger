#!/usr/bin/env python3
"""ticket-tasuki Task spawn ガード (プラグインhook)

PreToolUse hook:
- ticket-tasuki:* の Task 直接起動をブロックし、Agent Teams (team_name指定) 経由の起動は許可する。
- team_name未指定のTask spawnを原則ブロック（ビルトイン軽量エージェントは例外許可）。
- promptにissue_{id}が含まれない場合はユーザー確認を要求する。

設計思想: leaderのコンテキストウィンドウを守るため、ad-hoc Taskエージェントの起動を制限し、
既存チームエージェント（tech-lead, PMO等）への委譲またはleader自身の直接実行を促す。

Claude Code プラグインhook機構で ${CLAUDE_PLUGIN_ROOT}/hooks/task_spawn_guard.py として呼び出される。
"""

import json
import re
import sys

# ブロック対象プレフィックス
BLOCKED_PREFIX = "ticket-tasuki:"

# team_name不要で許可するsubagent_type（ビルトイン軽量エージェント）
TEAM_EXEMPT_TYPES = {"Explore", "Plan", "Bash", "statusline-setup", "claude-code-guide"}

# ブロック時メッセージ (ticket-tasuki:* 直接起動)
BLOCK_MESSAGE_TEMPLATE = """\
Task spawn規約: ticket-tasuki プラグインの直接起動禁止
━━━━━━━━━━━━━━━━━
検出: subagent_type="{subagent_type}"
対処:
1. Agent Teams（team_name指定）経由で起動してください
2. Task ツールでの ticket-tasuki:* subagent_type 直接指定は禁止です

⚠ 迂回禁止: general-purpose エージェント等の代替エージェントで
同等の作業を実行することも禁止されています。
必ず Agent Teams 経由で正規の手順に従ってください。"""

# team_name未指定ブロック時のメッセージ
NO_TEAM_BLOCK_TEMPLATE = """\
Task spawn規約: team_name未指定のTask spawn制限
━━━━━━━━━━━━━━━━━
検出: subagent_type="{subagent_type}" (team_name未指定)
対処:
1. Agent Teams (team_name指定) 経由で起動してください
2. 常駐エージェント (tech-lead, PMO等) にSendMessageで委譲してください
3. 1-3ツールコールで済む作業はleader自身で直接実行してください

⚠ team_name不要のエージェント: Explore, Plan, Bash のみ"""

# issue_{id}パターン（トレーサビリティチェック用）
ISSUE_ID_PATTERN = re.compile(r"issue_\d+")

# issue_{id}欠落時の警告メッセージ
ISSUE_ID_WARN_MESSAGE = """\
⚠ Task promptにissue_{id}が含まれていません。
トレーサビリティのため、promptにissue_{id}（例: issue_1234）を含めてください。"""


def _has_issue_id(prompt: str) -> bool:
    """promptにissue_{id}パターンが含まれるか判定"""
    if not prompt:
        return False
    return bool(ISSUE_ID_PATTERN.search(prompt))


def _emit_and_exit(output: dict | None) -> None:
    """判定結果を出力して終了する。Noneなら出力なし（許可）"""
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


def _make_issue_id_warn_output() -> dict:
    """issue_{id}欠落時の警告出力を生成（ユーザー確認要求）"""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": ISSUE_ID_WARN_MESSAGE,
        }
    }


def main():
    """stdinからPreToolUse入力JSONを読み、判定結果をstdoutに出力する"""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # 入力不正は無視して許可
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Task":
        # Task以外は対象外
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "")
    team_name = tool_input.get("team_name", "")
    prompt = tool_input.get("prompt", "")

    # --- issue_{id}トレーサビリティチェック ---
    issue_id_warn = None
    if not _has_issue_id(prompt):
        issue_id_warn = _make_issue_id_warn_output()

    # --- ticket-tasuki:* 直接起動ブロック ---
    if subagent_type.startswith(BLOCKED_PREFIX):
        if team_name and team_name.strip():
            _emit_and_exit(issue_id_warn)

        # deny判定はissue_id警告より優先
        reason = BLOCK_MESSAGE_TEMPLATE.format(subagent_type=subagent_type)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
        _emit_and_exit(output)

    # --- team_name指定あり → 許可 ---
    if team_name and team_name.strip():
        _emit_and_exit(issue_id_warn)

    # --- ビルトイン軽量エージェント → team_name不要で許可 ---
    if subagent_type in TEAM_EXEMPT_TYPES:
        _emit_and_exit(issue_id_warn)

    # --- team_name未指定 + 非ホワイトリスト → ブロック ---
    # deny判定はissue_id警告より優先
    reason = NO_TEAM_BLOCK_TEMPLATE.format(
        subagent_type=subagent_type or "(未指定)"
    )
    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    _emit_and_exit(output)


if __name__ == "__main__":
    main()
