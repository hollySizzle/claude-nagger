"""leader判定ユーティリティ（agent_idベース）

issue_7352/7353: transcript走査を全廃し、input_data['agent_id']ベースに移行。
"""

import logging
from typing import Optional

_logger = logging.getLogger(__name__)


def is_leader_tool_use(input_data: dict) -> bool:
    """agent_idベースのleader判定（issue_7352, issue_7353）

    input_data['agent_id']の有無でleader/subagentを判定。
    agent_idが存在すればsubagent（False）、不在ならleader（True）。

    Args:
        input_data: PreToolUseペイロード辞書

    Returns:
        True: leader（agent_idフィールド不在）
        False: subagent（agent_idフィールド存在）

    フォールバック方針:
        - input_dataがdictでない場合 → False（安全側=subagent扱い）
    """
    if not isinstance(input_data, dict):
        _logger.warning("is_leader_tool_use: input_dataがdictでない → subagent扱い")
        return False

    agent_id = input_data.get('agent_id')
    if agent_id:
        _logger.info(f"is_leader_tool_use: agent_id={agent_id} → subagent（非leader）")
        return False

    _logger.info("is_leader_tool_use: agent_id不在 → leader")
    return True


def find_caller_agent_id(input_data: dict) -> Optional[str]:
    """input_dataからagent_idを取得（issue_7353）

    Args:
        input_data: PreToolUseペイロード辞書

    Returns:
        agent_id文字列、不在時はNone
    """
    if not isinstance(input_data, dict):
        return None
    return input_data.get('agent_id')
