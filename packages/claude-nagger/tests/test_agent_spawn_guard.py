"""agent_spawn_guard.py のテスト

Agent tool経由のsub-agent直接起動ガードの動作を検証する。
- ビルトインホワイトリスト（Explore, Plan, statusline-setup, claude-code-guide）は許可
- team_name指定あり → 許可
- team_name空白のみ → deny（strip()で空扱い）
- subagent（agent_context="subagent"）は制約対象外
- それ以外 → deny
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

# テスト対象スクリプトのパス
GUARD_SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "..",
    ".claude",
    "plugins",
    "ticket-tasuki",
    "hooks",
    "agent_spawn_guard.py",
)
GUARD_SCRIPT = os.path.normpath(GUARD_SCRIPT)


def _run_guard(input_data: dict, env: dict | None = None) -> tuple[int, dict | None]:
    """ガードスクリプトを実行し、(終了コード, stdout JSONまたはNone) を返す"""
    proc = subprocess.run(
        [sys.executable, GUARD_SCRIPT],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    stdout_json = None
    if proc.stdout.strip():
        try:
            stdout_json = json.loads(proc.stdout)
        except json.JSONDecodeError:
            pass
    return proc.returncode, stdout_json


def _make_agent_input(
    subagent_type: str = "",
    team_name: str = "",
    agent_context: str = "",
    prompt: str = "",
) -> dict:
    """PreToolUse Agent入力データを生成"""
    tool_input = {"subagent_type": subagent_type}
    if team_name:
        tool_input["team_name"] = team_name
    if prompt:
        tool_input["prompt"] = prompt
    data = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": tool_input,
    }
    if agent_context:
        data["agent_context"] = agent_context
    return data


class TestBuiltinWhitelist:
    """ビルトインホワイトリストの許可テスト"""

    @pytest.mark.parametrize("agent_type", ["Explore", "Plan"])
    def test_allow_builtin_types(self, agent_type):
        """ホワイトリスト対象はteam_name不要で許可"""
        data = _make_agent_input(subagent_type=agent_type, prompt="issue_1234 do something")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # 完全許可

    def test_allow_statusline_setup(self):
        """statusline-setupは許可（BUILTIN_WHITELISTに含まれる）"""
        data = _make_agent_input(subagent_type="statusline-setup", prompt="issue_1234")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_allow_claude_code_guide(self):
        """claude-code-guideは許可（BUILTIN_WHITELISTに含まれる）"""
        data = _make_agent_input(subagent_type="claude-code-guide", prompt="issue_1234")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_case_sensitive_whitelist(self):
        """ホワイトリストは大文字小文字を区別する"""
        data = _make_agent_input(subagent_type="explore")  # 小文字
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestTeamNameHandling:
    """team_name指定による許可・拒否テスト"""

    def test_allow_with_team_name(self):
        """team_name指定ありは許可（config.json不要）"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="my-team",
            prompt="issue_7579 implement feature",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_allow_with_team_name_no_config(self):
        """team_name指定あり＋config.json不在でも許可"""
        env = {**os.environ, "HOME": tempfile.mkdtemp()}
        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="any-team",
            prompt="issue_7947 test",
        )
        rc, out = _run_guard(data, env=env)

        assert rc == 0
        assert out is None

    @pytest.mark.parametrize("role", ["coder", "tech-lead", "tester", "pmo"])
    def test_allow_all_ticket_tasuki_roles_with_team_name(self, role):
        """team_name指定時に全ticket-tasukiロールが許可される"""
        data = _make_agent_input(
            subagent_type=role,
            team_name="my-team",
            prompt="issue_7947 do work",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_block_without_team_name(self):
        """team_name未指定はdeny"""
        data = _make_agent_input(subagent_type="general-purpose")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_whitespace_only_team_name_treated_as_empty(self):
        """team_name=" "（空白文字のみ）はstrip()で空扱い→deny"""
        data = _make_agent_input(subagent_type="general-purpose")
        # _make_agent_inputはteam_name truthyなのでtool_inputに含まれる
        data["tool_input"]["team_name"] = " "
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestSubagentContext:
    """agent_context="subagent"の制約対象外テスト"""

    def test_subagent_context_bypasses_guard(self):
        """subagentからの呼び出しは制約対象外"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            agent_context="subagent",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None


class TestNonAgentTool:
    """Agent以外のtool_nameは対象外"""

    def test_ignore_non_agent_tool(self):
        """Agent以外のtool_nameはスキップ"""
        data = _make_agent_input(subagent_type="general-purpose")
        data["tool_name"] = "Task"
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None


class TestIssueIdCheck:
    """issue_{id}トレーサビリティチェックのテスト"""

    def test_warn_when_issue_id_missing_builtin(self):
        """ビルトイン許可時にissue_id欠落でask警告"""
        data = _make_agent_input(subagent_type="Explore", prompt="do something")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_warn_when_issue_id_missing_team_name(self):
        """team_name許可時にissue_id欠落でask警告"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="my-team",
            prompt="no ticket reference here",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_no_warn_when_issue_id_present(self):
        """issue_id含む場合は警告なしで許可"""
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 fix bug")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_warn_when_prompt_empty(self):
        """prompt空文字でask警告"""
        data = _make_agent_input(subagent_type="Plan", prompt="")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_deny_takes_priority_over_issue_id_warn(self):
        """deny判定はissue_id警告より優先"""
        data = _make_agent_input(subagent_type="general-purpose", prompt="no issue id")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


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

    def test_empty_subagent_type_blocked(self):
        """subagent_type空文字はdeny"""
        data = _make_agent_input(subagent_type="")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
