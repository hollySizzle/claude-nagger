"""caller role取得サービス（issue_7155, issue_7352）

ImplementationDesignHook._get_caller_roles()を独立関数として抽出。
SendMessageGuardHook等からも利用可能。
issue_7352: agent_idベースに移行。transcript走査を全廃。
"""

import logging
from typing import Optional

from shared.trusted_prefixes import resolve_trusted_prefix


def get_caller_roles(
    input_data: dict,
    logger: Optional[logging.Logger] = None,
) -> set:
    """現在のcaller（subagent）のroleセットを取得

    agent_idベース: input_data['agent_id']からDB検索し、roleを返す。
    agent_id不在時はleader判定（is_leader_tool_use()と一貫）。

    Args:
        input_data: 入力データ（agent_id, session_id等を含む）
        logger: ロガー（Noneの場合は__name__で取得）

    Returns:
        正規化済みroleのセット
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # agent_idベースのagent特定（優先: issue_7352）
    from domain.services.leader_detection import find_caller_agent_id
    agent_id = find_caller_agent_id(input_data)
    if agent_id:
        try:
            from infrastructure.db import NaggerStateDB, SubagentRepository
            db = NaggerStateDB(NaggerStateDB.resolve_db_path())
            subagent_repo = SubagentRepository(db)
            record = subagent_repo.get(agent_id)
            db.close()
            # trusted_prefixes照合: agent_typeから直接roleを確定（race condition回避）
            if record and record.agent_type:
                trusted_role = resolve_trusted_prefix(record.agent_type, logger)
                if trusted_role:
                    logger.info(
                        f"CALLER ROLES (trusted_prefix): agent_id={agent_id}, "
                        f"agent_type={record.agent_type}, role={trusted_role}"
                    )
                    return {trusted_role}
            if record and record.role:
                from infrastructure.db.subagent_repository import _normalize_role, _get_known_roles_from_config
                known_roles = _get_known_roles_from_config()
                normalized = _normalize_role(record.role, known_roles)
                logger.info(
                    f"CALLER ROLES (agent_id): agent_id={agent_id}, role={normalized}"
                )
                return {normalized}
            # record/role無し → 空set（安全側フォールバック）
            return set()
        except Exception as e:
            logger.warning(f"Failed to get caller roles via agent_id: {e}")
            return set()

    # agent_id不在 = leader（is_leader_tool_use()と一貫した判定: issue_8118）
    logger.info("CALLER ROLES: agent_id不在 → leader")
    return {"leader"}
