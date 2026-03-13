"""agent_spawn_guard.py のテスト

Agent tool経由のsub-agent直接起動ガードの動作を検証する。
- ビルトインホワイトリスト（Explore, Plan, statusline-setup, claude-code-guide）は許可
- team_name指定あり + promptパターン合致 → override注入(allow+updatedInput)
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


def _assert_override_output(out: dict, original_prompt: str) -> None:
    """override注入出力の構造を検証するヘルパー"""
    assert out is not None
    hook_output = out["hookSpecificOutput"]
    assert hook_output["permissionDecision"] == "allow"
    assert "updatedInput" in hook_output
    updated_prompt = hook_output["updatedInput"]["prompt"]
    assert updated_prompt.startswith(original_prompt + "\n\n")
    # override指示が付加されていることを確認
    assert len(updated_prompt) > len(original_prompt) + 2


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
        """team_name指定あり+promptパターン合致→override注入(allow+updatedInput)"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="my-team",
            prompt="issue_7579",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_7579")

    def test_allow_with_team_name_no_config(self):
        """team_name指定あり＋config不在でもデフォルトoverride指示で許可"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="any-team",
            prompt="issue_7947",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_7947")

    @pytest.mark.parametrize("role", ["coder", "tech-lead", "tester", "pmo"])
    def test_allow_all_ticket_tasuki_roles_with_team_name(self, role):
        """team_name指定時に全ticket-tasukiロールがoverride注入付きで許可（promptパターン準拠）"""
        data = _make_agent_input(
            subagent_type=role,
            team_name="my-team",
            prompt="issue_7947",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_7947")

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

    def test_deny_when_issue_id_missing_team_name(self):
        """team_name指定+非ビルトインでpromptパターン不一致→deny（promptパターン制限優先）"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            team_name="my-team",
            prompt="no ticket reference here",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

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


