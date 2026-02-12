"""task_spawn_guard.py のテスト

ticket-tasuki プラグインの PreToolUse hook スクリプトを
subprocess経由で呼び出し、ブロック・許可・迂回検知の動作を検証する。
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import pytest

# テスト対象スクリプトのパス
GUARD_SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "..",
    ".claude",
    "plugins",
    "ticket-tasuki",
    "hooks",
    "task_spawn_guard.py",
)
GUARD_SCRIPT = os.path.normpath(GUARD_SCRIPT)


def _run_guard(input_data: dict) -> tuple[int, dict | None]:
    """ガードスクリプトを実行し、(終了コード, stdout JSONまたはNone) を返す"""
    proc = subprocess.run(
        [sys.executable, GUARD_SCRIPT],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
    )
    stdout_json = None
    if proc.stdout.strip():
        try:
            stdout_json = json.loads(proc.stdout)
        except json.JSONDecodeError:
            pass
    return proc.returncode, stdout_json


def _make_task_input(
    subagent_type: str = "",
    team_name: str = "",
    prompt: str = "",
    description: str = "",
    session_id: str = "test-session-001",
) -> dict:
    """PreToolUse Task入力データを生成"""
    tool_input = {"subagent_type": subagent_type, "prompt": prompt}
    if team_name:
        tool_input["team_name"] = team_name
    if description:
        tool_input["description"] = description
    return {
        "session_id": session_id,
        "transcript_path": "/tmp/test_transcript.jsonl",
        "cwd": "/workspace",
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Task",
        "tool_input": tool_input,
        "tool_use_id": "toolu_test_001",
    }


def _cleanup_block_record(session_id: str):
    """テスト後のブロック記録ファイルを削除"""
    path = os.path.join(
        tempfile.gettempdir(),
        f"task_spawn_guard_block_{session_id}.json",
    )
    try:
        os.remove(path)
    except OSError:
        pass


class TestBasicBlocking:
    """既存のticket-tasuki:*直接起動ブロック機能"""

    def test_block_ticket_tasuki_direct(self):
        """ticket-tasuki:coder を team_name なしで呼ぶとブロック"""
        data = _make_task_input(subagent_type="ticket-tasuki:coder")
        rc, out = _run_guard(data)
        _cleanup_block_record(data["session_id"])

        assert rc == 0
        assert out is not None
        decision = out["hookSpecificOutput"]["permissionDecision"]
        assert decision == "deny"

    def test_block_ticket_tasuki_scribe(self):
        """ticket-tasuki:scribe も同様にブロック"""
        data = _make_task_input(subagent_type="ticket-tasuki:scribe")
        rc, out = _run_guard(data)
        _cleanup_block_record(data["session_id"])

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_allow_ticket_tasuki_with_team_name(self):
        """team_name 指定ありなら許可"""
        data = _make_task_input(
            subagent_type="ticket-tasuki:coder",
            team_name="my-team",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # 出力なし = 許可

    def test_allow_non_ticket_tasuki(self):
        """ticket-tasuki以外のsubagent_typeは許可"""
        data = _make_task_input(subagent_type="coder")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_allow_general_purpose_without_block(self):
        """ブロック記録なしのgeneral-purposeは無条件許可"""
        session_id = "test-no-block-session"
        _cleanup_block_record(session_id)
        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=session_id,
            prompt="Web検索でReactのドキュメントを調べてください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_ignore_non_task_tool(self):
        """Task以外のツール名は無視"""
        data = {
            "session_id": "test-session",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "echo hello"},
        }
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None


class TestBlockMessageContent:
    """#6103: ブロックメッセージに迂回禁止が明記されているか"""

    def test_block_message_contains_circumvention_warning(self):
        """ブロックメッセージに迂回禁止の注意書きが含まれる"""
        data = _make_task_input(subagent_type="ticket-tasuki:coder")
        rc, out = _run_guard(data)
        _cleanup_block_record(data["session_id"])

        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "迂回禁止" in reason
        assert "general-purpose" in reason
        assert "代替エージェント" in reason

    def test_block_message_contains_original_info(self):
        """ブロックメッセージに従来の情報も含まれる"""
        data = _make_task_input(subagent_type="ticket-tasuki:coder")
        rc, out = _run_guard(data)
        _cleanup_block_record(data["session_id"])

        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "ticket-tasuki:coder" in reason
        assert "Agent Teams" in reason


