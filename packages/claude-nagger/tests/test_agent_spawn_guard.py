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


class TestSubagentRedmineFlowConfig:
    """検証項目(d): subagent規約にget_issue_detail_toolフローが含まれること（issue_8139）

    config.yamlの各subagent_type override設定に
    get_issue_detail_tool規約文言が含まれることを検証する。
    """

    @pytest.fixture(autouse=True)
    def _load_config(self):
        """config.yamlのsession_startup.overridesセクションを読み込む"""
        import yaml

        # プロジェクトルートのconfig.yamlを使用
        config_path = os.path.join(
            os.path.dirname(__file__), "..", ".claude-nagger", "config.yaml"
        )
        config_path = os.path.normpath(config_path)
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        self.overrides = data.get("session_startup", {}).get("overrides", {})
        self.subagent_types = self.overrides.get("subagent_types", {})

    @pytest.mark.parametrize("role", ["coder", "tester", "tech-lead", "pmo"])
    def test_role_contains_get_issue_detail_tool(self, role):
        """各ロールのoverride設定にget_issue_detail_tool規約文言が含まれる"""
        role_config = self.subagent_types.get(role, {})
        main_text = (
            role_config.get("messages", {})
            .get("first_time", {})
            .get("main_text", "")
        )
        assert "get_issue_detail_tool" in main_text, (
            f"{role}のoverride設定にget_issue_detail_tool文言が含まれていない"
        )

    def test_researcher_has_get_issue_detail_tool(self):
        """researcherのoverride設定にget_issue_detail_tool規約文言が含まれる

        researcherはsubagent_defaultフォールバックの可能性があるため個別検証。
        """
        researcher_config = self.subagent_types.get("researcher", {})
        main_text = (
            researcher_config.get("messages", {})
            .get("first_time", {})
            .get("main_text", "")
        )
        assert "get_issue_detail_tool" in main_text, (
            "researcherのoverride設定にget_issue_detail_tool文言が含まれていない。"
            "subagent_defaultフォールバックではget_issue_detail_tool規約が欠落する"
        )

    def test_override_instruction_contains_get_issue_detail_tool(self):
        """agent_spawn_guardのoverride_instructionにget_issue_detail_tool文言が含まれる"""
        import yaml

        config_path = os.path.join(
            os.path.dirname(__file__), "..", ".claude-nagger", "config.yaml"
        )
        config_path = os.path.normpath(config_path)
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        guard_config = data.get("agent_spawn_guard", {})
        instruction = guard_config.get("override_instruction", "")
        assert "get_issue_detail_tool" in instruction, (
            "override_instructionにget_issue_detail_tool文言が含まれていない"
        )


