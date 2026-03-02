"""convention_log記録の統合テスト（issue_7057）

- deny/block/warn各パターンでDB記録確認（file/command/mcp）
- approve時の非記録確認
- ログ記録失敗時のフック動作確認
- schema v9マイグレーションテスト
"""

import pytest
from unittest.mock import patch, MagicMock

from src.domain.hooks.implementation_design_hook import ImplementationDesignHook
from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.convention_log_repository import ConventionLogRepository


@pytest.fixture
def hook_with_db(db):
    """DB付きImplementationDesignHookフィクスチャ"""
    hook = ImplementationDesignHook()
    repo = ConventionLogRepository(db)
    hook._convention_log_repo = repo
    return hook, db


def _get_log_records(db):
    """convention_logテーブルの全レコードを取得"""
    cursor = db.conn.execute(
        "SELECT session_id, tool_name, convention_type, rule_name, "
        "severity, decision, reason, scope, caller_role "
        "FROM convention_log ORDER BY id"
    )
    return cursor.fetchall()


class TestFileDenyRecord:
    """ファイル規約deny判定 → DB記録"""

    def test_deny判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-secret-file',
                'severity': 'deny',
                'message': '秘密ファイル編集禁止',
                'token_threshold': None,
                'scope': None,
            }]
            hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/secret/file.md'},
                'session_id': 'sess-deny-file',
            })

        records = _get_log_records(db)
        assert len(records) == 1
        r = records[0]
        assert r[0] == 'sess-deny-file'     # session_id
        assert r[1] == 'Edit'               # tool_name
        assert r[2] == 'file'               # convention_type
        assert r[3] == 'deny-secret-file'   # rule_name
        assert r[4] == 'deny'               # severity
        assert r[5] == 'blocked'            # decision
        assert '秘密ファイル編集禁止' in r[6]  # reason
        assert r[7] is None                 # scope


class TestFileBlockRecord:
    """ファイル規約block判定 → DB記録"""

    def test_block判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'block-config',
                'severity': 'block',
                'message': '設定ファイル編集注意',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                hook.process({
                    'tool_name': 'Write',
                    'tool_input': {'file_path': '/config/app.yml'},
                    'session_id': 'sess-block-file',
                })

        records = _get_log_records(db)
        assert len(records) == 1
        r = records[0]
        assert r[2] == 'file'
        assert r[3] == 'block-config'
        assert r[4] == 'block'
        assert r[5] == 'blocked'


class TestFileWarnRecord:
    """ファイル規約warn判定 → DB記録"""

    def test_warn判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'warn-docs',
                'severity': 'warn',
                'message': 'ドキュメント編集確認',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/docs/guide.md'},
                    'session_id': 'sess-warn-file',
                })

        records = _get_log_records(db)
        assert len(records) == 1
        assert records[0][4] == 'warn'


class TestCommandDenyRecord:
    """コマンド規約deny判定 → DB記録"""

    def test_deny判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-rm-rf',
                'severity': 'deny',
                'message': 'rm -rf禁止',
                'token_threshold': None,
                'scope': None,
            }]
            hook.process({
                'tool_name': 'Bash',
                'tool_input': {'command': 'rm -rf /'},
                'session_id': 'sess-deny-cmd',
            })

        records = _get_log_records(db)
        assert len(records) == 1
        r = records[0]
        assert r[1] == 'Bash'
        assert r[2] == 'command'
        assert r[3] == 'deny-rm-rf'
        assert r[4] == 'deny'


class TestCommandBlockRecord:
    """コマンド規約block判定 → DB記録"""

    def test_block判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'block-git-push',
                'severity': 'block',
                'message': 'git push確認',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_command_processed', return_value=False):
                hook.process({
                    'tool_name': 'Bash',
                    'tool_input': {'command': 'git push'},
                    'session_id': 'sess-block-cmd',
                })

        records = _get_log_records(db)
        assert len(records) == 1
        assert records[0][2] == 'command'
        assert records[0][4] == 'block'


class TestCommandWarnRecord:
    """コマンド規約warn判定 → DB記録"""

    def test_warn判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'warn-npm-install',
                'severity': 'warn',
                'message': 'npm install注意',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_command_processed', return_value=False):
                hook.process({
                    'tool_name': 'Bash',
                    'tool_input': {'command': 'npm install'},
                    'session_id': 'sess-warn-cmd',
                })

        records = _get_log_records(db)
        assert len(records) == 1
        assert records[0][4] == 'warn'


