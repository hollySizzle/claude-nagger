"""coygeek方式leader検出PoC（issue_7327, issue_7314）

GitHub #6885提案のTask/Agent tool_use逆順走査によるleader/subagent判定。
現行is_leader_tool_use()はPreToolUseタイミング問題で常にFalse返却するが、
coygeek方式はTask/Agent tool_useがsubagent起動前にtranscriptに書込済みのため
タイミング問題を回避可能。

ロジック:
- transcriptを逆順走査し、最新のTask/Agent tool_use（name in {'Task','Agent'}）を探す
- Task/Agent tool_useが存在 → subagentが起動済み → 非leader（False）
- Task/Agent tool_useが不在 → leader単独 → leader（True）
"""

import json
import logging
from pathlib import Path

_logger = logging.getLogger(__name__)


def is_leader_coygeek(transcript_path: str) -> bool:
    """coygeek方式: Task/Agent tool_use有無でleader判定（PoC, issue_7314）

    transcriptを逆順走査し、Task/Agent tool_useの存在を確認。
    Task/Agent tool_useが1つでも存在すればsubagentが起動済み → False（非leader）。
    Task/Agent tool_useが不在 → leader単独 → True。

    Args:
        transcript_path: main transcript（.jsonl）のパス

    Returns:
        True: leader（Task/Agent tool_useなし）
        False: 非leader（Task/Agent tool_useあり）

    フォールバック方針:
        - transcript未存在/読み込みエラー → False（安全側=subagent扱い）
          理由: ファイル不在は異常状態のため、leaderと誤判定するリスクを回避
        - 空transcript → True（leader）
          理由: セッション開始直後でツール未使用=leader単独作業の正常状態

    制約:
        - tool_use_idを使わないため、呼び出し元の特定は不可
        - leader自身もTask/Agent tool_useを発行するため、leaderのPreToolUseでもFalse返却
        - 複数subagent環境でどのsubagentかは識別不可
    """
    path = Path(transcript_path)
    if not path.exists():
        _logger.warning(f"is_leader_coygeek: transcript未発見: {transcript_path}")
        return False  # フォールバック: subagent扱い（異常状態のためleader誤判定を回避）

    # 全行読み込み後に逆順走査（逆順で最初に見つかったTask tool_useが最新）
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, IOError) as e:
        _logger.warning(f"is_leader_coygeek: ファイル読み込みエラー: {e}")
        return False

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "assistant":
            continue
        message = entry.get("message", {})
        for content_item in message.get("content", []):
            if content_item.get("type") != "tool_use":
                continue
            if content_item.get("name") in {"Task", "Agent"}:
                _logger.info(
                    f"is_leader_coygeek: {content_item.get('name')} tool_use発見 "
                    f"id={content_item.get('id')} → 非leader"
                )
                return False

    _logger.info("is_leader_coygeek: Task/Agent tool_use不在 → leader")
    return True