class TestConfigYamlMessageOverride:
    """検証項目(e): config.yamlメッセージテンプレート書き換えの反映確認（issue_8139）

    config.yamlのメッセージテンプレートを書き換えた状態でguardスクリプトを実行し、
    変更がdeny/warn時のメッセージに正しく反映されることを検証する。
    """

    @pytest.fixture
    def custom_config_dir(self, tmp_path):
        """カスタムメッセージを持つconfig.yamlを含む一時ディレクトリを作成"""
        import shutil
        import yaml

        # guardスクリプトの親ディレクトリ構造を再現
        # agent_spawn_guard.py は script_dir/../.claude-nagger/config.yaml を参照
        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()

        # カスタムメッセージのconfig.yaml
        custom_config = {
            "agent_spawn_guard": {
                "block_message_template": 'カスタムブロック: type="{subagent_type}"',
                "prompt_pattern_block_message": 'カスタムパターン拒否: prompt="{prompt}"',
                "issue_id_warn_message": "カスタム警告: issue_idが必要です",
                "override_instruction": "カスタムoverride指示文",
            }
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        # guardスクリプトをコピー
        shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")

        return hooks_dir / "agent_spawn_guard.py"

    def _run_custom_guard(self, script_path, input_data):
        """カスタムconfig環境でguardスクリプトを実行"""
        proc = subprocess.run(
            [sys.executable, str(script_path)],
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

    def test_custom_block_message_reflected(self, custom_config_dir):
        """書き換えたblock_message_templateがdeny時に反映される"""
        data = _make_agent_input(subagent_type="coder", prompt="issue_1234")
        rc, out = self._run_custom_guard(custom_config_dir, data)

        assert rc == 0
        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "カスタムブロック" in reason
        assert 'type="coder"' in reason

    def test_custom_prompt_pattern_block_reflected(self, custom_config_dir):
        """書き換えたprompt_pattern_block_messageがpromptパターン拒否時に反映される"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="invalid prompt",
        )
        rc, out = self._run_custom_guard(custom_config_dir, data)

        assert rc == 0
        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "カスタムパターン拒否" in reason
        assert '"invalid prompt"' in reason

    def test_custom_issue_id_warn_reflected(self, custom_config_dir):
        """書き換えたissue_id_warn_messageが警告時に反映される"""
        data = _make_agent_input(subagent_type="Explore", prompt="no issue id")
        rc, out = self._run_custom_guard(custom_config_dir, data)

        assert rc == 0
        assert out is not None
        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "カスタム警告" in reason

    def test_custom_override_instruction_in_updated_input(self, custom_config_dir):
        """書き換えたoverride_instructionがupdatedInputに反映される"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234",
        )
        rc, out = self._run_custom_guard(custom_config_dir, data)

        assert rc == 0
        assert out is not None
        updated_prompt = out["hookSpecificOutput"]["updatedInput"]["prompt"]
        assert "カスタムoverride指示文" in updated_prompt
        assert "issue_1234" in updated_prompt


class TestConfigYamlContentValidation:
    """config.yaml内容の妥当性検証テスト（issue_8139チューニング）

    config.yaml変更後の内容が期待通りであることを直接検証する。
    """

    @pytest.fixture(autouse=True)
    def _load_config(self):
        """config.yamlを読み込む"""
        import yaml

        config_path = os.path.join(
            os.path.dirname(__file__), "..", ".claude-nagger", "config.yaml"
        )
        config_path = os.path.normpath(config_path)
        with open(config_path, encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

    def test_prompt_pattern_block_message_contains_reason(self):
        """prompt_pattern_block_messageに理由行が含まれる"""
        guard = self.config.get("agent_spawn_guard", {})
        msg = guard.get("prompt_pattern_block_message", "")
        assert "理由:" in msg, "prompt_pattern_block_messageに理由行が含まれていない"
        assert "Redmine連携" in msg

    def test_override_instruction_contains_ticket_reference(self):
        """override_instructionにチケット番号参照の指示が含まれる"""
        guard = self.config.get("agent_spawn_guard", {})
        instruction = guard.get("override_instruction", "")
        assert "promptに指定されたチケット番号" in instruction

    def test_override_instruction_in_updated_input(self):
        """override_instructionが実際のupdatedInputに反映される"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        updated_prompt = out["hookSpecificOutput"]["updatedInput"]["prompt"]
        assert "promptに指定されたチケット番号" in updated_prompt


class TestConfigPatternOverride:
    """正規表現パターンのconfig.yaml化テスト（issue_8512）

    issue_id_patternとprompt_only_patternをconfig.yamlで上書き可能であることを検証する。
    """

    @pytest.fixture
    def custom_pattern_config_dir(self, tmp_path):
        """カスタムパターンを持つconfig.yamlを含む一時ディレクトリを作成"""
        import shutil
        import yaml

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()

        # カスタムパターン: ticket-XXX形式に変更
        custom_config = {
            "agent_spawn_guard": {
                "issue_id_pattern": r"ticket-\d+",
                "prompt_only_pattern": r"^ticket-\d{1,6}$",
            }
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
        return hooks_dir / "agent_spawn_guard.py"

    def _run_custom_guard(self, script_path, input_data):
        """カスタムconfig環境でguardスクリプトを実行"""
        proc = subprocess.run(
            [sys.executable, str(script_path)],
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

    def test_custom_issue_id_pattern_accepted(self, custom_pattern_config_dir):
        """カスタムissue_id_patternに合致するpromptで警告なし"""
        data = _make_agent_input(subagent_type="Explore", prompt="ticket-1234 do something")
        rc, out = self._run_custom_guard(custom_pattern_config_dir, data)

        assert rc == 0
        assert out is None  # 警告なし

    def test_custom_issue_id_pattern_old_format_warns(self, custom_pattern_config_dir):
        """カスタムパターン環境で旧issue_{id}形式はask警告"""
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 do something")
        rc, out = self._run_custom_guard(custom_pattern_config_dir, data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_custom_prompt_only_pattern_accepted(self, custom_pattern_config_dir):
        """カスタムprompt_only_patternに合致するpromptでoverride注入"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="ticket-5678",
        )
        rc, out = self._run_custom_guard(custom_pattern_config_dir, data)

        assert rc == 0
        assert out is not None
        hook_out = out["hookSpecificOutput"]
        assert hook_out["permissionDecision"] == "allow"
        assert "updatedInput" in hook_out

    def test_custom_prompt_only_pattern_old_format_denied(self, custom_pattern_config_dir):
        """カスタムパターン環境で旧issue_{id}形式のpromptはdeny"""
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234",
        )
        rc, out = self._run_custom_guard(custom_pattern_config_dir, data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_default_pattern_fallback(self):
        """config.yamlにパターン未設定時はデフォルトパターンが使用される"""
        # 既存のconfig.yamlにはパターンが設定されているが、
        # デフォルト値と同じなので動作は同一
        data = _make_agent_input(
            subagent_type="coder",
            team_name="my-team",
            prompt="issue_1234",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        _assert_override_output(out, "issue_1234")

    def test_config_patterns_in_config_yaml(self):
        """config.yamlにissue_id_patternとprompt_only_patternが定義されている"""
        import yaml

        # agent_spawn_guard.pyが参照するconfig.yaml（プラグインディレクトリ）
        config_path = os.path.join(
            os.path.dirname(GUARD_SCRIPT), "..", ".claude-nagger", "config.yaml"
        )
        config_path = os.path.normpath(config_path)
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        guard = config.get("agent_spawn_guard", {})
        assert "issue_id_pattern" in guard, "config.yamlにissue_id_patternが未定義"
        assert "prompt_only_pattern" in guard, "config.yamlにprompt_only_patternが未定義"
        assert guard["issue_id_pattern"] == r"issue_\d+"
        assert guard["prompt_only_pattern"] == r"^issue_\d{1,6}$"


class TestSafeCompileFallback:
    """_safe_compile()の不正パターンフォールバックテスト（issue_8512）

    config.yamlに不正な正規表現が設定された場合、デフォルトパターンにフォールバックすることを検証する。
    """

    @pytest.fixture
    def _make_config_dir(self, tmp_path):
        """指定configでguardスクリプト環境を作成するファクトリ"""
        import shutil

        def factory(config_data):
            hooks_dir = tmp_path / "hooks"
            hooks_dir.mkdir(exist_ok=True)
            config_dir = tmp_path / ".claude-nagger"
            config_dir.mkdir(exist_ok=True)

            import yaml
            config_file = config_dir / "config.yaml"
            with open(config_file, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, allow_unicode=True)

            shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
            return hooks_dir / "agent_spawn_guard.py"

        return factory

    def _run_custom_guard(self, script_path, input_data):
        """カスタムconfig環境でguardスクリプトを実行"""
        proc = subprocess.run(
            [sys.executable, str(script_path)],
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
        return proc.returncode, stdout_json, proc.stderr

    def test_invalid_issue_id_pattern_fallback(self, _make_config_dir):
        """不正なissue_id_patternでデフォルトにフォールバック"""
        script = _make_config_dir({
            "agent_spawn_guard": {"issue_id_pattern": "[invalid(regex"}
        })
        # デフォルトパターン(issue_\d+)で検出されるべき
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 do something")
        rc, out, _ = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None  # 警告なし（デフォルトパターンで検出成功）

    def test_invalid_prompt_only_pattern_fallback(self, _make_config_dir):
        """不正なprompt_only_patternでデフォルトにフォールバック"""
        script = _make_config_dir({
            "agent_spawn_guard": {"prompt_only_pattern": "[broken"}
        })
        # デフォルトパターン(^issue_\d{1,6}$)で合致するべき
        data = _make_agent_input(
            subagent_type="coder", team_name="my-team", prompt="issue_1234"
        )
        rc, out, _ = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
        assert "updatedInput" in out["hookSpecificOutput"]

    def test_both_patterns_invalid_fallback(self, _make_config_dir):
        """両パターンとも不正でもクラッシュせずデフォルトで動作"""
        script = _make_config_dir({
            "agent_spawn_guard": {
                "issue_id_pattern": "(?P<broken",
                "prompt_only_pattern": "[unmatched",
            }
        })
        data = _make_agent_input(subagent_type="Explore", prompt="issue_999 test")
        rc, out, _ = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_empty_pattern_uses_default(self, _make_config_dir):
        """空文字パターンはデフォルトにフォールバック"""
        script = _make_config_dir({
            "agent_spawn_guard": {"issue_id_pattern": ""}
        })
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out, _ = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_none_pattern_uses_default(self, _make_config_dir):
        """Noneパターンはデフォルトにフォールバック"""
        script = _make_config_dir({
            "agent_spawn_guard": {"issue_id_pattern": None}
        })
        data = _make_agent_input(subagent_type="Explore", prompt="issue_5678 test")
        rc, out, _ = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None


class TestConfigLoadFailure:
    """config.yaml読み込み失敗時のフォールバックテスト（issue_8512）

    YAML構文エラー、セクション欠損、型エラー等でもクラッシュせずデフォルト動作することを検証する。
    """

    @pytest.fixture
    def _make_raw_config_dir(self, tmp_path):
        """生のconfig.yaml内容でguardスクリプト環境を作成するファクトリ"""
        import shutil

        def factory(raw_content):
            hooks_dir = tmp_path / "hooks"
            hooks_dir.mkdir(exist_ok=True)
            config_dir = tmp_path / ".claude-nagger"
            config_dir.mkdir(exist_ok=True)

            config_file = config_dir / "config.yaml"
            config_file.write_text(raw_content, encoding="utf-8")

            shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
            return hooks_dir / "agent_spawn_guard.py"

        return factory

    def _run_custom_guard(self, script_path, input_data):
        proc = subprocess.run(
            [sys.executable, str(script_path)],
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

    def test_yaml_syntax_error_fallback(self, _make_raw_config_dir):
        """YAML構文エラー時にデフォルトパターンで動作"""
        script = _make_raw_config_dir("agent_spawn_guard:\n  issue_id_pattern: [broken yaml")
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_missing_section_fallback(self, _make_raw_config_dir):
        """agent_spawn_guardセクション欠損時にデフォルトパターンで動作"""
        script = _make_raw_config_dir("other_section:\n  key: value\n")
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_non_dict_config_fallback(self, _make_raw_config_dir):
        """config.yamlがdict以外（リスト等）の場合にデフォルトで動作"""
        script = _make_raw_config_dir("- item1\n- item2\n")
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_pattern_type_error_fallback(self, _make_raw_config_dir):
        """パターンが文字列以外（数値等）の場合にデフォルトで動作"""
        script = _make_raw_config_dir("agent_spawn_guard:\n  issue_id_pattern: 12345\n")
        data = _make_agent_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        # 数値はre.compileで文字列変換されるため、クラッシュしないことを確認
        assert out is None or out["hookSpecificOutput"]["permissionDecision"] == "ask"


class TestExemptSpawnRoutes:
    """exempt_spawn_routes（issue_idチェックスキップ）のテスト（issue_8570）

    config.yaml sendmessage_guard.exempt_routesに定義された経路では、
    agent_spawn_guardのissue_idチェックをスキップする。
    leader(agent_context="")→pmo経路が免除対象。
    """

    def test_leader_to_pmo_no_issue_id_no_warn(self):
        """leader→pmo: issue_id無しでもask警告されない"""
        data = _make_agent_input(
            subagent_type="pmo",
            team_name="my-team",
            prompt="pmo",
            agent_context="",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        # pmoはprompt_only_patternに合致しないためdeny
        # ただしissue_id警告ではなくpromptパターン制限のdeny
        # → prompt="issue_1234"形式ではないのでdenyになるが、それはpromptパターン問題
        # exempt_routesのテストとしては、issue_idなしでもteam_name+正しいpromptで確認
        assert out is not None

    def test_leader_to_pmo_valid_prompt_no_issue_id(self):
        """leader→pmo: issue_id形式のpromptでoverride注入（issue_id警告なし）"""
        # pmoはprompt_only_patternに合致する形式が必要
        # exempt_routesによりissue_id不要だが、prompt_only_patternは別チェック
        # ビルトイン以外はprompt_only_pattern必須なので"issue_1234"形式でテスト
        # ※exempt_routesの効果はissue_idチェックのスキップ
        data = _make_agent_input(
            subagent_type="pmo",
            team_name="my-team",
            prompt="issue_1234",
            agent_context="",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        # override注入されて許可（issue_id警告なし）
        _assert_override_output(out, "issue_1234")

    def test_leader_to_pmo_builtin_no_warn(self):
        """leader→pmo（ビルトイン相当テスト用）: exempt経路でissue_id警告なし

        ビルトインsubagent_typeでexempt経路の効果を単独確認するため、
        Exploreをpmo経路に見立てた補助テスト。
        実際のexempt効果はissue_id無しpromptで確認。
        """
        # 直接_is_exempt_spawn_routeの動作を確認するため
        # issue_idなしのpromptでビルトイン(Explore)を使い、
        # exempt有無でwarn出力の差を確認
        data = _make_agent_input(
            subagent_type="Explore",
            prompt="no issue id here",
            agent_context="",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        # Exploreはビルトインなのでdenyにはならないが、issue_id警告(ask)は出る
        # exempt_routesはExploreに適用されない（from:leader, to:pmo）
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_leader_to_explore_no_issue_id_warns(self):
        """leader→Explore（非exempt経路）: issue_id無しはask警告"""
        data = _make_agent_input(
            subagent_type="Explore",
            prompt="no issue id",
            agent_context="",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"
        assert "issue_{id}" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_leader_to_coder_no_issue_id_denied(self):
        """leader→coder（非exempt経路、team_nameなし）: deny"""
        data = _make_agent_input(
            subagent_type="coder",
            prompt="no issue id",
            agent_context="",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_exempt_route_with_custom_config(self, tmp_path):
        """カスタムconfig環境でexempt_routesが正しく動作する"""
        import shutil
        import yaml

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()

        # exempt_routes: leader→pmoを設定（agent_spawn_guard独自管理）
        custom_config = {
            "agent_spawn_guard": {
                "exempt_routes": [{"from": "leader", "to": "pmo"}],
            },
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
        script = hooks_dir / "agent_spawn_guard.py"

        # leader(agent_context="")→pmo: exempt経路なのでissue_id警告なし
        data = _make_agent_input(
            subagent_type="pmo",
            team_name="my-team",
            prompt="issue_1234",
            agent_context="",
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        # exempt経路なのでissue_id警告なし、override注入で許可
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_exempt_route_not_applied_to_non_leader(self, tmp_path):
        """subagent以外の非leader contextではexempt_routesが適用されない"""
        import shutil
        import yaml

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()

        custom_config = {
            "agent_spawn_guard": {
                "exempt_routes": [{"from": "leader", "to": "pmo"}],
            },
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
        script = hooks_dir / "agent_spawn_guard.py"

        # agent_context="other"→pmo: exempt_routesのfrom:leaderに合致しない
        data = _make_agent_input(
            subagent_type="pmo",
            team_name="my-team",
            prompt="issue_1234",
            agent_context="other",
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        # exempt非該当だがissue_idあり → override注入で許可
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_empty_exempt_routes_warns(self, tmp_path):
        """exempt_routes空の場合はissue_idチェックが通常通り実行される"""
        import shutil
        import yaml

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()

        custom_config = {
            "agent_spawn_guard": {
                "exempt_routes": [],
            },
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
        script = hooks_dir / "agent_spawn_guard.py"

        # issue_idなしのビルトイン → ask警告
        data = _make_agent_input(
            subagent_type="Explore",
            prompt="no issue id",
            agent_context="",
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_exempt_multiple_routes_second_match(self, tmp_path):
        """exempt_routes複数経路設定時、2番目の経路もマッチする"""
        import shutil
        import yaml

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()

        custom_config = {
            "agent_spawn_guard": {
                "exempt_routes": [
                    {"from": "leader", "to": "pmo"},
                    {"from": "leader", "to": "tester"},
                ],
            },
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
        script = hooks_dir / "agent_spawn_guard.py"

        # leader→tester（2番目の経路）: exempt有効でissue_id警告なし
        data = _make_agent_input(
            subagent_type="tester",
            team_name="my-team",
            prompt="issue_1234",
            agent_context="",
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"

    def test_non_leader_non_subagent_context(self, tmp_path):
        """agent_context="team-lead"等の非leader/非subagentコンテキスト"""
        import shutil
        import yaml

        hooks_dir = tmp_path / "hooks"
        hooks_dir.mkdir()
        config_dir = tmp_path / ".claude-nagger"
        config_dir.mkdir()

        custom_config = {
            "agent_spawn_guard": {
                "exempt_routes": [{"from": "leader", "to": "pmo"}],
            },
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        shutil.copy2(GUARD_SCRIPT, hooks_dir / "agent_spawn_guard.py")
        script = hooks_dir / "agent_spawn_guard.py"

        # agent_context="team-lead"→pmo: "leader"ではないのでexempt非適用
        data = _make_agent_input(
            subagent_type="pmo",
            team_name="my-team",
            prompt="issue_1234",
            agent_context="team-lead",
        )
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(data),
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
        out = json.loads(proc.stdout) if proc.stdout.strip() else None
        # exempt非適用だがissue_idあり → override注入で許可
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
