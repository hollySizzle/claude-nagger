"""セッション開始時の規約確認フック"""

import copy
import json
import re
import sys
import os
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
sys.path.append(str(Path(__file__).parent.parent.parent))

from domain.hooks.base_hook import BaseHook
from infrastructure.db import NaggerStateDB, SubagentRepository, SessionRepository, SubagentHistoryRepository, SUBAGENT_TOOL_NAMES
from shared.constants import SUGGESTED_RULES_FILENAME, SUGGESTED_RULES_DIRNAME


def _deep_copy_dict(d: Dict[str, Any]) -> Dict[str, Any]:
    """辞書の深いコピー（ネスト・リスト対応）"""
    return copy.deepcopy(d)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    """overrideの値でbaseを深くマージ（in-place）

    ネストされた辞書は再帰的にマージし、それ以外は上書き。
    """
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _strip_numeric_suffix(name: str) -> str:
    """末尾の-数字サフィックスを除去してベースロール名を返す。
    例: 'tester-2' → 'tester', 'coder' → 'coder'
    """
    if not isinstance(name, str):
        return name
    return re.sub(r'-\d+$', '', name)



class SessionStartupHook(BaseHook):
    """セッション開始時のAI協働規約確認フック"""

    def __init__(self, *args, **kwargs):
        """初期化"""
        super().__init__(debug=True)
        self.config = self._load_config()
        # subagentコンテキスト（should_processで設定、processで参照）
        self._is_subagent = False
        self._resolved_config = None
        self._current_agent_id = None
        self._current_agent_type = None
        # DB関連（should_processで初期化、processで参照）
        self._db: Optional[NaggerStateDB] = None
        self._subagent_repo: Optional[SubagentRepository] = None
        self._session_repo: Optional[SessionRepository] = None
        
    def _load_config(self) -> Dict[str, Any]:
        """
        設定ファイルを読み込む
        
        優先順位:
        1. .claude-nagger/config.yaml (プロジェクト設定)
        2. rules/session_startup_settings.yaml (デフォルト設定)
        
        Returns:
            設定データの辞書
        """
        # CLAUDE_PROJECT_DIRを優先、フォールバックはcwd
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base_path = Path(project_dir) if project_dir else Path.cwd()
        project_config = base_path / ".claude-nagger" / "config.yaml"
        if project_config.exists():
            config_file = project_config
        else:
            # フォールバック: デフォルト設定
            config_file = Path(__file__).parent.parent.parent.parent / "rules" / "session_startup_settings.yaml"
        
        try:
            if config_file.exists():
                with open(config_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    self.log_info(f"✅ Loaded session startup config: {config_file}")
                    return data.get('session_startup', {})
            else:
                self.log_error(f"❌ Config file not found: {config_file}")
                return {}
        except Exception as e:
            self.log_error(f"❌ Failed to load config: {e}")
            return {}

    def should_skip_session(self, session_id: str, input_data: Dict[str, Any]) -> bool:
        """SessionStartupHookは独自のセッション管理機構(should_process内)を使用するため、
        BaseHookのセッション処理済みチェックを常にバイパスしてshould_processに委ねる。

        理由:
        - should_process()内にis_session_startup_processed()による独自の重複排除ロジックがある
        - subagentは親セッションと同一session_idを共有するため、BaseHookの判定では誤スキップが発生
        - SubagentStartはfire-and-forget(非同期)のため、マーカー依存の条件付きバイパスはレースコンディションを引き起こす
        """
        return False
        
    def _resolve_subagent_config(self, agent_type: str, role: Optional[str] = None) -> Dict[str, Any]:
        """subagent種別に応じたoverride設定を解決

        解決順序: base → subagent_default → subagent_types.{type}
        type解決順序: role完全一致 → role末尾-数字除去 → agent_type完全一致
                     → agent_type末尾-数字除去 → ":"区切り末尾 → 空dict

        Args:
            agent_type: サブエージェント種別
            role: サブエージェントのロール（優先マッチキー）

        Returns:
            解決済み設定辞書
        """
        overrides = self.config.get("overrides", {})
        subagent_default = overrides.get("subagent_default", {})
        subagent_types = overrides.get("subagent_types", {})
        # role完全一致 → role末尾-数字除去 → agent_type完全一致
        # → agent_type末尾-数字除去 → ":"区切り末尾 → 空dictフォールバック
        type_specific = None
        if role:
            type_specific = subagent_types.get(role)
            # role末尾-数字除去フォールバック（例: tester-2 → tester）
            if type_specific is None:
                base_role = _strip_numeric_suffix(role)
                if base_role != role:
                    type_specific = subagent_types.get(base_role)
        if type_specific is None:
            type_specific = subagent_types.get(agent_type)
        # agent_type末尾-数字除去フォールバック
        if type_specific is None:
            base_agent_type = _strip_numeric_suffix(agent_type)
            if base_agent_type != agent_type:
                type_specific = subagent_types.get(base_agent_type)
        if type_specific is None and ":" in agent_type:
            short_name = agent_type.rsplit(":", 1)[-1]
            type_specific = subagent_types.get(short_name, {})
        elif type_specific is None:
            type_specific = {}

        # base設定をコピー
        resolved = {
            "enabled": self.config.get("enabled", True),
            "messages": _deep_copy_dict(self.config.get("messages", {})),
            "behavior": _deep_copy_dict(self.config.get("behavior", {})),
        }

        # subagent_defaultで上書き
        _deep_merge(resolved, subagent_default)

        # subagent_types.{type}でさらに上書き
        _deep_merge(resolved, type_specific)

        self.log_info(f"🔧 Resolved subagent config for '{agent_type}': enabled={resolved.get('enabled')}")
        return resolved

    def _parse_role_from_transcript(self, transcript_path: str, parent_tool_use_id: Optional[str] = None) -> Optional[str]:
        """トランスクリプトJSONLからsubagentロールを抽出

        assistant内のsubagent tool_useブロックからinput.name（TeamCreate方式）
        またはinput.subagent_type（フォールバック）でロールを取得。

        parent_tool_use_id指定時は該当tool_useのみ対象。
        未指定または見つからない場合は最後のtool_use（従来動作）にフォールバック。

        Args:
            transcript_path: トランスクリプトJSONLファイルパス
            parent_tool_use_id: 特定subagentに対応するtool_useのID（任意）

        Returns:
            抽出されたロール文字列、未検出時はNone
        """
        if not transcript_path:
            return None

        try:
            path = Path(transcript_path)
            if not path.exists():
                self.log_debug(f"Transcript file not found: {transcript_path}")
                return None

            role_from_task = None
            role_by_id = None  # parent_tool_use_idで特定されたロール

            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue

                    entry_type = entry.get('type', '')

                    # assistant内のsubagent tool_useからロール抽出
                    if entry_type == 'assistant':
                        message = entry.get('message', {})
                        content = message.get('content', [])
                        if isinstance(content, list):
                            for block in content:
                                if (isinstance(block, dict)
                                    and block.get('type') == 'tool_use'
                                    and block.get('name') in SUBAGENT_TOOL_NAMES):
                                    input_data = block.get('input', {})
                                    block_id = block.get('id', '')

                                    # ロール抽出
                                    extracted_role = None
                                    if input_data.get('team_name') and input_data.get('name'):
                                        extracted_role = input_data.get('name')  # TeamCreate方式
                                    elif input_data.get('subagent_type'):
                                        extracted_role = input_data.get('subagent_type')  # フォールバック

                                    if extracted_role:
                                        # parent_tool_use_idで正確マッチ
                                        if parent_tool_use_id and block_id == parent_tool_use_id:
                                            role_by_id = extracted_role
                                        # 従来動作: 最後のtool_useで上書き
                                        role_from_task = extracted_role

            # parent_tool_use_idマッチ優先、なければ従来フォールバック
            result = role_by_id or role_from_task
            if result:
                if role_by_id:
                    self.log_info(f"Parsed role from transcript (by tool_use_id): {result}")
                else:
                    self.log_info(f"Parsed role from transcript (fallback last): {result}")
            return result

        except Exception as e:
            self.log_error(f"Error parsing role from transcript: {e}")

        return None

    def should_process(self, input_data: Dict[str, Any]) -> bool:
        """
        セッション開始時の処理対象かどうかを判定（設定ファイル対応・subagent override対応）

        Trueを返す場合、以下のインスタンス属性をprocess()用に設定する:
        - _is_subagent (bool): subagentコンテキストか否か
        - _resolved_config (dict|None): subagent時のoverride解決済み設定
        - _current_agent_id (str|None): subagentのagent_id
        - _current_agent_type (str|None): subagentのagent_type
        - _db, _subagent_repo, _session_repo: DB関連

        Args:
            input_data: 入力データ

        Returns:
            処理対象の場合True
        """
        self.log_info(f"📋 SessionStartupHook - Input data keys: {input_data.keys()}")

        # subagent生成ツールはスキップ（subagent自身のツール呼び出しで発火する）
        tool_name = input_data.get('tool_name', '')
        if tool_name in SUBAGENT_TOOL_NAMES:
            self.log_debug("Skipping subagent tool (subagent spawn)")
            return False

        # 設定で無効化されている場合はスキップ（base設定）
        if not self.config.get('enabled', True):
            self.log_info("❌ Session startup hook is disabled in config")
            return False

        # セッションIDを取得
        session_id = input_data.get('session_id', '')
        if not session_id:
            self.log_info("❌ No session_id found, skipping")
            return False

        self.log_info(f"🔍 Session ID: {session_id}")

        # DB Repository初期化
        db = NaggerStateDB(NaggerStateDB.resolve_db_path())
        subagent_repo = SubagentRepository(db)
        session_repo = SessionRepository(db)

        # subagent検出（DBベース）
        if subagent_repo.is_any_active(session_id):
            # claim_next_unprocessedでアトミックに取得（並列対応）
            record = subagent_repo.claim_next_unprocessed(session_id)
            if record is None:
                # 全subagent処理済み
                self.log_info("✅ All subagents already processed")
                db.close()
                return False

            # issue_6952: tool_use_id transcript parseによるleader/subagent判定
            # （issue_6057 transcript_path比較を置換: leader/subagentで同一値のため機能しなかった）
            #
            # 判定ロジック:
            # 1. Anthropic公式agent_idフィールド存在時はtranscript parseバイパス（将来対応）
            # 2. tool_use_idでmain transcript検索 → 見つかれば呼び出し元はleader → スキップ
            # 3. tool_use_idフィールド不在時はフォールバック（subagent扱い=安全側で続行）

            # D: Anthropic公式対応併存設計（将来のagent_id対応）
            if 'agent_id' in input_data:
                # Anthropic公式フィールド存在時はtranscript parseバイパス
                # agent_idでleader/subagent判定が直接可能になった場合に実装
                self.log_info(
                    f"🔮 agent_id field detected in PreToolUse payload "
                    f"(agent_id={input_data['agent_id']}). "
                    f"Future: use this for direct leader/subagent identification."
                )
                # 現時点ではフォールスルー（agent_idの値の使い方が確定していないため）

            # B: tool_use_id transcript parse判定
            tool_use_id = input_data.get('tool_use_id', '')
            current_transcript = input_data.get('transcript_path', '')
            if tool_use_id and current_transcript:
                from domain.services.leader_detection import is_leader_tool_use
                if is_leader_tool_use(current_transcript, tool_use_id):
                    self.log_info(
                        f"⏭️ Skipping subagent blocking: caller is leader "
                        f"(tool_use_id={tool_use_id})"
                    )
                    # leaderのPreToolUseではsubagentをブロックしない
                    # subagent自身のPreToolUseで再度claim_next_unprocessedが呼ばれる
                    db.close()
                    return False
            else:
                # C: フォールバック — tool_use_idまたはtranscript_pathがない場合
                # 安全側: subagent扱いで続行（ブロッキング対象として処理続行）
                self.log_warning(
                    f"⚠️ tool_use_id or transcript_path missing in PreToolUse payload. "
                    f"Falling back to subagent assumption. "
                    f"(tool_use_id={'present' if tool_use_id else 'missing'}, "
                    f"transcript_path={'present' if current_transcript else 'missing'})"
                )

            agent_type = record.agent_type
            agent_id = record.agent_id
            role = record.role

            # roleがない場合: 案D簡易版（ハイブリッドアプローチ）
            # SubagentStart時点でagent_progressが未書き込みのため、PreToolUse時に再マッチを試行
            if not role:
                transcript_path = input_data.get('transcript_path')
                if transcript_path:
                    # agent_progressベースの再マッチを試行
                    retry_role = subagent_repo.retry_match_from_agent_progress(
                        session_id, agent_id, transcript_path
                    )
                    if retry_role:
                        self.log_info(f"🔄 Retry match succeeded: role={retry_role}")
                        role = retry_role
                    else:
                        # フォールバック: transcriptから解析
                        # parentToolUseIDで特定subagentのtool_useを正確に特定
                        parent_tool_use_id = subagent_repo.find_parent_tool_use_id(
                            transcript_path, agent_id
                        )
                        parsed_role = self._parse_role_from_transcript(
                            transcript_path, parent_tool_use_id
                        )
                        if parsed_role:
                            subagent_repo.update_role(agent_id, parsed_role, 'transcript_parse')
                            role = parsed_role

            self.log_info(f"🤖 Subagent detected: type={agent_type}, id={agent_id}, role={role}")

            # override設定を解決（role優先）
            resolved = self._resolve_subagent_config(agent_type, role=role)

            # override設定でenabled: falseの場合はスキップ
            if not resolved.get("enabled", True):
                self.log_info(f"❌ Subagent type '{agent_type}' is disabled by overrides")
                db.close()
                return False

            # subagentコンテキストを保存して後続processで使用
            # 2フェーズ方式: claim_next_unprocessed()は取得のみ、process()完了後にmark_processed()
            self._is_subagent = True
            self._resolved_config = resolved
            self._current_agent_id = agent_id
            self._current_agent_type = agent_type
            self._db = db
            self._subagent_repo = subagent_repo
            self._session_repo = session_repo

            self.log_info(f"🚀 New subagent requires startup processing: {agent_type}/{agent_id}")
            return True

        # main agentフロー
        self._is_subagent = False
        self._resolved_config = None
        self._db = db
        self._subagent_repo = subagent_repo
        self._session_repo = session_repo

        # SessionRepositoryで処理済みチェック
        if self.config.get('behavior', {}).get('once_per_session', True):
            threshold = self.config.get('behavior', {}).get('token_threshold', 50000)
            current_tokens = self._get_current_context_size(input_data.get('transcript_path')) or 0
            if session_repo.is_processed_context_aware(session_id, self.__class__.__name__, current_tokens, threshold):
                self.log_info(f"✅ Session startup already processed for: {session_id}")
                db.close()
                return False

        self.log_info(f"🚀 New session detected, requires startup processing: {session_id}")
        return True

    def process(self, input_data: Dict[str, Any]) -> Dict[str, str]:
        """
        セッション開始時の規約確認処理を実行（subagent override対応）

        前提: should_process()がTrueを返した後に呼び出すこと。
        should_process()が設定した_is_subagent, _resolved_config等を参照する。

        Args:
            input_data: 入力データ

        Returns:
            処理結果 {'decision': 'block'/'approve', 'reason': 'メッセージ'}
        """
        session_id = input_data.get('session_id', '')

        self.log_info(f"🎯 Processing session startup for: {session_id} (subagent={self._is_subagent})")

        # suggested_rules.yamlを一度だけ読み込み
        suggested_rules_data = self._load_suggested_rules()

        # メッセージを構築（ロード結果を引数で渡す）
        message = self._build_message(session_id, suggested_rules_data=suggested_rules_data)

        self.log_info(f"📋 SESSION STARTUP BLOCKING: Session '{session_id}' requires startup confirmation")

        if self._is_subagent:
            # subagent: process完了後にmark_processed()でマーク
            # 2フェーズ方式: claim_next_unprocessed()は取得のみ、ここでマーク
            self._subagent_repo.mark_processed(self._current_agent_id)
            self.log_info(f"✅ Subagent {self._current_agent_id} marked as startup_processed after process completion")
        else:
            # main agent: SessionRepositoryで処理済みマーク
            current_tokens = self._get_current_context_size(input_data.get('transcript_path')) or 0
            self._session_repo.register(session_id, self.__class__.__name__, current_tokens)
            self.log_info(f"✅ Registered session in DB: {session_id} with {current_tokens} tokens")

        # 通知済みのsuggested_rules.yamlをアーカイブ
        if suggested_rules_data is not None:
            self._archive_suggested_rules()
            # 分析済みhook_inputもアーカイブ（再生成防止: issue_5964）
            self._archive_hook_inputs()

        # JSON応答でブロック
        return {
            'decision': 'block',
            'reason': message
        }

    def _get_execution_count(self, session_id: str) -> int:
        """
        セッション内での実行回数を取得（DBベース）

        sessionsテーブルのcreated_atを利用し、同一session_id/hook_nameのレコード数をカウント。
        expired含む全レコードを対象とする。

        Args:
            session_id: セッションID

        Returns:
            実行回数（1から開始）
        """
        if self._db is None:
            # DBが未初期化の場合は1を返す
            return 1

        cursor = self._db.conn.execute(
            """
            SELECT COUNT(*) FROM sessions
            WHERE session_id = ? AND hook_name = ?
            """,
            (session_id, self.__class__.__name__),
        )
        row = cursor.fetchone()
        count = row[0] if row else 0

        # 次回実行予定の回数を返す（カウント+1）
        return count + 1
    
    def _build_message(self, session_id: str, suggested_rules_data: Optional[Dict[str, Any]] = None) -> str:
        """
        設定ファイルからメッセージを構築（subagent override対応）
        
        Args:
            session_id: セッションID
            suggested_rules_data: ロード済みのsuggested_rulesデータ（Noneなら提案なし）
            
        Returns:
            構築されたメッセージ文字列
        """
        # subagentの場合は解決済みconfigを使用
        if self._is_subagent and self._resolved_config:
            config_to_use = self._resolved_config
            # subagentは常に初回扱い
            execution_count = 1
        else:
            config_to_use = self.config
            execution_count = self._get_execution_count(session_id)
        
        # messages 構造から適切なメッセージを選択
        messages_config = config_to_use.get('messages', {})
        
        if execution_count == 1:
            message_config = messages_config.get('first_time', {})
        else:
            message_config = messages_config.get('repeated', {})
        
        title = message_config.get('title', 'セッション開始時の確認')
        main_text = message_config.get('main_text', '設定ファイルを確認してください。')
        
        # メッセージを構築
        message = title + "\n\n" + main_text
        
        # suggested_rules.yaml の提案サマリーを統合
        if suggested_rules_data:
            summary = self._build_suggested_rules_summary(suggested_rules_data)
            if summary:
                message += "\n\n" + summary

        # 前回セッションのsubagent履歴サマリーを追記（mainエージェントのみ）
        if not self._is_subagent:
            history_summary = self._build_subagent_history_summary(session_id)
            if history_summary:
                message += "\n\n" + history_summary

        self.log_info(f"🎯 Built message for execution #{execution_count}: {title[:50]}...")
        
        return message

    def _get_suggested_rules_path(self) -> Path:
        """suggested_rules.yamlのパスを返す"""
        project_dir = os.environ.get("CLAUDE_PROJECT_DIR")
        base_path = Path(project_dir) if project_dir else Path.cwd()
        return base_path / ".claude-nagger" / SUGGESTED_RULES_DIRNAME / SUGGESTED_RULES_FILENAME

    def _load_suggested_rules(self) -> Optional[Dict[str, Any]]:
        """suggested_rules.yamlを読み込む。存在しない場合はNone"""
        rules_path = self._get_suggested_rules_path()
        if not rules_path.exists():
            return None

        try:
            with open(rules_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            self.log_info(f"📋 suggested_rules.yaml を検出: {rules_path}")
            return data
        except Exception as e:
            self.log_error(f"❌ suggested_rules.yaml 読み込み失敗: {e}")
            return None

    def _build_suggested_rules_summary(self, rules_data: Dict[str, Any]) -> str:
        """規約提案データからサマリーメッセージを構築"""
        rules = rules_data.get('rules', [])
        if not rules:
            return ""

        lines = [
            "---",
            "📋 規約提案があります（suggested_rules.yaml）",
            f"提案数: {len(rules)}件",
            "",
        ]

        for i, rule in enumerate(rules, 1):
            name = rule.get('name', '(名前なし)')
            severity = rule.get('severity', 'warn')
            message = rule.get('message', '').strip().split('\n')[0]

            patterns = rule.get('patterns', [])
            commands = rule.get('commands', [])

            target = ""
            if patterns:
                target = f"パターン: {', '.join(patterns[:3])}"
            elif commands:
                target = f"コマンド: {', '.join(commands[:3])}"

            lines.append(f"{i}. [{severity}] {name}")
            if target:
                lines.append(f"   {target}")
            if message:
                lines.append(f"   → {message}")

        lines.extend([
            "",
            "確認後、file_conventions.yaml / command_conventions.yaml に追記してください。",
        ])

        return "\n".join(lines)

    def _build_subagent_history_summary(self, session_id: str) -> Optional[str]:
        """前回セッションのsubagent履歴サマリーを構築

        Args:
            session_id: 現在のセッションID

        Returns:
            サマリー文字列。前回セッションがない or 件数0ならNone
        """
        if not self._db:
            return None

        history_repo = SubagentHistoryRepository(self._db)
        previous_session_id = history_repo.get_previous_session_id(session_id)
        if not previous_session_id:
            return None

        stats = history_repo.get_stats(previous_session_id)
        if stats["total"] == 0:
            return None

        lines = [
            "---",
            "📊 前回セッションのsubagentアクティビティ",
            f"合計: {stats['total']}件",
            "",
            "role別:",
        ]

        for role, count in stats["by_role"].items():
            lines.append(f"  - {role}: {count}件")

        if stats["avg_duration_seconds"] is not None:
            avg = round(stats["avg_duration_seconds"], 1)
            lines.append("")
            lines.append(f"平均所要時間: {avg}秒")

        return "\n".join(lines)

    def _archive_suggested_rules(self) -> bool:
        """通知済みのsuggested_rules.yamlをリネーム（タイムスタンプなし単一ファイル）"""
        rules_path = self._get_suggested_rules_path()
        if not rules_path.exists():
            return False

        # タイムスタンプなし単一アーカイブファイル（上書き）
        archived_name = f"{SUGGESTED_RULES_FILENAME}.notified"
        archived_path = rules_path.parent / archived_name

        try:
            rules_path.rename(archived_path)
            self.log_info(f"📦 suggested_rules.yaml をアーカイブ: {archived_path}")
            return True
        except Exception as e:
            self.log_error(f"❌ suggested_rules.yaml アーカイブ失敗: {e}")
            return False

    def _archive_hook_inputs(self) -> int:
        """通知済みのhook_input_*.jsonをアーカイブディレクトリに移動

        suggested_rules通知後に呼び出し、分析済みhook_inputを隔離することで
        閾値再到達による再生成を防止する（issue_5964）

        Returns:
            移動したファイル数
        """
        import glob
        import shutil

        log_dir = self.log_dir
        archive_dir = log_dir / "archived_hook_inputs"

        # hook_input_*.jsonを検索
        pattern = str(log_dir / "hook_input_*.json")
        files = glob.glob(pattern)

        if not files:
            self.log_debug("アーカイブ対象のhook_inputなし")
            return 0

        # アーカイブディレクトリ作成
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.log_error(f"❌ アーカイブディレクトリ作成失敗: {e}")
            return 0

        # ファイル移動
        moved_count = 0
        for filepath in files:
            try:
                src = Path(filepath)
                dst = archive_dir / src.name
                shutil.move(str(src), str(dst))
                moved_count += 1
            except Exception as e:
                self.log_error(f"❌ hook_input移動失敗: {filepath} - {e}")

        self.log_info(f"📦 hook_input {moved_count}件をアーカイブ: {archive_dir}")
        return moved_count


def main():
    """メインエントリーポイント"""
    hook = SessionStartupHook(debug=False)
    sys.exit(hook.run())


if __name__ == "__main__":
    main()