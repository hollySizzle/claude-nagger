"""TranscriptRepository 単体テスト"""

import json
from pathlib import Path

import pytest

from infrastructure.db.nagger_state_db import NaggerStateDB
from infrastructure.db.transcript_repository import TranscriptRepository


# === フィクスチャ ===

@pytest.fixture
def sample_jsonl(tmp_path):
    """テスト用.jsonlファイル（複数行タイプ）"""
    jsonl_path = tmp_path / "transcript.jsonl"
    lines = [
        {"type": "user", "message": {"content": "ファイルを読んでください"}},
        {"type": "assistant", "message": {"content": "はい", "usage": {"input_tokens": 100, "output_tokens": 50}}},
        {"type": "progress", "data": {"type": "tool_use", "name": "Read"}},
        {"type": "user", "message": {"content": "ありがとう"}},
        {"type": "assistant", "message": {"content": "どういたしまして"}},
    ]
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    return jsonl_path


# === store_and_retrieveテスト ===

class TestStoreAndRetrieve:
    """格納→取得の往復テスト"""

    def test_store_and_retrieve(self, db, sample_jsonl):
        """格納した行を正しく取得できる"""
        repo = TranscriptRepository(db)

        # 格納
        count = repo.store_transcript("test-session", str(sample_jsonl))
        assert count == 5

        # 取得
        lines = repo.get_transcript_lines("test-session")
        assert len(lines) == 5

        # 行番号の順序確認
        for i, line in enumerate(lines):
            assert line.line_number == i + 1
            assert line.session_id == "test-session"
            assert line.raw_json  # 空でないこと

        # 最初の行のJSON内容確認
        first_json = json.loads(lines[0].raw_json)
        assert first_json["type"] == "user"

    def test_store_empty_file(self, db, tmp_path):
        """空ファイルの格納で0行"""
        empty_path = tmp_path / "empty.jsonl"
        empty_path.write_text("")

        repo = TranscriptRepository(db)
        count = repo.store_transcript("test-session", str(empty_path))
        assert count == 0

        lines = repo.get_transcript_lines("test-session")
        assert len(lines) == 0

    def test_store_nonexistent_file(self, db):
        """存在しないファイルで0行"""
        repo = TranscriptRepository(db)
        count = repo.store_transcript("test-session", "/nonexistent/file.jsonl")
        assert count == 0

    def test_retrieve_nonexistent_session(self, db):
        """存在しないセッションで空リスト"""
        repo = TranscriptRepository(db)
        lines = repo.get_transcript_lines("nonexistent-session")
        assert len(lines) == 0

    def test_multiple_sessions_isolated(self, db, tmp_path):
        """異なるセッションのデータが分離される"""
        repo = TranscriptRepository(db)

        # セッション1用ファイル
        path1 = tmp_path / "session1.jsonl"
        path1.write_text(json.dumps({"type": "user", "message": "hello"}) + "\n")

        # セッション2用ファイル
        path2 = tmp_path / "session2.jsonl"
        path2.write_text(json.dumps({"type": "assistant", "message": "hi"}) + "\n")

        repo.store_transcript("session-1", str(path1))
        repo.store_transcript("session-2", str(path2))

        lines1 = repo.get_transcript_lines("session-1")
        lines2 = repo.get_transcript_lines("session-2")

        assert len(lines1) == 1
        assert len(lines2) == 1
        assert lines1[0].line_type == "user"
        assert lines2[0].line_type == "assistant"


# === line_type抽出テスト ===

class TestLineTypeExtraction:
    """user/assistant/progress の type 抽出"""

    def test_line_type_extraction(self, db, sample_jsonl):
        """各行のline_typeが正しく抽出される"""
        repo = TranscriptRepository(db)
        repo.store_transcript("test-session", str(sample_jsonl))

        lines = repo.get_transcript_lines("test-session")
        types = [line.line_type for line in lines]
        assert types == ["user", "assistant", "progress", "user", "assistant"]

    def test_line_type_filter(self, db, sample_jsonl):
        """line_typeでフィルタできる"""
        repo = TranscriptRepository(db)
        repo.store_transcript("test-session", str(sample_jsonl))

        user_lines = repo.get_transcript_lines("test-session", line_type="user")
        assert len(user_lines) == 2

        assistant_lines = repo.get_transcript_lines("test-session", line_type="assistant")
        assert len(assistant_lines) == 2

        progress_lines = repo.get_transcript_lines("test-session", line_type="progress")
        assert len(progress_lines) == 1

    def test_invalid_json_line_type_none(self, db, tmp_path):
        """不正JSONの行はline_type=Noneで格納"""
        path = tmp_path / "invalid.jsonl"
        path.write_text("not valid json\n")

        repo = TranscriptRepository(db)
        count = repo.store_transcript("test-session", str(path))
        assert count == 1

        lines = repo.get_transcript_lines("test-session")
        assert len(lines) == 1
        assert lines[0].line_type is None
        assert lines[0].raw_json == "not valid json"

    def test_json_without_type_field(self, db, tmp_path):
        """typeフィールドがないJSONはline_type=None"""
        path = tmp_path / "no_type.jsonl"
        path.write_text(json.dumps({"message": "no type"}) + "\n")

        repo = TranscriptRepository(db)
        count = repo.store_transcript("test-session", str(path))
        assert count == 1

        lines = repo.get_transcript_lines("test-session")
        assert lines[0].line_type is None


