"""ConventionLogRepositoryのテスト（issue_7055）

- convention_logテーブルへのINSERT確認
- 全カラムが正しく保存されること
- オプションカラムがNULLで保存できること
"""

import pytest

from infrastructure.db.convention_log_repository import ConventionLogRepository


class TestInsertLog:
    """insert_log()の動作確認"""

    def test_全カラム指定でINSERT(self, db):
        """全パラメータ指定時に正しくINSERTされる"""
        repo = ConventionLogRepository(db)
        repo.insert_log(
            session_id="sess-001",
            tool_name="Bash",
            convention_type="command",
            rule_name="deny_rm_rf",
            severity="deny",
            decision="blocked",
            reason="rm -rf は禁止",
            scope="coder",
            caller_role="coder",
        )

        cursor = db.conn.execute("SELECT * FROM convention_log WHERE id = 1")
        row = cursor.fetchone()
        assert row is not None
        # id=1, session_id, timestamp, tool_name, convention_type,
        # rule_name, severity, decision, reason, scope, caller_role
        assert row[1] == "sess-001"       # session_id
        assert row[3] == "Bash"           # tool_name
        assert row[4] == "command"        # convention_type
        assert row[5] == "deny_rm_rf"     # rule_name
        assert row[6] == "deny"           # severity
        assert row[7] == "blocked"        # decision
        assert row[8] == "rm -rf は禁止"  # reason
        assert row[9] == "coder"          # scope
        assert row[10] == "coder"         # caller_role

    def test_オプションカラムNULLでINSERT(self, db):
        """reason/scope/caller_role省略時にNULLで保存される"""
        repo = ConventionLogRepository(db)
        repo.insert_log(
            session_id="sess-002",
            tool_name="Write",
            convention_type="file",
            rule_name="block_env_file",
            severity="block",
            decision="blocked",
        )

        cursor = db.conn.execute("SELECT * FROM convention_log WHERE id = 1")
        row = cursor.fetchone()
        assert row is not None
        assert row[8] is None   # reason
        assert row[9] is None   # scope
        assert row[10] is None  # caller_role

    def test_session_id_NULLでINSERT(self, db):
        """session_idがNoneでも保存可能"""
        repo = ConventionLogRepository(db)
        repo.insert_log(
            session_id=None,
            tool_name="mcp__some_tool",
            convention_type="mcp",
            rule_name="warn_mcp_access",
            severity="warn",
            decision="warned",
        )

        cursor = db.conn.execute("SELECT * FROM convention_log WHERE id = 1")
        row = cursor.fetchone()
        assert row is not None
        assert row[1] is None  # session_id

    def test_timestampが自動設定される(self, db):
        """timestamp DEFAULT (datetime('now'))が機能する"""
        repo = ConventionLogRepository(db)
        repo.insert_log(
            session_id="sess-003",
            tool_name="Bash",
            convention_type="command",
            rule_name="warn_sudo",
            severity="warn",
            decision="warned",
        )

        cursor = db.conn.execute("SELECT timestamp FROM convention_log WHERE id = 1")
        row = cursor.fetchone()
        assert row is not None
        assert row[0] is not None  # timestampが自動設定されている

    def test_複数レコードINSERT(self, db):
        """複数回insert_log()でAUTOINCREMENTが機能する"""
        repo = ConventionLogRepository(db)
        for i in range(3):
            repo.insert_log(
                session_id=f"sess-{i}",
                tool_name="Bash",
                convention_type="command",
                rule_name=f"rule_{i}",
                severity="warn",
                decision="warned",
            )

        cursor = db.conn.execute("SELECT COUNT(*) FROM convention_log")
        assert cursor.fetchone()[0] == 3


class TestConventionLogTable:
    """convention_logテーブルの構造確認"""

    def test_テーブル存在確認(self, db):
        """convention_logテーブルが存在する"""
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='convention_log'"
        )
        assert cursor.fetchone() is not None

    def test_インデックス存在確認(self, db):
        """convention_logのインデックスが存在する"""
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_convention_log_%'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_convention_log_session" in indexes
        assert "idx_convention_log_severity" in indexes
