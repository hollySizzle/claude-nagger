"""trusted_prefixesユニットテスト（issue_7446-7448）

resolve_trusted_prefix()の最長一致ロジック、
get_caller_roles()のtrusted_prefix優先、
_resolve_subagent_config()のrole上書きをテスト。
"""

import os
import tempfile
import pytest
import yaml

from shared.trusted_prefixes import resolve_trusted_prefix, _load_trusted_prefixes, clear_cache


@pytest.fixture(autouse=True)
def _clear_cache():
    """各テスト前後にキャッシュをクリア"""
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def config_dir(tmp_path):
    """trusted_prefixes付きconfig.yamlを持つ一時ディレクトリを作成"""
    nagger_dir = tmp_path / ".claude-nagger"
    nagger_dir.mkdir()
    config = {
        "role_resolution": {
            "trusted_prefixes": {
                "ticket-tasuki:coder": "coder",
                "ticket-tasuki:pmo": "pmo",
                "ticket-tasuki:tech-lead": "tech-lead",
                "ticket-tasuki:tester": "tester",
                "ticket-tasuki:researcher": "researcher",
            }
        }
    }
    config_file = nagger_dir / "config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)
    return tmp_path


@pytest.fixture
def empty_config_dir(tmp_path):
    """trusted_prefixes未定義のconfig.yamlを持つ一時ディレクトリ"""
    nagger_dir = tmp_path / ".claude-nagger"
    nagger_dir.mkdir()
    config = {"session_startup": {"enabled": True}}
    config_file = nagger_dir / "config.yaml"
    with open(config_file, 'w') as f:
        yaml.dump(config, f)
    return tmp_path


class TestResolveTrustedPrefix:
    """resolve_trusted_prefix()の最長一致ロジックテスト"""

    def test_完全一致(self, config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("ticket-tasuki:coder") == "coder"

    def test_前方一致(self, config_dir, monkeypatch):
        """agent_typeがprefixより長い場合も前方一致でマッチ"""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("ticket-tasuki:coder-extra") == "coder"

    def test_pmo解決(self, config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("ticket-tasuki:pmo") == "pmo"

    def test_tech_lead解決(self, config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("ticket-tasuki:tech-lead") == "tech-lead"

    def test_未マッチ_None返却(self, config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("unknown-plugin:coder") is None

    def test_trusted_prefixes未定義_None返却(self, empty_config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(empty_config_dir))
        assert resolve_trusted_prefix("ticket-tasuki:coder") is None

    def test_最長一致(self, tmp_path, monkeypatch):
        """複数のprefixがマッチする場合、最長のものが優先される"""
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        config = {
            "role_resolution": {
                "trusted_prefixes": {
                    "ticket": "generic",
                    "ticket-tasuki": "tasuki-generic",
                    "ticket-tasuki:coder": "coder",
                }
            }
        }
        with open(nagger_dir / "config.yaml", 'w') as f:
            yaml.dump(config, f)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        # "ticket-tasuki:coder"が最長一致で"coder"を返す
        assert resolve_trusted_prefix("ticket-tasuki:coder") == "coder"

    def test_最長一致_中間マッチ(self, tmp_path, monkeypatch):
        """最長一致で中間のprefixがマッチするケース"""
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        config = {
            "role_resolution": {
                "trusted_prefixes": {
                    "ticket": "generic",
                    "ticket-tasuki": "tasuki-generic",
                    "ticket-tasuki:coder": "coder",
                }
            }
        }
        with open(nagger_dir / "config.yaml", 'w') as f:
            yaml.dump(config, f)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        # "ticket-tasuki:unknown"は"ticket-tasuki"にマッチ
        assert resolve_trusted_prefix("ticket-tasuki:unknown") == "tasuki-generic"


class TestLoadTrustedPrefixes:
    """_load_trusted_prefixes()のキャッシュ動作テスト"""

    def test_キャッシュ有効(self, config_dir, monkeypatch):
        """2回目の呼び出しはキャッシュから返される"""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        result1 = _load_trusted_prefixes()
        result2 = _load_trusted_prefixes()
        assert result1 is result2  # 同一オブジェクト（キャッシュ）

    def test_config未存在_空dict(self, tmp_path, monkeypatch):
        """config.yamlが存在しない場合は空dictを返す"""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert _load_trusted_prefixes() == {}