class TestMcpDenyRecord:
    """MCP規約deny判定 → DB記録"""

    def test_deny判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.mcp_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-mcp-delete',
                'severity': 'deny',
                'message': 'MCP削除禁止',
                'token_threshold': None,
                'scope': None,
            }]
            hook.process({
                'tool_name': 'mcp__test__delete',
                'tool_input': {},
                'session_id': 'sess-deny-mcp',
            })

        records = _get_log_records(db)
        assert len(records) == 1
        r = records[0]
        assert r[1] == 'mcp__test__delete'
        assert r[2] == 'mcp'
        assert r[3] == 'deny-mcp-delete'
        assert r[4] == 'deny'


class TestMcpBlockRecord:
    """MCP規約block判定 → DB記録"""

    def test_block判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.mcp_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'block-mcp-write',
                'severity': 'block',
                'message': 'MCP書き込み確認',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                hook.process({
                    'tool_name': 'mcp__test__write',
                    'tool_input': {},
                    'session_id': 'sess-block-mcp',
                })

        records = _get_log_records(db)
        assert len(records) == 1
        assert records[0][2] == 'mcp'
        assert records[0][4] == 'block'


class TestMcpWarnRecord:
    """MCP規約warn判定 → DB記録"""

    def test_warn判定がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.mcp_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'warn-mcp-read',
                'severity': 'warn',
                'message': 'MCP読み取り注意',
                'token_threshold': None,
                'scope': None,
            }]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                hook.process({
                    'tool_name': 'mcp__test__read',
                    'tool_input': {},
                    'session_id': 'sess-warn-mcp',
                })

        records = _get_log_records(db)
        assert len(records) == 1
        assert records[0][4] == 'warn'


class TestApproveNotRecorded:
    """approve判定 → DB記録されない"""

    def test_ファイルルール非マッチで記録なし(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = []
            hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/safe/file.py'},
                'session_id': 'sess-approve',
            })

        records = _get_log_records(db)
        assert len(records) == 0

    def test_コマンドルール非マッチで記録なし(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.command_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = []
            hook.process({
                'tool_name': 'Bash',
                'tool_input': {'command': 'ls -la'},
                'session_id': 'sess-approve-cmd',
            })

        records = _get_log_records(db)
        assert len(records) == 0

    def test_MCPルール非マッチで記録なし(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.mcp_matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = []
            hook.process({
                'tool_name': 'mcp__safe__tool',
                'tool_input': {},
                'session_id': 'sess-approve-mcp',
            })

        records = _get_log_records(db)
        assert len(records) == 0

    def test_全ルールスキップ時に記録なし(self, hook_with_db):
        """トークン閾値内で全ルールスキップ → approve → 記録なし"""
        hook, db = hook_with_db
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'block-edit',
                'severity': 'block',
                'message': 'Edit blocked',
                'token_threshold': None,
                'scope': None,
            }]
            # ルール処理済み → スキップ → approve
            with patch.object(hook, 'is_rule_processed', return_value=True):
                hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'sess-skip',
                })

        records = _get_log_records(db)
        assert len(records) == 0


class TestScopeRecorded:
    """scopeがDB記録に含まれる"""

    def test_scope値がDB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-coder-edit',
                'severity': 'deny',
                'message': 'coder編集禁止',
                'token_threshold': None,
                'scope': 'coder',
            }]
            # scopeフィルタリングをバイパス（scope=coderのルールを通す）
            with patch.object(hook, '_filter_rules_by_scope', side_effect=lambda rules, _: rules):
                hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/restricted/file.py'},
                    'session_id': 'sess-scope',
                })

        records = _get_log_records(db)
        assert len(records) == 1
        assert records[0][7] == 'coder'  # scope


class TestLogFailureDoesNotAffectHook:
    """ログ記録失敗時のフック動作確認"""

    def test_DB記録失敗でもフック正常動作(self):
        """ConventionLogRepository.insert_log()が例外を投げてもprocess()は正常に返却"""
        hook = ImplementationDesignHook()
        # 例外を投げるモックrepoを設定
        mock_repo = MagicMock()
        mock_repo.insert_log.side_effect = Exception("DB connection error")
        hook._convention_log_repo = mock_repo

        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-test',
                'severity': 'deny',
                'message': 'Test denied',
                'token_threshold': None,
                'scope': None,
            }]
            result = hook.process({
                'tool_name': 'Edit',
                'tool_input': {'file_path': '/test/file.md'},
                'session_id': 'sess-error',
            })

        # フック本体は正常に動作
        assert result['decision'] == 'block'
        assert result.get('skip_warn_only') is True

    def test_repo初期化失敗でもフック正常動作(self):
        """_get_convention_log_repo()が失敗してもprocess()は正常に返却"""
        hook = ImplementationDesignHook()
        # repoをNoneのまま（初期化失敗をシミュレート）

        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [{
                'rule_name': 'deny-test',
                'severity': 'deny',
                'message': 'Test denied',
                'token_threshold': None,
                'scope': None,
            }]
            # _get_convention_log_repoが例外を投げる
            with patch.object(hook, '_get_convention_log_repo', side_effect=Exception("init failed")):
                result = hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'sess-init-error',
                })

        assert result['decision'] == 'block'


