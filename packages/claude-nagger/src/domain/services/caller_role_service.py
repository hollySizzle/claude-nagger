"""caller role取得サービス（issue_7155, issue_7352）

ImplementationDesignHook._get_caller_roles()を独立関数として抽出。
SendMessageGuardHook等からも利用可能。
issue_7352: agent_idベースに移行。transcript走査を全廃。
"""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml


def _load_trusted_prefixes(logger: logging.Logger) -> dict:
    """config.yamlからrole_resolution.trusted_prefixesを読み込む"""
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    base_path = Path(project_dir) if project_dir else Path.cwd()
    config_file = base_path / ".claude-nagger" / "config.yaml"
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            return (data or {}).get('role_resolution', {}).get('trusted_prefixes', {})
    except Exception as e:
        logger.warning(f"Failed to load trusted_prefixes: {e}")
    return {}


def _resolve_trusted_prefix(agent_type: str, logger: logging.Logger) -> Optional[str]:
    """agent_typeをtrusted_prefixesで前方一致照合し、確定roleを返す（最長一致）"""
    prefixes = _load_trusted_prefixes(logger)
    if not prefixes:
        return None
    # 最長一致: キーを長い順にソートし最初にマッチしたものを採用
    for prefix in sorted(prefixes.keys(), key=len, reverse=True):
        if agent_type.startswith(prefix):
            return prefixes[prefix]
    return None


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
                trusted_role = _resolve_trusted_prefix(record.agent_type, logger)
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
