#!/usr/bin/env python3
"""ticket-tasuki Agent spawn ガード (プラグインhook)

PreToolUse hook:
- leaderによるAgent toolでのsub-agent直接起動をブロックし、TeamCreate経由を強制する。
- ビルトイン軽量エージェント（Explore, Plan等）は許可。
- subagent（agent_context="subagent"）からの呼び出しは制約対象外。
- team_name指定ありのAgent呼び出し（team agent経由）は許可。

Claude Code プラグインhook機構で ${CLAUDE_PLUGIN_ROOT}/hooks/agent_spawn_guard.py として呼び出される。
"""

import json
import os
import re
import sys

import yaml

# team_name不要で許可するsubagent_type（ビルトイン軽量エージェント）
BUILTIN_WHITELIST = {
    "Explore", "Plan",
    "statusline-setup", "claude-code-guide",
}

# デフォルト正規表現パターン（config.yaml読み込み失敗時のフォールバック）
_DEFAULT_ISSUE_ID_PATTERN = r"issue_\d+"
_DEFAULT_PROMPT_ONLY_PATTERN = r"^issue_\d{1,6}$"

# デフォルトメッセージ（config.yaml読み込み失敗時のフォールバック）
_DEFAULT_ISSUE_ID_WARN_MESSAGE = """\
⚠ Agent promptにissue_{id}が含まれていません。
トレーサビリティのため、promptにissue_{id}（例: issue_1234）を含めてください。"""

_DEFAULT_OVERRIDE_INSTRUCTION = (
    "Redmine get_issue_detail_toolでチケットコメントから最新の指示を取得し、指示に従って作業を実行せよ"
)

_DEFAULT_PROMPT_PATTERN_BLOCK_MESSAGE = """\
Agent tool規約: promptパターン制限
━━━━━━━━━━━━━━━━━
検出prompt: "{prompt}"
要件: promptは "issue_{{数字1-6桁}}" の形式（例: issue_1234）でなければなりません。
対処: promptを issue_{{id}} 形式に変更してください。"""

_DEFAULT_BLOCK_MESSAGE_TEMPLATE = """\
Agent tool規約: sub-agent直接起動の制限
━━━━━━━━━━━━━━━━━
検出: subagent_type="{subagent_type}"
対処:
1. TeamCreate でチームを作成し、Agent tool に team_name を指定して起動してください
2. sub-agent（Agent tool単独）でのticket-tasukiロール起動は禁止です
3. 軽量エージェント（Explore, Plan）はsub-agentで利用可能です"""


def _load_guard_config() -> dict:
    """config.yamlからagent_spawn_guardセクションを読み込む。
    読み込み失敗時は空dictを返す。
    """
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, "..", ".claude-nagger", "config.yaml")
        config_path = os.path.normpath(config_path)
        if not os.path.isfile(config_path):
            return {}
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if not isinstance(config, dict):
            return {}
        return config.get("agent_spawn_guard", {}) or {}
    except Exception:
        return {}


# config.yamlから設定読み込み（フォールバック付き）
_guard_config = _load_guard_config()


def _safe_compile(pattern: str | None, default: str) -> re.Pattern:
    """正規表現を安全にコンパイルする。不正パターン時はデフォルトにフォールバック。"""
    raw = pattern or default
    try:
        return re.compile(raw)
    except (re.error, TypeError):
        return re.compile(default)


# 正規表現パターン（config.yamlからフォールバック付きで読み込み）
ISSUE_ID_PATTERN = _safe_compile(
    _guard_config.get("issue_id_pattern"), _DEFAULT_ISSUE_ID_PATTERN
)
PROMPT_ONLY_PATTERN = _safe_compile(
    _guard_config.get("prompt_only_pattern"), _DEFAULT_PROMPT_ONLY_PATTERN
)

ISSUE_ID_WARN_MESSAGE = (
    _guard_config.get("issue_id_warn_message") or _DEFAULT_ISSUE_ID_WARN_MESSAGE
).rstrip()

PROMPT_PATTERN_BLOCK_MESSAGE = (
    _guard_config.get("prompt_pattern_block_message") or _DEFAULT_PROMPT_PATTERN_BLOCK_MESSAGE
).rstrip()

BLOCK_MESSAGE_TEMPLATE = (
    _guard_config.get("block_message_template") or _DEFAULT_BLOCK_MESSAGE_TEMPLATE
).rstrip()