# === スキーママイグレーションテスト ===

class TestSchemaMigrationV6:
    """v5→v6マイグレーション・スキーマテスト"""

    def test_schema_version_is_6(self, tmp_path):
        """新規DBのスキーマバージョンが7"""
        db_path = tmp_path / ".claude-nagger" / "state.db"
        db = NaggerStateDB(db_path)
        db.connect()

        cursor = db.conn.execute("SELECT MAX(version) FROM schema_version")
        row = cursor.fetchone()
        assert row[0] == 8

        db.close()

    def test_fresh_db_has_metadata_columns(self, db):
        """新規DBにメタデータカラムが存在する"""
        cursor = db.conn.execute("PRAGMA table_info(transcript_lines)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        # 基本カラム
        assert "id" in columns
        assert "session_id" in columns
        assert "line_number" in columns
        assert "line_type" in columns
        assert "raw_json" in columns
        assert "created_at" in columns
        # v6追加カラム
        assert "timestamp" in columns
        assert "content_summary" in columns
        assert "tool_name" in columns
        assert "token_count" in columns
        assert "model" in columns
        assert "uuid" in columns

    def test_timestamp_index_exists(self, db):
        """timestampインデックスが存在する"""
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_transcript_lines_timestamp'"
        )
        assert cursor.fetchone() is not None

    def test_fresh_db_has_transcript_lines(self, db):
        """新規DBにtranscript_linesテーブルが存在する"""
        cursor = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='transcript_lines'"
        )
        assert cursor.fetchone() is not None

    def test_transcript_insert_and_select(self, db):
        """transcript_linesテーブルにINSERT/SELECTできる"""
        db.conn.execute(
            """
            INSERT INTO transcript_lines (session_id, line_number, line_type, raw_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("sess-1", 1, "user", '{"type":"user"}', "2026-01-01T00:00:00Z"),
        )
        db.conn.commit()

        cursor = db.conn.execute(
            "SELECT session_id, line_number, line_type, raw_json FROM transcript_lines WHERE session_id = ?",
            ("sess-1",),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == "sess-1"
        assert row[1] == 1
        assert row[2] == "user"
        assert row[3] == '{"type":"user"}'


# === indexed modeテスト ===

class TestIndexedMode:
    """indexed/structuredモードのメタデータ抽出テスト"""

    def test_indexed_mode_extracts_metadata(self, db, tmp_path):
        """indexedモードでメタデータが格納される"""
        path = tmp_path / "indexed.jsonl"
        lines = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": "テストメッセージ",
                "uuid": "user-uuid-1",
            },
            {
                "type": "assistant",
                "timestamp": "2026-01-01T00:00:01Z",
                "message": {
                    "model": "claude-opus-4-6",
                    "content": [{"type": "text", "text": "応答テキスト"}],
                    "usage": {"input_tokens": 200, "output_tokens": 100},
                },
                "uuid": "asst-uuid-1",
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        repo = TranscriptRepository(db, mode="indexed")
        repo.store_transcript("test-session", str(path))

        results = repo.get_transcript_lines("test-session")
        assert len(results) == 2

        # user行
        user_line = results[0]
        assert user_line.timestamp == "2026-01-01T00:00:00Z"
        assert user_line.uuid == "user-uuid-1"
        assert user_line.content_summary == "テストメッセージ"
        assert user_line.tool_name is None
        assert user_line.token_count is None
        assert user_line.model is None

        # assistant行
        asst_line = results[1]
        assert asst_line.timestamp == "2026-01-01T00:00:01Z"
        assert asst_line.uuid == "asst-uuid-1"
        assert asst_line.content_summary == "応答テキスト"
        assert asst_line.token_count == 300  # 200 + 100
        assert asst_line.model == "claude-opus-4-6"

    def test_raw_mode_no_metadata(self, db, tmp_path):
        """rawモードでメタデータカラムがNULL"""
        path = tmp_path / "raw.jsonl"
        lines = [
            {
                "type": "user",
                "timestamp": "2026-01-01T00:00:00Z",
                "message": "テスト",
                "uuid": "user-uuid-1",
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        repo = TranscriptRepository(db, mode="raw")
        repo.store_transcript("test-session", str(path))

        results = repo.get_transcript_lines("test-session")
        assert len(results) == 1

        line = results[0]
        assert line.timestamp is None
        assert line.content_summary is None
        assert line.tool_name is None
        assert line.token_count is None
        assert line.model is None
        assert line.uuid is None

    def test_content_summary_truncation(self, db, tmp_path):
        """100文字で切り詰め"""
        long_text = "あ" * 200
        path = tmp_path / "long.jsonl"
        lines = [
            {
                "type": "user",
                "message": long_text,
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        repo = TranscriptRepository(db, mode="indexed")
        repo.store_transcript("test-session", str(path))

        results = repo.get_transcript_lines("test-session")
        assert len(results) == 1
        assert len(results[0].content_summary) == 100

    def test_tool_name_extraction(self, db, tmp_path):
        """tool_use時のツール名抽出"""
        path = tmp_path / "tools.jsonl"
        lines = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}},
                        {"type": "tool_use", "name": "Read", "input": {"path": "/tmp"}},
                    ],
                    "usage": {"input_tokens": 50, "output_tokens": 10},
                },
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        repo = TranscriptRepository(db, mode="indexed")
        repo.store_transcript("test-session", str(path))

        results = repo.get_transcript_lines("test-session")
        assert len(results) == 1
        assert results[0].tool_name == "Bash,Read"
        # content_summaryはtool_useの場合ツール名
        assert results[0].content_summary == "Bash"

    def test_token_count_extraction(self, db, tmp_path):
        """トークン数計算"""
        path = tmp_path / "tokens.jsonl"
        lines = [
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "hello"}],
                    "usage": {"input_tokens": 500, "output_tokens": 250},
                },
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        repo = TranscriptRepository(db, mode="indexed")
        repo.store_transcript("test-session", str(path))

        results = repo.get_transcript_lines("test-session")
        assert len(results) == 1
        assert results[0].token_count == 750

    def test_metadata_extraction_with_malformed_json(self, db, tmp_path):
        """不正JSONでも安全にメタデータ抽出"""
        path = tmp_path / "malformed.jsonl"
        with open(path, "w", encoding="utf-8") as f:
            f.write("not valid json\n")
            f.write(json.dumps({"type": "user", "message": "正常行"}) + "\n")

        repo = TranscriptRepository(db, mode="indexed")
        count = repo.store_transcript("test-session", str(path))
        assert count == 2

        results = repo.get_transcript_lines("test-session")
        assert len(results) == 2

        # 不正JSON行: メタデータはすべてNone
        assert results[0].line_type is None
        assert results[0].timestamp is None
        assert results[0].content_summary is None

        # 正常行: メタデータ抽出OK
        assert results[1].line_type == "user"
        assert results[1].content_summary == "正常行"

    def test_progress_hook_name_extraction(self, db, tmp_path):
        """progress行のhookName抽出"""
        path = tmp_path / "progress.jsonl"
        lines = [
            {
                "type": "progress",
                "timestamp": "2026-01-01T00:00:00Z",
                "data": {"type": "hook_progress", "hookName": "PreToolUse:Bash"},
                "uuid": "prog-uuid-1",
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        repo = TranscriptRepository(db, mode="indexed")
        repo.store_transcript("test-session", str(path))

        results = repo.get_transcript_lines("test-session")
        assert len(results) == 1
        assert results[0].tool_name == "PreToolUse:Bash"
        assert results[0].timestamp == "2026-01-01T00:00:00Z"
        assert results[0].uuid == "prog-uuid-1"

    def test_user_message_dict_content(self, db, tmp_path):
        """user行で.messageがdictの場合のcontent_summary抽出"""
        path = tmp_path / "user_dict.jsonl"
        lines = [
            {
                "type": "user",
                "message": {"role": "user", "content": "dictの中のcontent"},
            },
        ]
        with open(path, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")

        repo = TranscriptRepository(db, mode="indexed")
        repo.store_transcript("test-session", str(path))

        results = repo.get_transcript_lines("test-session")
        assert results[0].content_summary == "dictの中のcontent"


# === delete_old_transcriptsテスト ===

class TestDeleteOldTranscripts:
    """retention管理スタブテスト"""

    def test_stub_returns_zero(self, db):
        """スタブ実装は0を返す"""
        repo = TranscriptRepository(db)
        result = repo.delete_old_transcripts(30)
        assert result == 0
