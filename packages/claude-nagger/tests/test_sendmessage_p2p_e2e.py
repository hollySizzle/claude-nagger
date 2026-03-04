"""SendMessage P2P通信制御 E2Eテスト（issue_7157）

P2P許可マトリクスの全role×recipient組み合わせを検証。
SendMessageGuardHook.process()経由で、_validate_p2p()のallow/denyを確認する。

P2Pマトリクス:
| caller      | 許可recipient              | broadcast |
|-------------|---------------------------|-----------|
| leader      | 全員                       | 許可      |
| pmo         | team-lead                  | 禁止      |
| tech-lead   | team-lead, tester, coder   | 禁止      |
| coder       | team-lead, tester, tech-lead| 禁止      |
| tester      | team-lead, coder, tech-lead| 禁止      |
| researcher  | team-lead                  | 禁止      |
"""

import pytest
from unittest.mock import patch, MagicMock

from src.domain.hooks.sendmessage_guard_hook import SendMessageGuardHook


# --- P2P設定 ---
P2P_CONFIG = {
    "enabled": True,
    "default_policy": "deny",
    "broadcast_allowed_roles": ["leader"],
    "matrix": {
        "pmo": ["team-lead"],
        "tech-lead": ["team-lead", "tester", "coder"],
        "coder": ["team-lead", "tester", "tech-lead"],
        "tester": ["team-lead", "coder", "tech-lead"],
        "researcher": ["team-lead"],
    },
}


# --- ヘルパー ---

def _make_hook(p2p_config=None):
    """P2P設定付きhookインスタンス生成"""
    guard_config = {"p2p_rules": p2p_config or P2P_CONFIG}
    with patch(
        "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
    ) as mock_cm:
        mock_cm.return_value.config = {"sendmessage_guard": guard_config}
        h = SendMessageGuardHook(debug=False)
    return h


def _make_input(msg_type, recipient="", content="issue_7157 [完了]"):
    """テスト用input_data生成"""
    tool_input = {"type": msg_type, "content": content}
    if recipient:
        tool_input["recipient"] = recipient
    return {
        "tool_name": "SendMessage",
        "tool_input": tool_input,
        "session_id": "test-p2p-e2e",
        "tool_use_id": "toolu_P2P_001",
    }


def _mock_roles(roles_set):
    """get_caller_roles()をモックするコンテキストマネージャ"""
    return patch(
        "src.domain.hooks.sendmessage_guard_hook.get_caller_roles",
        return_value=roles_set,
    )


def _assert_p2p_block(result):
    """P2P deny判定アサート: decision=block + skip_warn_only=True + P2P制御"""
    assert result["decision"] == "block", f"Expected block but got {result['decision']}"
    assert result.get("skip_warn_only") is True, "P2P blockはskip_warn_only=True必須"
    assert "P2P制御" in result["reason"], f"P2P制御が理由に含まれない: {result['reason']}"


def _assert_approve(result):
    """approve判定アサート"""
    assert result["decision"] == "approve", \
        f"Expected approve but got {result['decision']}: {result.get('reason', '')}"


# ============================================================
# P2P deny検証: 各roleから許可外recipientへの通信がdenyされる
# ============================================================

