"""task_spawn_guard.py のテスト

ticket-tasuki プラグインの PreToolUse hook スクリプトを
subprocess経由で呼び出し、ブロック・許可の動作を検証する。
"""

import json
import os
import subprocess
import sys

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


class TestTicketTasukiBlocking:
    """ticket-tasuki:* 直接起動ブロック（既存機能）"""

    def test_block_ticket_tasuki_direct(self):
        """ticket-tasuki:coder を team_name なしで呼ぶとブロック"""
        data = _make_task_input(subagent_type="ticket-tasuki:coder")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_block_ticket_tasuki_scribe(self):
        """ticket-tasuki:scribe も同様にブロック"""
        data = _make_task_input(subagent_type="ticket-tasuki:scribe")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_allow_ticket_tasuki_with_team_name(self):
        """team_name 指定ありなら許可"""
        data = _make_task_input(
            subagent_type="ticket-tasuki:coder",
            team_name="my-team",
            prompt="issue_1234: 実装タスク",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # issue_id付きなので完全許可

    def test_block_message_contains_info(self):
        """ブロックメッセージに必要な情報が含まれる"""
        data = _make_task_input(subagent_type="ticket-tasuki:coder")
        rc, out = _run_guard(data)

        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "ticket-tasuki:coder" in reason
        assert "Agent Teams" in reason
        assert "迂回禁止" in reason
        assert "general-purpose" in reason

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


class TestTeamNameRequirement:
    """team_name未指定のTask spawnブロック（新機能）"""

    def test_block_general_purpose_without_team_name(self):
        """general-purpose を team_name なしで起動するとブロック"""
        data = _make_task_input(subagent_type="general-purpose")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "team_name" in out["hookSpecificOutput"]["permissionDecisionReason"]

    def test_block_coder_without_team_name(self):
        """非ホワイトリストの coder を team_name なしで起動するとブロック"""
        data = _make_task_input(subagent_type="coder")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_block_empty_subagent_type_without_team_name(self):
        """subagent_type未指定 + team_name未指定でブロック"""
        data = _make_task_input(subagent_type="")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_allow_general_purpose_with_team_name(self):
        """general-purpose でも team_name 指定ありなら許可"""
        data = _make_task_input(
            subagent_type="general-purpose",
            team_name="my-team",
            prompt="issue_1234: 調査タスク",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_block_message_contains_alternatives(self):
        """ブロックメッセージに代替手段が含まれる"""
        data = _make_task_input(subagent_type="general-purpose")
        rc, out = _run_guard(data)

        reason = out["hookSpecificOutput"]["permissionDecisionReason"]
        assert "SendMessage" in reason
        assert "Explore" in reason
        assert "Plan" in reason

    def test_block_unknown_subagent_type(self):
        """未知のsubagent_typeもteam_nameなしではブロック"""
        data = _make_task_input(subagent_type="my-custom-agent")
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestTeamExemptTypes:
    """ビルトイン軽量エージェントのホワイトリスト"""

    @pytest.mark.parametrize("agent_type", ["Explore", "Plan"])
    def test_allow_exempt_types_without_team_name(self, agent_type):
        """ホワイトリスト対象はteam_name不要で許可"""
        data = _make_task_input(
            subagent_type=agent_type,
            prompt="issue_1234: テスト",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None  # 完全許可

    def test_allow_explore_without_issue_id(self):
        """Exploreはissue_id無しでもブロックはされない（ユーザー確認要求）"""
        data = _make_task_input(
            subagent_type="Explore",
            prompt="コードベースを調べてください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        # issue_id欠落時はユーザー確認を要求する
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_allow_statusline_setup(self):
        """statusline-setupは許可"""
        data = _make_task_input(
            subagent_type="statusline-setup",
            prompt="issue_1234: ステータスライン設定",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_allow_claude_code_guide(self):
        """claude-code-guideは許可"""
        data = _make_task_input(
            subagent_type="claude-code-guide",
            prompt="issue_1234: Claude Code の使い方",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_case_sensitive_whitelist(self):
        """ホワイトリストは大文字小文字を区別する"""
        data = _make_task_input(subagent_type="explore")  # 小文字
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestIssueIdCheck:
    """promptにissue_{id}が含まれるかのトレーサビリティチェック"""

    def test_no_warning_with_issue_id(self):
        """issue_{id}がpromptに含まれていれば警告なし（ホワイトリスト型）"""
        data = _make_task_input(
            subagent_type="Explore",
            prompt="issue_6218: コードベースを調査する",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_warning_without_issue_id(self):
        """issue_{id}がpromptに含まれていなければユーザー確認要求（ホワイトリスト型）"""
        data = _make_task_input(
            subagent_type="Explore",
            prompt="コードベースを調べてください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        hook_output = out["hookSpecificOutput"]
        assert "issue_{id}" in hook_output["permissionDecisionReason"]
        # ユーザー確認を要求する
        assert hook_output["permissionDecision"] == "ask"

    def test_ticket_tasuki_deny_takes_priority(self):
        """ticket-tasuki直接起動のdeny判定はissue_id警告より優先"""
        data = _make_task_input(
            subagent_type="ticket-tasuki:coder",
            prompt="テスト実装",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_team_name_with_issue_id_no_output(self):
        """team_name指定ありかつissue_id含むなら完全許可"""
        data = _make_task_input(
            subagent_type="ticket-tasuki:coder",
            team_name="my-team",
            prompt="issue_6218: 実装タスク",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None

    def test_non_whitelisted_deny_takes_priority_over_issue_id_warn(self):
        """非ホワイトリストのdeny判定はissue_id警告より優先"""
        data = _make_task_input(
            subagent_type="general-purpose",
            prompt="コードベースを調べてください",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_issue_id_various_formats(self):
        """各種issue_{id}フォーマットを正しく検出"""
        test_cases = [
            ("issue_1", True),
            ("issue_12345", True),
            ("issue_0", True),
            ("prefix issue_999 suffix", True),
            ("issue_", False),  # 数字なし
            ("issue_abc", False),  # 数字でない
            ("ISSUE_123", False),  # 大文字
        ]
        for prompt, should_have_id in test_cases:
            data = _make_task_input(subagent_type="Explore", prompt=prompt)
            rc, out = _run_guard(data)
            assert rc == 0, f"Failed for prompt: {prompt}"
            if should_have_id:
                assert out is None, f"Expected no warn for prompt: {prompt}"
            else:
                assert out is not None, f"Expected warn for prompt: {prompt}"


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

    def test_non_whitelisted_without_session_id_still_blocked(self):
        """session_idがなくても非ホワイトリストはブロックされる"""
        data = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Task",
            "tool_input": {
                "subagent_type": "general-purpose",
                "prompt": "テスト",
            },
        }
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"

    def test_whitespace_only_team_name_treated_as_empty(self):
        """team_name=" "（空白文字のみ）はstrip()で空扱い→deny"""
        data = _make_task_input(
            subagent_type="general-purpose",
            team_name=" ",
            prompt="issue_1234: テスト",
        )
        # _make_task_inputはteam_name truthyなのでtool_inputに含まれる
        # しかしguard側で team_name.strip() が空→team_name無し扱い
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "deny"


class TestConfigPatternOverride:
    """正規表現パターンのconfig.yaml化テスト（issue_8512）

    task_spawn_guard.pyのISSUE_ID_PATTERNをconfig.yamlで上書き可能であることを検証する。
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
            }
        }
        config_file = config_dir / "config.yaml"
        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(custom_config, f, allow_unicode=True)

        shutil.copy2(GUARD_SCRIPT, hooks_dir / "task_spawn_guard.py")
        return hooks_dir / "task_spawn_guard.py"

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
        data = _make_task_input(subagent_type="Explore", prompt="ticket-1234 調査")
        rc, out = self._run_custom_guard(custom_pattern_config_dir, data)

        assert rc == 0
        assert out is None

    def test_custom_issue_id_pattern_old_format_warns(self, custom_pattern_config_dir):
        """カスタムパターン環境で旧issue_{id}形式はask警告"""
        data = _make_task_input(subagent_type="Explore", prompt="issue_1234 調査")
        rc, out = self._run_custom_guard(custom_pattern_config_dir, data)

        assert rc == 0
        assert out is not None
        assert out["hookSpecificOutput"]["permissionDecision"] == "ask"

    def test_default_pattern_fallback(self):
        """デフォルトパターンでissue_{id}形式が検出される"""
        data = _make_task_input(
            subagent_type="Explore",
            prompt="issue_1234 調査",
        )
        rc, out = _run_guard(data)

        assert rc == 0
        assert out is None


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

            shutil.copy2(GUARD_SCRIPT, hooks_dir / "task_spawn_guard.py")
            return hooks_dir / "task_spawn_guard.py"

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

    def test_invalid_issue_id_pattern_fallback(self, _make_config_dir):
        """不正なissue_id_patternでデフォルトにフォールバック"""
        script = _make_config_dir({
            "agent_spawn_guard": {"issue_id_pattern": "[invalid(regex"}
        })
        data = _make_task_input(subagent_type="Explore", prompt="issue_1234 調査")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None  # デフォルトパターンで検出成功、警告なし

    def test_invalid_pattern_does_not_crash(self, _make_config_dir):
        """不正パターンでプロセスがクラッシュしない"""
        script = _make_config_dir({
            "agent_spawn_guard": {"issue_id_pattern": "(?P<broken"}
        })
        data = _make_task_input(subagent_type="Explore", prompt="issue_999 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_empty_pattern_uses_default(self, _make_config_dir):
        """空文字パターンはデフォルトにフォールバック"""
        script = _make_config_dir({
            "agent_spawn_guard": {"issue_id_pattern": ""}
        })
        data = _make_task_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_none_pattern_uses_default(self, _make_config_dir):
        """Noneパターンはデフォルトにフォールバック"""
        script = _make_config_dir({
            "agent_spawn_guard": {"issue_id_pattern": None}
        })
        data = _make_task_input(subagent_type="Explore", prompt="issue_5678 test")
        rc, out = self._run_custom_guard(script, data)

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

            shutil.copy2(GUARD_SCRIPT, hooks_dir / "task_spawn_guard.py")
            return hooks_dir / "task_spawn_guard.py"

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
        data = _make_task_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_missing_section_fallback(self, _make_raw_config_dir):
        """agent_spawn_guardセクション欠損時にデフォルトパターンで動作"""
        script = _make_raw_config_dir("other_section:\n  key: value\n")
        data = _make_task_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_non_dict_config_fallback(self, _make_raw_config_dir):
        """config.yamlがdict以外（リスト等）の場合にデフォルトで動作"""
        script = _make_raw_config_dir("- item1\n- item2\n")
        data = _make_task_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None

    def test_pattern_type_error_fallback(self, _make_raw_config_dir):
        """パターンが文字列以外（数値等）の場合にデフォルトで動作"""
        script = _make_raw_config_dir("agent_spawn_guard:\n  issue_id_pattern: 12345\n")
        data = _make_task_input(subagent_type="Explore", prompt="issue_1234 test")
        rc, out = self._run_custom_guard(script, data)

        assert rc == 0
        assert out is None or out["hookSpecificOutput"]["permissionDecision"] == "ask"
