"""_normalize_role() 単体テスト（issue_7131）

対象:
- src/domain/hooks/session_startup_hook.py::_normalize_role()
- src/infrastructure/db/subagent_repository.py::_normalize_role()
両実装が同一結果を返すことを検証。
"""

import pytest
from unittest.mock import patch, MagicMock

from domain.hooks.session_startup_hook import _normalize_role as normalize_hook
from infrastructure.db.subagent_repository import (
    _normalize_role as normalize_repo,
    _get_known_roles_from_config,
)

# config.yamlのsubagent_typesキーに対応する既知ロール
KNOWN_ROLES = {"coder", "tester", "tech-lead", "researcher", "Explore", "Plan", "Bash"}


class TestNormalizeRoleBothImplementations:
    """両実装（session_startup_hook版 / subagent_repository版）が同一結果を返すことを検証"""

    @pytest.mark.parametrize("input_role,expected", [
        # A. 完全一致（回帰なし）
        ("coder", "coder"),
        ("tester", "tester"),
        ("tech-lead", "tech-lead"),
        ("researcher", "researcher"),
        ("Explore", "Explore"),
        # B. suffix除去（数字サフィックス）
        ("coder-7097", "coder"),
        ("tester-2", "tester"),
        ("researcher-123", "researcher"),
        # C. suffix除去（非数字サフィックス）
        ("researcher-db", "researcher"),
        ("coder-t2", "coder"),
        # D. tech-lead安全性（最長一致）
        ("tech-lead", "tech-lead"),
        ("tech-lead-123", "tech-lead"),
        # E. prefix除去
        ("claude-coder", "coder"),
        ("claude-researcher", "researcher"),
        ("my-tester", "tester"),
    ])
    def test_両実装が同一結果(self, input_role, expected):
        """hook版とrepo版が同じ結果を返す"""
        result_hook = normalize_hook(input_role, KNOWN_ROLES)
        result_repo = normalize_repo(input_role, KNOWN_ROLES)
        assert result_hook == expected, f"hook版: {input_role} -> {result_hook}, expected {expected}"
        assert result_repo == expected, f"repo版: {input_role} -> {result_repo}, expected {expected}"


class TestNormalizeRoleExactMatch:
    """A. 完全一致"""

    @pytest.mark.parametrize("role", ["coder", "tester", "tech-lead", "researcher", "Explore"])
    def test_完全一致はそのまま返却(self, role):
        assert normalize_hook(role, KNOWN_ROLES) == role


class TestNormalizeRoleSuffixRemoval:
    """B/C. suffix除去（数字・非数字）"""

    @pytest.mark.parametrize("input_role,expected", [
        ("coder-7097", "coder"),
        ("tester-2", "tester"),
        ("researcher-123", "researcher"),
        ("researcher-db", "researcher"),
        ("coder-t2", "coder"),
    ])
    def test_suffix除去で既知ロールに正規化(self, input_role, expected):
        assert normalize_hook(input_role, KNOWN_ROLES) == expected


class TestNormalizeRoleTechLeadSafety:
    """D. tech-lead安全性（最長一致で破壊しない）"""

    def test_tech_leadはそのまま(self):
        assert normalize_hook("tech-lead", KNOWN_ROLES) == "tech-lead"

    def test_tech_lead_数字suffixは除去(self):
        """tech-lead-123 → tech-lead（techにならない）"""
        assert normalize_hook("tech-lead-123", KNOWN_ROLES) == "tech-lead"


class TestNormalizeRolePrefixRemoval:
    """E. prefix除去"""

    @pytest.mark.parametrize("input_role,expected", [
        ("claude-coder", "coder"),
        ("claude-researcher", "researcher"),
        ("my-tester", "tester"),
    ])
    def test_prefix除去で既知ロールに正規化(self, input_role, expected):
        assert normalize_hook(input_role, KNOWN_ROLES) == expected


class TestNormalizeRoleNamespaced:
    """F. namespaced（コロン区切り）"""

    def test_コロン区切りは正規化されない(self):
        """現在の実装はハイフン区切りのみ対応。コロンはフォールバック"""
        result = normalize_hook("my-plugin:coder", KNOWN_ROLES)
        # コロン区切りはknown_rolesにマッチしないためフォールバック
        assert result == "my-plugin:coder"  # 数字サフィックスなし→そのまま


class TestNormalizeRoleFallback:
    """G. フォールバック"""

    def test_未知ロール_数字なし_そのまま(self):
        """config未登録・数字サフィックスなし → そのまま返却"""
        assert normalize_hook("unknown-role", KNOWN_ROLES) == "unknown-role"

    def test_未知ロール_数字suffix_除去(self):
        """config未登録・数字サフィックス → strip"""
        assert normalize_hook("unknown-123", KNOWN_ROLES) == "unknown"


class TestNormalizeRoleEdgeCases:
    """H. エッジケース"""

    def test_空文字列(self):
        assert normalize_hook("", KNOWN_ROLES) == ""

    def test_None(self):
        assert normalize_hook(None, KNOWN_ROLES) is None

    def test_非文字列_数値(self):
        assert normalize_hook(123, KNOWN_ROLES) == 123

    def test_非文字列_リスト(self):
        assert normalize_hook(["coder"], KNOWN_ROLES) == ["coder"]


class TestGetKnownRolesFromConfig:
    """I. _get_known_roles_from_config()"""

    def test_config存在時にキー一覧取得(self, tmp_path):
        """config.yaml存在時にsubagent_typesキーのset返却"""
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text(
            "session_startup:\n"
            "  overrides:\n"
            "    subagent_types:\n"
            "      coder:\n"
            "        enabled: true\n"
            "      tester:\n"
            "        enabled: true\n"
            "      tech-lead:\n"
            "        enabled: true\n"
        )
        with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            result = _get_known_roles_from_config()
        assert result == {"coder", "tester", "tech-lead"}

    def test_config不在時に空set返却(self, tmp_path):
        """config.yamlが存在しない場合は空set"""
        with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            result = _get_known_roles_from_config()
        assert result == set()

    def test_configにsubagent_typesなし(self, tmp_path):
        """session_startupはあるがsubagent_typesがない場合"""
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()
        config_file = config_dir / "config.yaml"
        config_file.write_text("session_startup:\n  enabled: true\n")
        with patch.dict("os.environ", {"CLAUDE_PROJECT_DIR": str(tmp_path)}):
            result = _get_known_roles_from_config()
        assert result == set()