class TestP2PDeny:
    """許可外recipientへのmessage → deny"""

    @pytest.fixture
    def hook(self):
        return _make_hook()

    # --- pmo: team-lead以外deny ---
    def test_pmo_to_coder_deny(self, hook):
        """pmo → coder: deny"""
        input_data = _make_input("message", "coder")
        with _mock_roles({"pmo"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_pmo_to_tester_deny(self, hook):
        """pmo → tester: deny"""
        input_data = _make_input("message", "tester")
        with _mock_roles({"pmo"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_pmo_to_tech_lead_deny(self, hook):
        """pmo → tech-lead: deny"""
        input_data = _make_input("message", "tech-lead")
        with _mock_roles({"pmo"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_pmo_to_researcher_deny(self, hook):
        """pmo → researcher: deny"""
        input_data = _make_input("message", "researcher")
        with _mock_roles({"pmo"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    # --- tech-lead: team-lead, tester, coder以外deny ---
    def test_tech_lead_to_pmo_deny(self, hook):
        """tech-lead → pmo: deny"""
        input_data = _make_input("message", "pmo")
        with _mock_roles({"tech-lead"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_tech_lead_to_researcher_deny(self, hook):
        """tech-lead → researcher: deny"""
        input_data = _make_input("message", "researcher")
        with _mock_roles({"tech-lead"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    # --- coder: team-lead, tester, tech-lead以外deny ---
    def test_coder_to_pmo_deny(self, hook):
        """coder → pmo: deny"""
        input_data = _make_input("message", "pmo")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_coder_to_researcher_deny(self, hook):
        """coder → researcher: deny"""
        input_data = _make_input("message", "researcher")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    # --- tester: team-lead, coder, tech-lead以外deny ---
    def test_tester_to_pmo_deny(self, hook):
        """tester → pmo: deny"""
        input_data = _make_input("message", "pmo")
        with _mock_roles({"tester"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_tester_to_researcher_deny(self, hook):
        """tester → researcher: deny"""
        input_data = _make_input("message", "researcher")
        with _mock_roles({"tester"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    # --- researcher: team-lead以外deny ---
    def test_researcher_to_coder_deny(self, hook):
        """researcher → coder: deny"""
        input_data = _make_input("message", "coder")
        with _mock_roles({"researcher"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_researcher_to_tester_deny(self, hook):
        """researcher → tester: deny"""
        input_data = _make_input("message", "tester")
        with _mock_roles({"researcher"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_researcher_to_pmo_deny(self, hook):
        """researcher → pmo: deny"""
        input_data = _make_input("message", "pmo")
        with _mock_roles({"researcher"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)

    def test_researcher_to_tech_lead_deny(self, hook):
        """researcher → tech-lead: deny"""
        input_data = _make_input("message", "tech-lead")
        with _mock_roles({"researcher"}):
            result = hook.process(input_data)
        _assert_p2p_block(result)


# ============================================================
# P2P allow検証: 各roleから許可recipientへの通信がapproveされる
# ============================================================

class TestP2PAllow:
    """許可recipientへのmessage → approve"""

    @pytest.fixture
    def hook(self):
        return _make_hook()

    # --- 全role → team-lead: allow ---
    def test_pmo_to_team_lead_allow(self, hook):
        """pmo → team-lead: allow"""
        input_data = _make_input("message", "team-lead")
        with _mock_roles({"pmo"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_tech_lead_to_team_lead_allow(self, hook):
        """tech-lead → team-lead: allow"""
        input_data = _make_input("message", "team-lead")
        with _mock_roles({"tech-lead"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_coder_to_team_lead_allow(self, hook):
        """coder → team-lead: allow"""
        input_data = _make_input("message", "team-lead")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_tester_to_team_lead_allow(self, hook):
        """tester → team-lead: allow"""
        input_data = _make_input("message", "team-lead")
        with _mock_roles({"tester"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_researcher_to_team_lead_allow(self, hook):
        """researcher → team-lead: allow"""
        input_data = _make_input("message", "team-lead")
        with _mock_roles({"researcher"}):
            result = hook.process(input_data)
        _assert_approve(result)

    # --- role固有許可 ---
    def test_tech_lead_to_tester_allow(self, hook):
        """tech-lead → tester: allow"""
        input_data = _make_input("message", "tester")
        with _mock_roles({"tech-lead"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_coder_to_tester_allow(self, hook):
        """coder → tester: allow"""
        input_data = _make_input("message", "tester")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_tech_lead_to_coder_allow(self, hook):
        """tech-lead → coder: allow（#7169追加）"""
        input_data = _make_input("message", "coder")
        with _mock_roles({"tech-lead"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_coder_to_tech_lead_allow(self, hook):
        """coder → tech-lead: allow（#7169追加）"""
        input_data = _make_input("message", "tech-lead")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_tester_to_coder_allow(self, hook):
        """tester → coder: allow"""
        input_data = _make_input("message", "coder")
        with _mock_roles({"tester"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_tester_to_tech_lead_allow(self, hook):
        """tester → tech-lead: allow"""
        input_data = _make_input("message", "tech-lead")
        with _mock_roles({"tester"}):
            result = hook.process(input_data)
        _assert_approve(result)


# ============================================================
# leader全許可検証
# ============================================================

class TestLeaderFullAccess:
    """leader → 全recipient + broadcast: approve"""

    @pytest.fixture
    def hook(self):
        return _make_hook()

    @pytest.mark.parametrize("recipient", [
        "team-lead", "pmo", "tech-lead", "coder", "tester", "researcher",
    ])
    def test_leader_to_any_recipient_allow(self, hook, recipient):
        """leader → 任意recipient: allow"""
        input_data = _make_input("message", recipient)
        with _mock_roles({"leader"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_leader_broadcast_allow(self, hook):
        """leader broadcast: allow"""
        input_data = _make_input("broadcast")
        with _mock_roles({"leader"}):
            result = hook.process(input_data)
        _assert_approve(result)


# ============================================================
# broadcast制御検証
# ============================================================

class TestBroadcastControl:
    """broadcast: leader以外deny"""

    @pytest.fixture
    def hook(self):
        return _make_hook()

    @pytest.mark.parametrize("role", [
        "pmo", "tech-lead", "coder", "tester", "researcher",
    ])
    def test_non_leader_broadcast_deny(self, hook, role):
        """leader以外のbroadcast → deny"""
        input_data = _make_input("broadcast")
        with _mock_roles({role}):
            result = hook.process(input_data)
        _assert_p2p_block(result)
        assert "broadcast禁止" in result["reason"]


# ============================================================
# exempt_types検証: shutdown系はP2P制約を受けない
# ============================================================

class TestExemptTypes:
    """exempt_types（shutdown系）→ P2P制約スキップ"""

    @pytest.fixture
    def hook(self):
        return _make_hook()

    @pytest.mark.parametrize("exempt_type", [
        "shutdown_request",
        "shutdown_response",
        "plan_approval_response",
    ])
    @pytest.mark.parametrize("role", ["pmo", "coder", "tester"])
    def test_exempt_type_bypasses_p2p(self, hook, exempt_type, role):
        """exempt_typeはshould_processでFalse → processに到達しない（allow扱い）"""
        input_data = _make_input(exempt_type, "researcher")
        with _mock_roles({role}):
            # should_processでFalseなのでprocessは呼ばれない
            assert hook.should_process(input_data) is False


# ============================================================
# role不明時のフォールバック
# ============================================================

class TestUnknownRoleFallback:
    """role不明 → allow（安全側フォールバック）"""

    @pytest.fixture
    def hook(self):
        return _make_hook()

    def test_empty_roles_allow_message(self, hook):
        """roles空set → message allow"""
        input_data = _make_input("message", "coder")
        with _mock_roles(set()):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_empty_roles_allow_broadcast(self, hook):
        """roles空set → broadcast allow"""
        input_data = _make_input("broadcast")
        with _mock_roles(set()):
            result = hook.process(input_data)
        _assert_approve(result)


# ============================================================
# config無効時: p2p_rules.enabled=False → 全通過
# ============================================================

class TestP2PDisabled:
    """P2P無効時は全通過"""

    @pytest.fixture
    def hook(self):
        return _make_hook({"enabled": False})

    def test_disabled_allows_any_message(self, hook):
        """P2P無効: 許可外recipient → approve（P2Pスキップ、content検証のみ）"""
        input_data = _make_input("message", "researcher")
        with _mock_roles({"pmo"}):
            result = hook.process(input_data)
        _assert_approve(result)

    def test_disabled_allows_broadcast(self, hook):
        """P2P無効: 非leader broadcast → approve"""
        input_data = _make_input("broadcast")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        _assert_approve(result)


# ============================================================
# default_policy検証
# ============================================================

class TestDefaultPolicy:
    """default_policy: matrixに存在しないroleの挙動"""

    def test_deny_policy_unknown_role_deny(self):
        """default_policy=deny: matrixに無いrole → deny"""
        hook = _make_hook(P2P_CONFIG)
        input_data = _make_input("message", "team-lead")
        with _mock_roles({"unknown_role"}):
            result = hook.process(input_data)
        # unknown_roleはmatrixに無い → default_policy=deny → block
        _assert_p2p_block(result)

    def test_allow_policy_unknown_role_allow(self):
        """default_policy=allow: matrixに無いrole → allow"""
        config = {**P2P_CONFIG, "default_policy": "allow"}
        hook = _make_hook(config)
        input_data = _make_input("message", "anyone")
        with _mock_roles({"unknown_role"}):
            result = hook.process(input_data)
        _assert_approve(result)


# ============================================================
# 既存機能回帰テスト: P2P有効でもcontent検証は動作する
# ============================================================

class TestContentValidationRegression:
    """P2P有効時でもcontent検証（issue_id・文字数）は正常動作"""

    @pytest.fixture
    def hook(self):
        """enum指定パターンでcontent検証を有効化"""
        guard_config = {
            "p2p_rules": P2P_CONFIG,
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$",
        }
        with patch(
            "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
        ) as mock_cm:
            mock_cm.return_value.config = {"sendmessage_guard": guard_config}
            h = SendMessageGuardHook(debug=False)
        return h

    def test_missing_issue_id_still_blocked(self, hook):
        """issue_id無しcontent → block（P2P通過後のcontent検証）"""
        input_data = _make_input("message", "team-lead", content="完了しました")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "フォーマット不一致" in result["reason"]

    def test_invalid_format_still_blocked(self, hook):
        """フォーマット不正（ブラケットなし） → block"""
        input_data = _make_input("message", "team-lead", content="issue_7157 完了しました")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        assert result["decision"] == "block"
        assert "フォーマット不一致" in result["reason"]

    def test_valid_content_approve(self, hook):
        """正常content → approve"""
        input_data = _make_input("message", "team-lead", content="issue_7157 [完了]")
        with _mock_roles({"coder"}):
            result = hook.process(input_data)
        _assert_approve(result)


# ============================================================
# skip_warn_only検証: P2P blockはWARN_ONLYで迂回されない
# ============================================================

class TestSkipWarnOnly:
    """P2P block時のskip_warn_only=True検証"""

    @pytest.fixture
    def hook(self):
        return _make_hook()

    @pytest.fixture
    def hook_with_pattern(self):
        """enum指定パターンでcontent検証を有効化"""
        guard_config = {
            "p2p_rules": P2P_CONFIG,
            "pattern": r"^issue_\d+ \[(完了|指示|相談|確認|要判断|ブロッカー)\]$",
        }
        with patch(
            "src.domain.hooks.sendmessage_guard_hook.ConfigManager"
        ) as mock_cm:
            mock_cm.return_value.config = {"sendmessage_guard": guard_config}
            h = SendMessageGuardHook(debug=False)
        return h

    def test_p2p_block_has_skip_warn_only(self, hook):
        """P2P deny → skip_warn_only=True"""
        input_data = _make_input("message", "researcher")
        with _mock_roles({"pmo"}):
            result = hook.process(input_data)
        assert result["decision"] == "block"
        assert result.get("skip_warn_only") is True

    def test_content_block_no_skip_warn_only(self, hook_with_pattern):
        """content検証block → skip_warn_only未設定"""
        input_data = _make_input("message", "team-lead", content="no issue id")
        with _mock_roles({"coder"}):
            result = hook_with_pattern.process(input_data)
        assert result["decision"] == "block"
        assert result.get("skip_warn_only") is not True