class TestAdditionalScenarios:
    """追加受入テストシナリオ (issue_7947)"""

    def test_empty_string_team_name_deny(self):
        """team_name空文字はdeny"""
        data = _make_agent_input(subagent_type="general-purpose")
        data["tool_input"]["team_name"] = ""
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_tech_lead_without_team_name_deny(self):
        """tech-leadロール単独（team_nameなし）はdeny"""
        data = _make_agent_input(subagent_type="tech-lead")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_tester_without_team_name_deny(self):
        """testerロール単独（team_nameなし）はdeny"""
        data = _make_agent_input(subagent_type="tester")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_pmo_without_team_name_deny(self):
        """pmoロール単独（team_nameなし）はdeny"""
        data = _make_agent_input(subagent_type="pmo")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_no_subagent_type_key_in_tool_input(self):
        """tool_inputにsubagent_typeキーなしはdeny"""
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {},
        }
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_subagent_context_without_team_name(self):
        """subagentコンテキスト+team_nameなしはバイパス（許可）"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            agent_context="subagent",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_tab_only_team_name_deny(self):
        """team_nameタブ文字のみはstrip()で空扱い→deny"""
        data = _make_agent_input(subagent_type="general-purpose")
        data["tool_input"]["team_name"] = "\t"
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_team_name_with_surrounding_whitespace_allow(self):
        """team_name前後空白ありはstrip()後有効→override注入付き許可"""
        data = _make_agent_input(
            subagent_type="general-purpose",
            prompt="issue_7947",
        )
        data["tool_input"]["team_name"] = "  my-team  "
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_7947")


class TestPromptPatternRestriction:
    """promptパターン制限のテスト（issue_8132）"""

    def test_valid_prompt_pattern_allowed(self):
        """issue_1234形式のpromptはoverride注入付き許可"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_1234")

    def test_valid_prompt_pattern_6digits(self):
        """6桁のissue_idもoverride注入付き許可"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_123456",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_123456")

    def test_valid_prompt_pattern_1digit(self):
        """1桁のissue_idもoverride注入付き許可"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_1")

    def test_deny_prompt_with_extra_text(self):
        """issue_1234に追加テキストがある場合はdeny"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234 implement feature",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_deny_prompt_freeform(self):
        """自由文promptはdeny"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="implement the login feature",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_deny_prompt_empty(self):
        """空promptはdeny"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_deny_prompt_7digits(self):
        """7桁のissue_idはdeny（上限6桁）"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234567",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_builtin_exempt_from_prompt_pattern(self):
        """ビルトインsubagent_typeはpromptパターン制限対象外"""
        data = _make_agent_input(
            subagent_type="Explore",
            team_name="my-team",
            prompt="explore the codebase for auth patterns",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        # ビルトインはprompt自由文OK（issue_id欠落のask警告のみ）
        if out is not None:
            assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_builtin_plan_exempt_from_prompt_pattern(self):
        """Plan subagent_typeもpromptパターン制限対象外"""
        data = _make_agent_input(
            subagent_type="Plan",
            team_name="my-team",
            prompt="issue_1234 plan the implementation",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    @pytest.mark.parametrize("role", ["coder", "tech-lead", "tester", "pmo", "researcher"])
    def test_all_roles_require_prompt_pattern(self, role):
        """全ticket-tasukiロールにpromptパターン制限が適用される"""
        data = _make_agent_input(
            subagent_type=role,
            team_name="my-team",
            prompt="issue_8132 do work",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    @pytest.mark.parametrize("role", ["coder", "tech-lead", "tester", "pmo", "researcher"])
    def test_all_roles_allow_valid_prompt(self, role):
        """全ロールで正しいpromptパターンならoverride注入付き許可"""
        data = _make_agent_input(
            subagent_type=role,
            team_name="my-team",
            prompt="issue_8132",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_8132")


class TestOverrideInjection:
    """override注入（updatedInput）のテスト（issue_8133）"""

    def test_override_output_structure(self):
        """override出力がupdatedInput構造を持つことを検証"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        hook_out = out["hookSpecificOutput"]
        assert hook_out["hookEventName"] == "PreToolUse"
        assert hook_out["permissionDecision"] == "allow"
        assert "updatedInput" in hook_out
        assert "prompt" in hook_out["updatedInput"]

    def test_override_prompt_contains_original(self):
        """注入後のpromptが元のpromptを含むことを検証"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_5678",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        updated_prompt = out["hookSpecificOutput"]["updatedInput"]["prompt"]
        assert updated_prompt.startswith("issue_5678\n\n")

    def test_override_prompt_contains_instruction(self):
        """注入後のpromptにRedmine読み込み指示が含まれることを検証"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_9999",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        updated_prompt = out["hookSpecificOutput"]["updatedInput"]["prompt"]
        # デフォルトまたはconfig設定のoverride指示が含まれること
        assert "Redmine" in updated_prompt or "get_issue_detail_tool" in updated_prompt

    def test_builtin_no_override(self):
        """ビルトインsubagent_typeにはoverride注入されない"""
        data = _make_agent_input(
            subagent_type="Explore",
            team_name="my-team",
            prompt="issue_1234 explore something",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        # ビルトインは直接許可（updatedInputなし）
        assert out is None

    def test_override_not_applied_on_deny(self):
        """deny時にはoverride注入されない"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="free text prompt",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "updatedInput" not in out["hookSpecificOutput"]


class TestConfigYamlMessages:
    """config.yamlからのブロックメッセージ読み込みテスト（issue_8137）"""

    def test_block_message_from_config(self):
        """config.yamlのblock_message_templateが使用される"""
        data = _make_agent_input(subagent_type="coder", prompt="issue_1234")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "sub-agent直接起動の制限" in reason
        assert 'subagent_type="coder"' in reason

    def test_prompt_pattern_block_message_from_config(self):
        """config.yamlのprompt_pattern_block_messageが使用される"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="invalid prompt",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "promptパターン制限" in reason
        assert '"invalid prompt"' in reason

    def test_issue_id_warn_message_from_config(self):
        """config.yamlのissue_id_warn_messageが使用される"""
        data = _make_agent_input(subagent_type="Explore", prompt="no issue id")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "issue_{id}" in reason

    def test_fallback_default_messages(self):
        """デフォルトメッセージの内容が正しく出力される"""
        data = _make_agent_input(subagent_type="unknown-role", prompt="issue_999")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "sub-agent直接起動の制限" in reason
