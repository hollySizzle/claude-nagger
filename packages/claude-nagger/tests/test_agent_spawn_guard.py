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
) -> dict:
    """PreToolUse Agent入力データを生成"""
    tool_input = {"subagent_type": subagent_type}
    if team_name:
        tool_input["team_name"] = team_name
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
        data = _make_agent_input(subagent_type=agent_type)
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # 完全許可

    def test_allow_statusline_setup(self):
        """statusline-setupは許可（BUILTIN_WHITELISTに含まれる）"""
        data = _make_agent_input(subagent_type="statusline-setup")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_allow_claude_code_guide(self):
        """claude-code-guideは許可（BUILTIN_WHITELISTに含まれる）"""
        data = _make_agent_input(subagent_type="claude-code-guide")
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

    def test_allow_with_team_name(self, tmp_path):
        """team_name指定あり＋config.json実在は許可"""
        # config.jsonを配置した仮HOMEを作成
        config_dir = tmp_path / ".claude" / "teams" / "my-team"
        config_dir.mkdir(parents=True)
        (config_dir / "config.json").write_text("{}")
        env = {**os.environ, "HOME": str(tmp_path)}

        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="my-team",
        )
        rc, out = _run_guard(data, env=env)

        assert rc == 0
        assert out is None

    def test_block_fake_team_name(self):
        """team_name指定あり＋config.json不在はdeny（偽装対策）"""
        # 存在しないチーム名を使用
        env = {**os.environ, "HOME": tempfile.mkdtemp()}
        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="fake-team",
        )
        rc, out = _run_guard(data, env=env)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

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
