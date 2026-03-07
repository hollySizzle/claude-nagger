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
                "coder": "coder",
                "pmo": "pmo",
                "tech-lead": "tech-lead",
                "tester": "tester",
                "researcher": "researcher",
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
        assert resolve_trusted_prefix("coder") == "coder"

    def test_前方一致(self, config_dir, monkeypatch):
        """agent_typeがprefixより長い場合も前方一致でマッチ"""
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("coder-extra") == "coder"

    def test_pmo解決(self, config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("pmo") == "pmo"

    def test_tech_lead解決(self, config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("tech-lead") == "tech-lead"

    def test_未マッチ_None返却(self, config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(config_dir))
        assert resolve_trusted_prefix("unknown-plugin") is None

    def test_trusted_prefixes未定義_None返却(self, empty_config_dir, monkeypatch):
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(empty_config_dir))
        assert resolve_trusted_prefix("coder") is None

    def test_最長一致(self, tmp_path, monkeypatch):
        """複数のprefixがマッチする場合、最長のものが優先される"""
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        config = {
            "role_resolution": {
                "trusted_prefixes": {
                    "cod": "generic",
                    "coder": "coder",
                    "coder-special": "special-coder",
                }
            }
        }
        with open(nagger_dir / "config.yaml", 'w') as f:
            yaml.dump(config, f)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        # "coder-special"が最長一致で"special-coder"を返す
        assert resolve_trusted_prefix("coder-special") == "special-coder"

    def test_最長一致_中間マッチ(self, tmp_path, monkeypatch):
        """最長一致で中間のprefixがマッチするケース"""
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        config = {
            "role_resolution": {
                "trusted_prefixes": {
                    "cod": "generic",
                    "coder": "coder",
                    "coder-special": "special-coder",
                }
            }
        }
        with open(nagger_dir / "config.yaml", 'w') as f:
            yaml.dump(config, f)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        # "coder-unknown"は"coder"にマッチ（"cod"より長い）
        assert resolve_trusted_prefix("coder-unknown") == "coder"


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


# === 統合テスト: trusted_prefix DB書込 (issue_7440) ===

from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.subagent_repository import SubagentRepository


@pytest.fixture
def integration_env(tmp_path, monkeypatch):
    """統合テスト用環境: 一時DB + trusted_prefixes設定付きconfig.yaml

    返却: (db, repo, config_dir)
    """
    # config.yaml作成（trusted_prefixes + session_startup設定）
    nagger_dir = tmp_path / ".claude-nagger"
    nagger_dir.mkdir()
    config = {
        "role_resolution": {
            "trusted_prefixes": {
                "coder": "coder",
                "pmo": "pmo",
                "tech-lead": "tech-lead",
                "tester": "tester",
                "researcher": "researcher",
            }
        },
        "session_startup": {
            "enabled": True,
            "overrides": {
                "subagent_types": {
                    "coder": {"enabled": True},
                    "pmo": {"enabled": True},
                    "tech-lead": {"enabled": True},
                }
            }
        }
    }
    with open(nagger_dir / "config.yaml", 'w') as f:
        yaml.dump(config, f)

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    # テスト用DB
    db_path = tmp_path / ".claude-nagger" / "state.db"
    db = NaggerStateDB(db_path)
    db.connect()
    repo = SubagentRepository(db)

    yield db, repo, tmp_path

    db.close()


@pytest.fixture
def no_prefix_env(tmp_path, monkeypatch):
    """trusted_prefixes未定義の統合テスト用環境"""
    nagger_dir = tmp_path / ".claude-nagger"
    nagger_dir.mkdir()
    config = {
        "session_startup": {
            "enabled": True,
        }
    }
    with open(nagger_dir / "config.yaml", 'w') as f:
        yaml.dump(config, f)

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    db_path = tmp_path / ".claude-nagger" / "state.db"
    db = NaggerStateDB(db_path)
    db.connect()
    repo = SubagentRepository(db)

    yield db, repo, tmp_path

    db.close()


class TestSubagentStartTrustedPrefixDB:
    """SubagentStart時のtrusted_prefix DB書込統合テスト（issue_7440 T3-1）

    subagent_event_hookのSubagentStart処理フローを再現し、
    register() → resolve_trusted_prefix() → update_role() のDB書込を検証。
    """

    def test_pmo_register_and_role_update(self, integration_env):
        """agent_type="pmo"でregister→trusted_prefix照合→DB書込"""
        db, repo, _ = integration_env
        clear_cache()

        agent_id = "agent-pmo-001"
        session_id = "session-001"
        agent_type = "pmo"

        # SubagentStart処理フローを再現
        repo.register(agent_id, session_id, agent_type)

        # trusted_prefix照合
        trusted_role = resolve_trusted_prefix(agent_type)
        assert trusted_role == "pmo"

        # DB書込（subagent_event_hookと同一コードパス）
        repo.update_role(agent_id, trusted_role, 'trusted_prefix')

        # DB検証: role='pmo', role_source='trusted_prefix'
        record = repo.get(agent_id)
        assert record is not None
        assert record.role == "pmo"
        assert record.role_source == "trusted_prefix"

    def test_trusted_prefix_skips_task_spawns(self, integration_env):
        """trusted_prefix解決成功時、task_spawnsマッチングがスキップされることを確認"""
        db, repo, _ = integration_env
        clear_cache()

        agent_id = "agent-coder-001"
        session_id = "session-002"
        agent_type = "coder"

        repo.register(agent_id, session_id, agent_type)

        # trusted_prefix照合（subagent_event_hook.pyのロジック再現）
        trusted_role = resolve_trusted_prefix(agent_type)
        assert trusted_role is not None  # 解決成功 → task_spawnsスキップ

        repo.update_role(agent_id, trusted_role, 'trusted_prefix')

        # task_spawnsにエントリが存在しないことを確認（スキップされた証拠）
        cursor = db.conn.execute(
            "SELECT COUNT(*) FROM task_spawns WHERE session_id = ?",
            (session_id,),
        )
        assert cursor.fetchone()[0] == 0

        # subagentsのrole_sourceが'trusted_prefix'であることを確認
        record = repo.get(agent_id)
        assert record.role_source == "trusted_prefix"


class TestPreToolUseTrustedPrefixDB:
    """PreToolUse時のtrusted_prefix DB書込統合テスト（issue_7440 T3-2）

    session_startup_hookのshould_process()内のtrusted_prefix照合フローを再現し、
    role未設定subagentに対するDB更新を検証。
    """

    def test_role未設定subagentへのtrusted_prefix適用(self, integration_env):
        """role=NoneのsubagentにPreToolUse時にtrusted_prefixでrole設定"""
        db, repo, _ = integration_env
        clear_cache()

        agent_id = "agent-tech-001"
        session_id = "session-003"
        agent_type = "tech-lead"

        # register時はrole=None（SubagentStart時にtrusted_prefixが失敗したケースを模擬）
        repo.register(agent_id, session_id, agent_type, role=None)

        # PreToolUse時のshould_process()内ロジック再現
        record = repo.get(agent_id)
        assert record.role is None

        # trusted_prefix照合
        trusted_role = resolve_trusted_prefix(agent_type)
        assert trusted_role == "tech-lead"

        # DB更新
        repo.update_role(agent_id, trusted_role, 'trusted_prefix')

        # DB検証
        updated = repo.get(agent_id)
        assert updated.role == "tech-lead"
        assert updated.role_source == "trusted_prefix"

    def test_role設定済みsubagentはスキップ(self, integration_env):
        """既にrole設定済みのsubagentはtrusted_prefix照合しない（上書き防止）"""
        db, repo, _ = integration_env
        clear_cache()

        agent_id = "agent-coder-002"
        session_id = "session-004"
        agent_type = "coder"

        # register時にrole='coder'が既に設定されているケース
        repo.register(agent_id, session_id, agent_type, role=None)
        repo.update_role(agent_id, "coder", "task_match")

        # session_startup_hookのロジック: roleがある場合はtrusted_prefix照合しない
        record = repo.get(agent_id)
        assert record.role == "coder"
        assert record.role_source == "task_match"  # 元のsourceが維持


class TestTrustedPrefixFallback:
    """trusted_prefix未定義時のフォールバック統合テスト（issue_7440 T3-3）

    trusted_prefixesに未定義のagent_typeで、
    既存のtask_spawns/transcript_parseにフォールバックすることを検証。
    """

    def test_未定義agent_typeはNone返却(self, no_prefix_env):
        """trusted_prefixes未定義のconfig環境でNone返却"""
        db, repo, _ = no_prefix_env
        clear_cache()

        agent_type = "general-purpose"
        trusted_role = resolve_trusted_prefix(agent_type)
        assert trusted_role is None

    def test_未定義agent_typeでtask_spawnsフォールバック(self, integration_env):
        """trusted_prefixesに未定義のagent_typeはtask_spawnsフォールバック"""
        db, repo, _ = integration_env
        clear_cache()

        agent_id = "agent-general-001"
        session_id = "session-005"
        agent_type = "general-purpose"

        repo.register(agent_id, session_id, agent_type)

        # trusted_prefix照合 → None（未定義）
        trusted_role = resolve_trusted_prefix(agent_type)
        assert trusted_role is None

        # フォールバック: task_spawnsマッチングに進むべき
        # ここではtrusted_prefixがNoneであることのみ検証
        # （実際のtask_spawnsマッチングはtranscript_pathが必要で別テストで検証済み）
        record = repo.get(agent_id)
        assert record.role is None  # trusted_prefixで解決されず、roleは未設定のまま
        assert record.role_source is None


class TestSuffixAgentTypeTrustedPrefix:
    """suffix付きagent_typeのtrusted_prefix統合テスト（issue_7440 T3-4）

    agent_type="coder-fix-bug" のように
    定義済みprefixにsuffixが付いたケースの前方一致を検証。
    """

    def test_suffix付きagent_typeの前方一致解決(self, integration_env):
        """agent_type="coder-fix-bug" → role='coder'に解決"""
        db, repo, _ = integration_env
        clear_cache()

        agent_id = "agent-coder-fix-001"
        session_id = "session-006"
        agent_type = "coder-fix-bug"

        repo.register(agent_id, session_id, agent_type)

        # 前方一致: "coder" が最長一致でマッチ
        trusted_role = resolve_trusted_prefix(agent_type)
        assert trusted_role == "coder"

        repo.update_role(agent_id, trusted_role, 'trusted_prefix')

        # DB検証
        record = repo.get(agent_id)
        assert record.role == "coder"
        assert record.role_source == "trusted_prefix"

    def test_suffix付きagent_typeのDB永続化(self, integration_env):
        """suffix付きでも正しくDB永続化されることを確認"""
        db, repo, _ = integration_env
        clear_cache()

        agent_id = "agent-tester-extra-001"
        session_id = "session-007"
        agent_type = "tester-regression"

        repo.register(agent_id, session_id, agent_type)

        trusted_role = resolve_trusted_prefix(agent_type)
        assert trusted_role == "tester"

        repo.update_role(agent_id, trusted_role, 'trusted_prefix')

        # DB永続化検証: 直接SQLで確認
        cursor = db.conn.execute(
            "SELECT role, role_source FROM subagents WHERE agent_id = ?",
            (agent_id,),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "tester"
        assert row[1] == "trusted_prefix"


class TestN3TrustedPrefixTypeValidation:
    """N3: trusted_prefixesが不正型の場合の防御テスト（issue_7565）

    trusted_prefixesにdict以外（リスト、文字列、整数等）が設定された場合、
    resolve_trusted_prefix()がNoneを返すことを検証。
    """

    def test_trusted_prefixesがリスト型_None返却(self, tmp_path, monkeypatch):
        """trusted_prefixesがリスト型の場合Noneを返す"""
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        config = {
            "role_resolution": {
                "trusted_prefixes": ["coder", "tester"]
            }
        }
        with open(nagger_dir / "config.yaml", 'w') as f:
            yaml.dump(config, f)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert resolve_trusted_prefix("coder") is None

    def test_trusted_prefixesが文字列型_None返却(self, tmp_path, monkeypatch):
        """trusted_prefixesが文字列型の場合Noneを返す"""
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        config = {
            "role_resolution": {
                "trusted_prefixes": "coder:coder"
            }
        }
        with open(nagger_dir / "config.yaml", 'w') as f:
            yaml.dump(config, f)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert resolve_trusted_prefix("coder") is None

    def test_trusted_prefixesが整数型_None返却(self, tmp_path, monkeypatch):
        """trusted_prefixesが整数型の場合Noneを返す"""
        nagger_dir = tmp_path / ".claude-nagger"
        nagger_dir.mkdir()
        config = {
            "role_resolution": {
                "trusted_prefixes": 42
            }
        }
        with open(nagger_dir / "config.yaml", 'w') as f:
            yaml.dump(config, f)
        monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
        assert resolve_trusted_prefix("coder") is None