def _load_override_instruction() -> str:
    """config.yamlからoverride_instructionを取得。フォールバック付き。"""
    return (
        _guard_config.get("override_instruction") or _DEFAULT_OVERRIDE_INSTRUCTION
    )


def _make_override_output(original_prompt: str, override_instruction: str) -> dict:
    """promptにoverride指示を付加したupdatedInput出力を生成"""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {
                "prompt": f"{original_prompt}\n\n{override_instruction}",
            },
        }
    }


def _has_issue_id(prompt: str) -> bool:
    """promptにissue_{id}パターンが含まれるか判定"""
    if not prompt:
        return False
    return bool(ISSUE_ID_PATTERN.search(prompt))


def _is_exempt_spawn_route(agent_context: str, subagent_type: str, guard_config: dict) -> bool:
    """exempt_routesに該当するcaller→subagent_type経路かを判定

    config.yaml の agent_spawn_guard.exempt_routes に定義された経路の場合、
    issue_id・promptパターンチェックをスキップする。

    Args:
        agent_context: 呼び出し元のコンテキスト（例: "leader"）
        subagent_type: 起動対象のsubagentタイプ（例: "pmo"）
        guard_config: agent_spawn_guard設定辞書

    Returns:
        免除対象経路の場合 True
    """
    exempt_routes = guard_config.get("exempt_routes", [])
    if not exempt_routes:
        return False
    # leaderはagent_context=""で識別される → "leader"に変換
    caller = "leader" if not agent_context else agent_context
    # 名前空間prefix除去（"ticket-tasuki:pmo" → "pmo"）
    normalized_type = subagent_type.split(":")[-1] if ":" in subagent_type else subagent_type
    for route in exempt_routes:
        if route.get("from") == caller and route.get("to") == normalized_type:
            return True
    return False


def _make_issue_id_warn_output() -> dict:
    """issue_{id}欠落時の警告出力を生成（ユーザー確認要求）"""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": ISSUE_ID_WARN_MESSAGE,
        }
    }


def _emit_and_exit(output: dict | None) -> None:
    """判定結果を出力して終了する。Noneなら出力なし（許可）"""
    if output is not None:
        print(json.dumps(output, ensure_ascii=False))
    sys.exit(0)


def main():
    """stdinからPreToolUse入力JSONを読み、判定結果をstdoutに出力する"""
    try:
        input_data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        # 入力不正は無視して許可
        sys.exit(0)

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Agent":
        # Agent以外は対象外
        sys.exit(0)

    # agent_contextフィルタ: subagentは制約対象外
    agent_context = input_data.get("agent_context", "")
    if agent_context == "subagent":
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "")
    team_name = tool_input.get("team_name", "")
    prompt = tool_input.get("prompt", "")

    # exempt_routesに該当する経路かを判定（issue_id・promptパターン両方スキップ）
    is_exempt = _is_exempt_spawn_route(agent_context, subagent_type, _guard_config)

    # --- issue_{id}トレーサビリティチェック ---
    # exempt_routesに該当する経路はissue_idチェックをスキップ
    issue_id_warn = None
    if not _has_issue_id(prompt) and not is_exempt:
        issue_id_warn = _make_issue_id_warn_output()

    # team_name指定あり → promptパターンチェック後に許可（override注入付き）
    if team_name and team_name.strip():
        # ビルトインsubagent_typeはprompt自由文を許可
        if subagent_type not in BUILTIN_WHITELIST:
            # exempt_routesに該当する場合はpromptパターンチェックをスキップ
            if is_exempt:
                _emit_and_exit(None)
            elif PROMPT_ONLY_PATTERN.match(prompt or ""):
                # promptパターン合致 → override指示を注入してallow
                override_instruction = _load_override_instruction()
                override_output = _make_override_output(prompt, override_instruction)
                _emit_and_exit(override_output)
            else:
                reason = PROMPT_PATTERN_BLOCK_MESSAGE.format(prompt=prompt or "(空)")
                output = {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": reason,
                    }
                }
                _emit_and_exit(output)
        _emit_and_exit(issue_id_warn)

    # ビルトインホワイトリスト → 許可
    if subagent_type in BUILTIN_WHITELIST:
        _emit_and_exit(issue_id_warn)

    # それ以外 → deny
    reason = BLOCK_MESSAGE_TEMPLATE.format(subagent_type=subagent_type or "(未指定)")
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
