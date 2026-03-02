"""caller role取得サービス（issue_7155）

ImplementationDesignHook._get_caller_roles()を独立関数として抽出。
SendMessageGuardHook等からも利用可能。
"""

import logging
from typing import Optional


def get_caller_roles(
    input_data: dict,
    tool_use_id: str = '',
    transcript_path: str = '',
    logger: Optional[logging.Logger] = None,
) -> set:
    """現在のcaller（subagent）のroleセットを取得

    tool_use_idベース: subagentsディレクトリからtool_use_idの発信元agentを特定し、
    そのagentのroleを返す。フォールバック: session_idベースの既存ロジック。

    Args:
        input_data: 入力データ（session_id等を含む）
        tool_use_id: ツール使用ID
        transcript_path: トランスクリプトファイルパス
        logger: ロガー（Noneの場合は__name__で取得）

    Returns:
        正規化済みroleのセット
    """
    if logger is None:
        logger = logging.getLogger(__name__)

    # tool_use_idベースのagent特定（優先）
    if tool_use_id and transcript_path:
        try:
            from domain.services.leader_detection import find_caller_agent_id
            agent_id = find_caller_agent_id(transcript_path, tool_use_id)
            if agent_id:
                from infrastructure.db import NaggerStateDB, SubagentRepository
                db = NaggerStateDB(NaggerStateDB.resolve_db_path())
                subagent_repo = SubagentRepository(db)
                record = subagent_repo.get(agent_id)
                db.close()
                if record and record.role:
                    from infrastructure.db.subagent_repository import _normalize_role, _get_known_roles_from_config
                    known_roles = _get_known_roles_from_config()
                    normalized = _normalize_role(record.role, known_roles)
                    logger.info(
                        f"CALLER ROLES (tool_use_id): agent_id={agent_id}, role={normalized}"
                    )
                    return {normalized}
            # agent_id未特定 or record/role無し → 空set（安全側フォールバック）
            return set()
        except Exception as e:
            logger.warning(f"Failed to get caller roles via tool_use_id: {e}")
            return set()

    # 後方互換: tool_use_id/transcript_pathが無い場合はsession_idベース
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