class TestCircumventionDetection:
    """#6102: 迂回検知機能"""

    def setup_method(self):
        """各テスト前にセッション固有のブロック記録をクリア"""
        self.session_id = f"test-circumvention-{os.getpid()}"
        _cleanup_block_record(self.session_id)

    def teardown_method(self):
        _cleanup_block_record(self.session_id)

    def _trigger_block(self):
        """ブロックを発生させてブロック記録を作成"""
        data = _make_task_input(
            subagent_type="ticket-tasuki:coder",
            session_id=self.session_id,
        )
        _run_guard(data)

    def test_detect_circumvention_with_redmine_prompt(self):
        """ブロック後にredmine関連のpromptでgeneral-purposeを起動すると警告"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="Redmineのチケット#123にコメントを追加してください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
        assert "迂回検知" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_detect_circumvention_with_ticket_tasuki_prompt(self):
        """ブロック後にticket-tasuki言及のpromptで警告"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="ticket-tasukiのscribe機能を使ってチケットを作成して",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_detect_circumvention_with_issue_create_prompt(self):
        """ブロック後にissue操作系のpromptで警告"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="issue create a new task for the sprint",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_detect_circumvention_japanese_ticket_prompt(self):
        """ブロック後に日本語のチケット操作系promptで警告"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="チケット起票をお願いします",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_no_circumvention_for_unrelated_prompt(self):
        """ブロック後でもticket-tasuki無関係のpromptは許可"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="Reactコンポーネントのユニットテストを書いてください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # 許可

    def test_no_circumvention_with_team_name(self):
        """ブロック後でもteam_name指定ありなら迂回検知しない"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            team_name="my-team",
            session_id=self.session_id,
            prompt="Redmineチケットを更新してください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_no_circumvention_for_specific_subagent_type(self):
        """ブロック後でもcoder等の特定subagent_typeは迂回検知対象外"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="coder",
            session_id=self.session_id,
            prompt="Redmineの設定ファイルを修正してください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_circumvention_warning_contains_blocked_type(self):
        """迂回警告メッセージにブロックされたsubagent_typeが含まれる"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="Redmineのチケットにコメントしてください",
        )
        _, out = _run_guard(data)

        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "ticket-tasuki:coder" in reason

    def test_block_record_expires(self):
        """ブロック記録はTTL後に失効する"""
        self._trigger_block()

        # ブロック記録のタイムスタンプを過去に変更
        path = os.path.join(
            tempfile.gettempdir(),
            f"task_spawn_guard_block_{self.session_id}.json",
        )
        with open(path) as f:
            record = json.load(f)
        record["blocked_at"] = time.time() - 400  # TTL(300秒)を超過
        with open(path, "w") as f:
            json.dump(record, f)

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="Redmineのチケットにコメントしてください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # TTL超過で許可

    def test_detect_circumvention_in_description(self):
        """promptだけでなくdescriptionの内容でも迂回検知"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="general-purpose",
            session_id=self.session_id,
            prompt="以下のタスクを実行してください",
            description="Redmineチケット管理を行う",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_empty_subagent_type_also_detected(self):
        """subagent_type未指定（空文字）でも迂回検知対象"""
        self._trigger_block()

        data = _make_task_input(
            subagent_type="",
            session_id=self.session_id,
            prompt="ticket_tasukiでチケットを更新してください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"


class TestEdgeCases:
    """エッジケースのテスト"""

    def test_invalid_json_input(self):
        """不正なJSON入力は許可（exit 0）"""
        proc = subprocess.run(
            [sys.executable, GUARD_SCRIPT],
            input="invalid json",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        assert proc.stdout.strip() == ""

    def test_empty_input(self):
        """空入力は許可"""
        proc = subprocess.run(
            [sys.executable, GUARD_SCRIPT],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0

    def test_missing_session_id(self):
        """session_id がない場合でもブロックは動作する"""
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {"subagent_type": "ticket-tasuki:coder"},
        }
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_missing_session_id_no_circumvention_check(self):
        """session_id がない場合は迂回検知をスキップ"""
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "Redmine チケットを作成",
            },
        }
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None
