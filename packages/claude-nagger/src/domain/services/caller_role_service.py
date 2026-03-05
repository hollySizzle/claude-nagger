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
    agent_id不在時はsession_idベースのフォールバック。

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

    # フォールバック: agent_idが無い場合はsession_idベース
    session_id = input_data.get('session_id', '')
    if not session_id:
        return set()

    try:
        from infrastructure.db import NaggerStateDB, SubagentRepository
        db = NaggerStateDB(NaggerStateDB.resolve_db_path())
        subagent_repo = SubagentRepository(db)
        records = subagent_repo.get_active(session_id)
        db.close()

        # 処理済みsubagentのroleを収集（issue_7130: role正規化）
        from infrastructure.db.subagent_repository import _normalize_role, _get_known_roles_from_config
        known_roles = _get_known_roles_from_config()
        roles = set()
        for record in records:
            if record.role and record.startup_processed:
                roles.add(_normalize_role(record.role, known_roles))

        if roles:
            logger.info(f"CALLER ROLES: session={session_id}, roles={roles}")
        return roles
    except Exception as e:
        logger.warning(f"Failed to get caller roles: {e}")
        return set()
