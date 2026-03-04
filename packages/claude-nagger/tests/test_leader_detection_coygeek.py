"""coygeek方式leader検出PoCテスト（issue_7327）

テストシナリオ:
1. leader単独作業時（Task tool_useなし）→ True期待
2. subagent1台起動時（Task tool_useあり）→ False期待
3. 並列subagent時（複数Task tool_useあり）→ False期待
4. transcript未存在時 → False期待（フォールバック）
5. 空transcript → True期待
6. leaderのTask以外のtool_use（Read/Edit等）のみ → True期待
"""

import json
import os
import tempfile

import pytest

from domain.services.leader_detection_coygeek import is_leader_coygeek


def _write_jsonl(path: str, entries: list[dict]) -> None:
    """テスト用ヘルパー: JSONL形式でエントリを書き込む"""
    with open(path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _make_assistant_entry(tool_uses: list[dict]) -> dict:
    """テスト用ヘルパー: assistantエントリを生成"""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": tu["id"], "name": tu["name"], "input": tu.get("input", {})}
                for tu in tool_uses
            ],
        },
    }


def _make_user_entry(text: str = "テスト指示") -> dict:
    """テスト用ヘルパー: userエントリを生成"""
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


class TestIsLeaderCoygeek:
    """coygeek方式leader検出PoCの精度検証"""

    def test_leader_solo_no_task(self, tmp_path):
        """leader単独作業: Task tool_useなし → True"""
        transcript = str(tmp_path / "transcript.jsonl")
        entries = [
            _make_user_entry("ファイルを読んで"),
            _make_assistant_entry([
                {"id": "toolu_01AAA", "name": "Read", "input": {"file_path": "/src/main.py"}},
            ]),
            _make_assistant_entry([
                {"id": "toolu_01BBB", "name": "Edit", "input": {"file_path": "/src/main.py"}},
                {"id": "toolu_01CCC", "name": "Bash", "input": {"command": "pytest"}},
            ]),
        ]
        _write_jsonl(transcript, entries)

        assert is_leader_coygeek(transcript) is True

    def test_single_subagent_spawned(self, tmp_path):
        """subagent1台起動: Task tool_useあり → False"""
        transcript = str(tmp_path / "transcript.jsonl")
        entries = [
            _make_user_entry("テスト実行して"),
            _make_assistant_entry([
                {"id": "toolu_01AAA", "name": "Read", "input": {"file_path": "/src/main.py"}},
            ]),
            _make_assistant_entry([
                {"id": "toolu_01TASK1", "name": "Task", "input": {"prompt": "テスト実行"}},
            ]),
        ]
        _write_jsonl(transcript, entries)

        assert is_leader_coygeek(transcript) is False

    def test_parallel_subagents(self, tmp_path):
        """並列subagent: 複数Task tool_useあり → False"""
        transcript = str(tmp_path / "transcript.jsonl")
        entries = [
            _make_user_entry("並列で作業して"),
            _make_assistant_entry([
                {"id": "toolu_01TASK1", "name": "Task", "input": {"prompt": "テスト実行"}},
                {"id": "toolu_01TASK2", "name": "Task", "input": {"prompt": "リント実行"}},
                {"id": "toolu_01TASK3", "name": "Task", "input": {"prompt": "ビルド実行"}},
            ]),
        ]
        _write_jsonl(transcript, entries)

        assert is_leader_coygeek(transcript) is False

    def test_transcript_not_found(self):
        """transcript未存在 → False（フォールバック）"""
        assert is_leader_coygeek("/nonexistent/path/transcript.jsonl") is False

    def test_empty_transcript(self, tmp_path):
        """空transcript → True（Task tool_useなし）"""
        transcript = str(tmp_path / "transcript.jsonl")
        _write_jsonl(transcript, [])

        assert is_leader_coygeek(transcript) is True

    def test_only_non_task_tool_uses(self, tmp_path):
        """Task以外のtool_useのみ → True"""
        transcript = str(tmp_path / "transcript.jsonl")
        entries = [
            _make_user_entry(),
            _make_assistant_entry([
                {"id": "toolu_01AAA", "name": "Read", "input": {}},
                {"id": "toolu_01BBB", "name": "Write", "input": {}},
                {"id": "toolu_01CCC", "name": "Bash", "input": {}},
                {"id": "toolu_01DDD", "name": "Glob", "input": {}},
                {"id": "toolu_01EEE", "name": "Grep", "input": {}},
            ]),
        ]
        _write_jsonl(transcript, entries)

        assert is_leader_coygeek(transcript) is True

    def test_task_after_non_task_tools(self, tmp_path):
        """非Taskツール使用後にTask起動 → False"""
        transcript = str(tmp_path / "transcript.jsonl")
        entries = [
            _make_user_entry(),
            _make_assistant_entry([
                {"id": "toolu_01AAA", "name": "Read", "input": {}},
            ]),
            _make_assistant_entry([
                {"id": "toolu_01BBB", "name": "Edit", "input": {}},
            ]),
            # leaderがsubagentを起動
            _make_assistant_entry([
                {"id": "toolu_01TASK1", "name": "Task", "input": {"prompt": "作業委任"}},
            ]),
        ]
        _write_jsonl(transcript, entries)

        assert is_leader_coygeek(transcript) is False

    def test_malformed_json_lines_skipped(self, tmp_path):
        """不正JSONは無視して走査継続"""
        transcript = str(tmp_path / "transcript.jsonl")
        with open(transcript, "w", encoding="utf-8") as f:
            f.write("invalid json\n")
            f.write("{bad json\n")
            f.write(json.dumps(_make_user_entry()) + "\n")
            f.write(json.dumps(_make_assistant_entry([
                {"id": "toolu_01AAA", "name": "Read", "input": {}},
            ])) + "\n")

        # Task tool_useなし → True
        assert is_leader_coygeek(transcript) is True

    def test_limitation_leader_pretooluse_after_task_spawn(self, tmp_path):
        """【限界】leaderのPreToolUse（Task起動後）でもFalse返却

        coygeek方式の根本的制約: leaderがTask起動後に自身のツールを
        使おうとした場合、transcriptにはTask tool_useが存在するため
        False（非leader）と誤判定される。
        """
        transcript = str(tmp_path / "transcript.jsonl")
        entries = [
            _make_user_entry(),
            # leaderがsubagent起動
            _make_assistant_entry([
                {"id": "toolu_01TASK1", "name": "Task", "input": {"prompt": "調査"}},
            ]),
            # leaderが自身でもツール使用（subagentと並行）
            _make_assistant_entry([
                {"id": "toolu_01LEADER_AFTER", "name": "Bash", "input": {"command": "ls"}},
            ]),
        ]
        _write_jsonl(transcript, entries)

        # 実際はleaderだがFalse返却（誤判定=既知の限界）
        assert is_leader_coygeek(transcript) is False