class TestMultipleRulesRecorded:
    """複数ルールマッチ時に全件記録"""

    def test_複数ルールが全件DB記録される(self, hook_with_db):
        hook, db = hook_with_db
        with patch.object(hook.matcher, 'get_confirmation_message') as mock_match:
            mock_match.return_value = [
                {
                    'rule_name': 'deny-rule',
                    'severity': 'deny',
                    'message': 'Deny message',
                    'token_threshold': None,
                    'scope': None,
                },
                {
                    'rule_name': 'block-rule',
                    'severity': 'block',
                    'message': 'Block message',
                    'token_threshold': None,
                    'scope': None,
                },
            ]
            with patch.object(hook, 'is_rule_processed', return_value=False):
                hook.process({
                    'tool_name': 'Edit',
                    'tool_input': {'file_path': '/test/file.md'},
                    'session_id': 'sess-multi',
                })

        records = _get_log_records(db)
        assert len(records) == 2
        # severity優先度ソートでdenyが先
        assert records[0][4] == 'deny'
        assert records[1][4] == 'block'


class TestSchemaV9Migration:
    """schema v9マイグレーションテスト"""

    def test_v8からv9へのマイグレーション(self, tmp_path):
        """v8 DBからv9への移行でconvention_logテーブルが作成される"""
        import sqlite3
        from datetime import datetime, timezone

        db_path = tmp_path / "migration_test.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # v8スキーマを直接sqlite3で構築（_ensure_schemaをバイパス）
        raw_conn = sqlite3.connect(str(db_path))
        raw_conn.executescript("""
            CREATE TABLE schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE subagents (
                agent_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                agent_type TEXT NOT NULL DEFAULT 'unknown',
                role TEXT, role_source TEXT,
                created_at TEXT NOT NULL,
                startup_processed INTEGER NOT NULL DEFAULT 0,
                startup_processed_at TEXT,
                task_match_index INTEGER,
                leader_transcript_path TEXT,
                issue_id TEXT
            );
            CREATE TABLE task_spawns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                transcript_index INTEGER NOT NULL,
                subagent_type TEXT, role TEXT,
                prompt_hash TEXT, tool_use_id TEXT,
                matched_agent_id TEXT, issue_id TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(session_id, transcript_index)
            );
            CREATE TABLE sessions (
                session_id TEXT NOT NULL,
                hook_name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_tokens INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                expired_at TEXT,
                PRIMARY KEY (session_id, hook_name)
            );
            CREATE TABLE hook_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                hook_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                agent_id TEXT,
                timestamp TEXT NOT NULL,
                result TEXT, details TEXT,
                duration_ms INTEGER
            );
            CREATE TABLE subagent_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                agent_type TEXT, role TEXT, role_source TEXT,
                leader_transcript_path TEXT,
                started_at TEXT NOT NULL,
                stopped_at TEXT, issue_id TEXT,
                agent_transcript_path TEXT
            );
            CREATE TABLE transcript_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                line_number INTEGER NOT NULL,
                line_type TEXT,
                raw_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                timestamp TEXT, content_summary TEXT,
                tool_name TEXT, token_count INTEGER,
                model TEXT, uuid TEXT
            );
        """)
        now = datetime.now(timezone.utc).isoformat()
        raw_conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (8, now),
        )
        raw_conn.commit()
        raw_conn.close()

        # NaggerStateDBで接続（_ensure_schemaがv8→v9マイグレーションを実行）
        db = NaggerStateDB(db_path)
        db.connect()

        # convention_logテーブル存在確認
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='convention_log'"
        )
        assert cursor.fetchone() is not None

        # インデックス存在確認
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_convention_log_%'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        assert "idx_convention_log_session" in indexes
        assert "idx_convention_log_severity" in indexes

        # バージョン9が記録されている
        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        assert cursor.fetchone()[0] == 9

        # INSERT可能確認
        db.conn.execute(
            "INSERT INTO convention_log (tool_name, convention_type, rule_name, severity, decision) "
            "VALUES ('Bash', 'command', 'test-rule', 'deny', 'blocked')"
        )
        db.conn.commit()
        cursor = db.conn.execute("SELECT COUNT(*) FROM convention_log")
        assert cursor.fetchone()[0] == 1

        db.close()
