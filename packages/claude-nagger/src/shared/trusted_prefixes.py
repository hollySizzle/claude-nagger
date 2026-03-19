"""trusted_prefixes共通ユーティリティ（issue_7446-7448）

config.yamlのrole_resolution.trusted_prefixesを読み込み、
agent_typeの前方一致（最長一致）でroleを確定する。
"""

import logging
import os
from pathlib import Path
from typing import Optional

import yaml

# デフォルトtrusted_prefixes（config.yaml未設定時のフェイルセーフ）
DEFAULT_TRUSTED_PREFIXES = {
    "coder": "coder",
    "pmo": "pmo",
    "team-lead": "leader",
    "tech-lead": "tech-lead",
    "tester": "tester",
    "researcher": "researcher",
    "auditor": "auditor",
}

# モジュールレベルキャッシュ（プロセス内で1回のみファイルI/O）
_trusted_prefixes_cache: Optional[dict] = None


def _load_trusted_prefixes(logger: Optional[logging.Logger] = None) -> dict:
    """config.yamlからrole_resolution.trusted_prefixesを読み込む（キャッシュ付き）

    config.yaml未設定時はDEFAULT_TRUSTED_PREFIXESをフェイルセーフとして使用。
    """
    global _trusted_prefixes_cache
    if _trusted_prefixes_cache is not None:
        return _trusted_prefixes_cache

    if logger is None:
        logger = logging.getLogger(__name__)

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    base_path = Path(project_dir) if project_dir else Path.cwd()
    config_file = base_path / ".claude-nagger" / "config.yaml"
    try:
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            loaded = (data or {}).get(
                'role_resolution', {}
            ).get('trusted_prefixes', {})
            if loaded:
                _trusted_prefixes_cache = loaded
                return _trusted_prefixes_cache
            # config.yamlにrole_resolutionが未定義 → デフォルトで補完
            logger.warning("role_resolution.trusted_prefixes未定義 — デフォルト値を使用")
    except Exception as e:
        logger.warning(f"Failed to load trusted_prefixes: {e}")
    _trusted_prefixes_cache = dict(DEFAULT_TRUSTED_PREFIXES)
    return _trusted_prefixes_cache


def resolve_trusted_prefix(agent_type: str, logger: Optional[logging.Logger] = None) -> Optional[str]:
    """agent_typeをtrusted_prefixesで前方一致照合し、確定roleを返す（最長一致）

    Args:
        agent_type: エージェントタイプ文字列
        logger: ロガー

    Returns:
        マッチしたrole文字列、またはNone（未マッチ/未定義時）
    """
    prefixes = _load_trusted_prefixes(logger)
    if not prefixes:
        return None
    # N3: trusted_prefixesがdict以外の場合は型不正として警告しNone返却
    if not isinstance(prefixes, dict):
        if logger is None:
            logger = logging.getLogger(__name__)
        logger.warning(f"trusted_prefixes型不正（期待: dict, 実際: {type(prefixes).__name__}）")
        return None
    # 最長一致: キーを長い順にソートし最初にマッチしたものを採用
    for prefix in sorted(prefixes.keys(), key=len, reverse=True):
        if agent_type.startswith(prefix):
            return prefixes[prefix]
    return None


def clear_cache():
    """テスト用: キャッシュをクリアする"""
    global _trusted_prefixes_cache
    _trusted_prefixes_cache = None
