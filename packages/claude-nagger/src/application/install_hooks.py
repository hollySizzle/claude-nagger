#!/usr/bin/env python3
"""install-hooks コマンド実装

機能:
1. .claude-nagger/ ディレクトリがなければ雛形生成
2. .claude/settings.json へ PreToolUse フック設定を登録
"""

import json
import os
import sys
from pathlib import Path
from typing import Any


class InstallHooksCommand:
    """フックインストールコマンド"""

    # 雛形ファイルの内容
    FILE_CONVENTIONS_TEMPLATE = """\
# ファイル編集規約定義
# 特定のファイルパターンに対して適用される規約を定義します

rules:
  # 例: View層編集規約
  # - name: "View層編集規約"
  #   patterns:
  #     - "**/app/views/**/*.erb"
  #   severity: "block"  # block: 完全ブロック, warn: 警告のみ
  #   token_threshold: 35000
  #   message: |
  #     このファイルを変更する場合は規約を確認してください
  []
"""

    COMMAND_CONVENTIONS_TEMPLATE = """\
# コマンド実行規約定義
# 危険なコマンドや確認が必要なコマンドに対して適用される規約を定義します

rules:
  # 例: Git操作規約
  # - name: "Git操作規約"
  #   patterns:
  #     - "git*"
  #   severity: "block"
  #   token_threshold: 25000
  #   message: |
  #     Git操作を実行する場合は規約を確認してください
  []
"""

    MCP_CONVENTIONS_TEMPLATE = """\
# MCP規約設定
# MCPツール呼び出し時のパターンマッチ規約を定義します
# tool_pattern: 正規表現（re.match）でMCPツール名にマッチ

rules:
  # 例: Redmine更新操作規約
  # - name: "Redmine更新確認"
  #   tool_pattern: "mcp__redmine_epic_grid__update.*"
  #   severity: "warn"
  #   token_threshold: 25000
  #   message: |
  #     Redmineの更新操作を行います。確認してください。
  []
"""

    CONFIG_TEMPLATE = """\
# claude-nagger 設定ファイル

# セッション開始時設定
session_startup:
  enabled: true
  messages:
    first_time:
      title: "プロジェクトセットアップ"
      main_text: |
        プロジェクトの規約を確認してください
      severity: "block"
    # 継続セッション用（token_threshold超過時に表示）
    repeated:
      title: "規約再確認"
      main_text: |
        規約を再確認してください
      severity: "block"

  # subagent別override設定（subagent自身に直接ブロッキング通知される）
  # 仕組み: SubagentStart hook → マーカー作成 → 次のPreToolUseでsubagentをブロック
  # 解決順序: base(上記) → subagent_default → subagent_types.{type}
  # namespaced対応: "my-plugin:coder" → "coder" にフォールバック
  # 命名規約: Agent Teamsメンバーのnameはsubagent_typesのキーと一致させること
  #   例: name="coder" → subagent_types.coder にマッチ
  overrides:
    subagent_default:
      messages:
        first_time:
          title: "subagent規約"
          main_text: |
            [ ] スコープ外のファイルを編集しないこと
            [ ] 作業完了後に結果を報告すること
    subagent_types:
      Explore:
        enabled: false
      Plan:
        enabled: false
      Bash:
        messages:
          first_time:
            title: "Bash subagent規約"
            main_text: |
              [ ] 破壊的コマンド禁止
      scribe:
        messages:
          first_time:
            title: "scribe subagent規約"
            main_text: |
              基本規約:
              [ ] 指定された操作のみ行うこと
              [ ] スコープ外の操作は行わないこと
              報告規約:
              [ ] 作業完了後に結果を報告すること
              [ ] コメント冒頭に [scribe] プレフィックスを付けること
      tester:
        messages:
          first_time:
            title: "tester subagent規約"
            main_text: |
              基本規約:
              [ ] 仕様からテストを設計すること（実装詳細に依存しない）
              [ ] コードを編集しないこと（Read専用）
              [ ] テスト失敗時に自分で修正しないこと
              報告規約:
              [ ] テスト結果を報告すること
              [ ] 失敗時は期待動作 vs 実際の動作を明記すること
              [ ] コメント冒頭に [tester] プレフィックスを付けること
      coder:
        messages:
          first_time:
            title: "coder subagent規約"
            main_text: |
              基本規約:
              [ ] 指示されたスコープ外のファイルを編集しないこと
              [ ] 判断が必要な場合は実装せず報告すること
              [ ] テストがあれば実行してから完了報告すること
              報告規約:
              [ ] 完了時に変更内容・懸念事項を報告すること
              [ ] コメント冒頭に [coder] プレフィックスを付けること
      conductor:
        messages:
          first_time:
            title: "conductor subagent規約"
            main_text: |
              [ ] 直接作業を実行しないこと（コード編集・ファイル操作禁止）
              [ ] 実作業はSubAgent（coder/tester/scribe）へ委譲すること
              [ ] SubAgentの成果物を必ずレビューすること

# SendMessageガード設定（Redmine基盤通信強制）
# 毎回検査。違反時のみblock、合格時は無通知通過
sendmessage_guard:
  enabled: true
  pattern: "^issue_\\\\d+ \\\\[.+\\\\]$"
  exempt_types:
    - shutdown_request
    - shutdown_response
    - plan_approval_response

# Discord通知設定
# webhook_url/thread_id は secrets.yaml から自動解決（${VAR} → secrets.yaml discord.* にフォールバック）
notifications:
  discord:
    enabled: true
    webhook_url: "${DISCORD_WEBHOOK_URL}"
    thread_id: "${DISCORD_THREAD_ID}"

# トランスクリプト保存設定（raw modeトランスクリプトDB保存）
transcript_storage:
  enabled: false
  # mode: raw=生データ格納 / indexed=インデックス付き / structured=構造化格納
  mode: "structured"
  retention_days: 30

# コンテキスト管理設定
context_management:
  reminder_thresholds:
    light_warning: 30000
    medium_warning: 60000
    critical_warning: 100000

# デバッグ設定
debug:
  enable_logging: false
"""

    SECRETS_TEMPLATE = """\
# 機密情報設定ファイル
# このファイルはGit管理対象外です（.gitignoreで除外済み）

# Discord通知設定
discord:
  webhook_url: ""
  thread_id: ""

# その他の機密情報
# api_keys:
#   service_name: "your-api-key"
"""

    GITIGNORE_TEMPLATE = """\
# vault/ディレクトリ内の全ファイルを除外
# 機密情報の漏洩防止
*
!.gitignore
"""

    # .claude-nagger/直下の.gitignoreテンプレート
    DOTCN_GITIGNORE_TEMPLATE = """\
# ランタイム生成ファイル（自動生成: claude-nagger install-hooks）
state.db
state.db-wal
state.db-shm
suggested_rules/
"""

    # デフォルトのPreToolUseフック設定
    # サブコマンド形式（claude-nagger hook <name>）を使用
    # uv tool install / pip install 両環境で動作
    DEFAULT_PRETOOLUSE_HOOKS = [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook session-startup"
                }
            ]
        },
        {
            "matcher": "mcp__.*__write.*",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook implementation-design"
                }
            ]
        },
        {
            "matcher": "mcp__.*replace.*",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook implementation-design"
                }
            ]
        },
        {
            "matcher": "mcp__.*insert.*",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook implementation-design"
                }
            ]
        },
        {
            "matcher": "Bash",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook implementation-design"
                }
            ]
        },
        {
            "matcher": "Edit",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook implementation-design"
                }
            ]
        },
        {
            "matcher": "Write",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook implementation-design"
                }
            ]
        },
        {
            "matcher": "MultiEdit",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook implementation-design"
                }
            ]
        },
        {
            "matcher": "SendMessage",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook sendmessage-guard"
                }
            ]
        },
    ]

    # デフォルトのNotificationフック設定
    # 通知発生時（複数API呼び出し間等）に実行される
    # claude-nagger notify コマンドを使用（uv/pip両環境対応）
    DEFAULT_NOTIFICATION_HOOKS: list = [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger notify \"📢 Claude Code から通知があります\""
                }
            ]
        }
    ]

    # デフォルトのStopフック設定
    # タスク完了・停止時に実行される
    # claude-nagger notify コマンドを使用（uv/pip両環境対応）
    DEFAULT_STOP_HOOKS: list = [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger notify \"🛑 Claude Code セッションが停止されました\""
                }
            ]
        },
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook suggest-rules-trigger"
                }
            ]
        },
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook transcript-storage"
                }
            ]
        }
    ]

    # デフォルトのSessionStartフック設定
    # compact発生時にマーカーをリセットし、既存フローを再発火させる
    DEFAULT_SESSIONSTART_HOOKS: list = [
        {
            "matcher": "compact",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook compact-detected"
                }
            ]
        }
    ]


    # デフォルトのSubagentStartフック設定
    # サブエージェント開始時にマーカーファイルを作成
    DEFAULT_SUBAGENTSTART_HOOKS: list = [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook subagent-event"
                }
            ]
        }
    ]

    # デフォルトのSubagentStopフック設定
    # サブエージェント終了時にマーカーファイルを削除
    DEFAULT_SUBAGENTSTOP_HOOKS: list = [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook subagent-event"
                }
            ]
        }
    ]

    # デフォルトのPostToolUseフック設定
    # Redmine MCPツール操作後にDiscord通知を送信
    DEFAULT_POSTTOOLUSE_HOOKS: list = [
        {
            "matcher": "mcp__redmine_epic_grid__.*",
            "hooks": [
                {
                    "type": "command",
                    "command": "claude-nagger hook redmine-discord"
                }
            ]
        }
    ]

    def __init__(self, force: bool = False, dry_run: bool = False):
        """
        Args:
            force: 既存ファイルを上書きするか
            dry_run: 実行内容を表示するのみ
        """
        self.force = force
        self.dry_run = dry_run
        self.project_root = Path.cwd()

    def execute(self) -> int:
        """コマンド実行"""
        print("claude-nagger install-hooks")
        print("=" * 40)

        try:
            # 1. .claude-nagger/ ディレクトリと雛形ファイル生成
            self._create_claude_nagger_dir()

            # 2. .claude/settings.json へフック設定追加
            self._update_settings_json()

            print()
            print("インストール完了")
            return 0

        except Exception as e:
            print(f"エラー: {e}")
            return 1

    def _create_claude_nagger_dir(self):
        """`.claude-nagger/` ディレクトリと雛形ファイルを生成"""
        nagger_dir = self.project_root / ".claude-nagger"

        if self.dry_run:
            print(f"[dry-run] ディレクトリ作成: {nagger_dir}")
        else:
            nagger_dir.mkdir(exist_ok=True)
            print(f"ディレクトリ確認: {nagger_dir}")

        # 雛形ファイル生成（conventions.yamlはrules/をフォールバックで使用するため生成しない）
        files = {
            "config.yaml": self.CONFIG_TEMPLATE,
        }

        for filename, content in files.items():
            file_path = nagger_dir / filename
            self._write_file(file_path, content)

        # .claude-nagger/.gitignore 生成（ランタイムファイル除外用）
        self._write_file(nagger_dir / ".gitignore", self.DOTCN_GITIGNORE_TEMPLATE)

        # vault/ ディレクトリと機密ファイル生成
        self._create_vault_dir(nagger_dir)

    def _create_vault_dir(self, nagger_dir: Path):
        """vault/ディレクトリと機密ファイルを生成"""
        vault_dir = nagger_dir / "vault"

        if self.dry_run:
            print(f"[dry-run] ディレクトリ作成: {vault_dir}")
        else:
            vault_dir.mkdir(exist_ok=True)
            print(f"ディレクトリ確認: {vault_dir}")

        # vault内ファイル生成
        vault_files = {
            "secrets.yaml": self.SECRETS_TEMPLATE,
            ".gitignore": self.GITIGNORE_TEMPLATE,
        }

        for filename, content in vault_files.items():
            file_path = vault_dir / filename
            self._write_file(file_path, content)

    def _write_file(self, path: Path, content: str):
        """ファイル書き込み（force/dry-run考慮）"""
        if path.exists() and not self.force:
            print(f"  スキップ（既存）: {path.name}")
            return

        if self.dry_run:
            action = "上書き" if path.exists() else "作成"
            print(f"  [dry-run] {action}: {path.name}")
        else:
            path.write_text(content, encoding="utf-8")
            action = "上書き" if path.exists() else "作成"
            print(f"  {action}: {path.name}")

    def _update_settings_json(self):
        """`.claude/settings.json` にフック設定を追加"""
        claude_dir = self.project_root / ".claude"
        settings_path = claude_dir / "settings.json"

        print()
        print("フック設定更新:")

        # .claude/ ディレクトリ作成
        if self.dry_run:
            if not claude_dir.exists():
                print(f"  [dry-run] ディレクトリ作成: {claude_dir}")
        else:
            claude_dir.mkdir(exist_ok=True)

        # 既存設定の読み込み
        settings = self._load_settings(settings_path)

        # 各フック設定のマージ
        hook_configs = [
            ("PreToolUse", self.DEFAULT_PRETOOLUSE_HOOKS),
            ("Notification", self.DEFAULT_NOTIFICATION_HOOKS),
            ("Stop", self.DEFAULT_STOP_HOOKS),
            ("SessionStart", self.DEFAULT_SESSIONSTART_HOOKS),
            ("SubagentStart", self.DEFAULT_SUBAGENTSTART_HOOKS),
            ("SubagentStop", self.DEFAULT_SUBAGENTSTOP_HOOKS),
            ("PostToolUse", self.DEFAULT_POSTTOOLUSE_HOOKS),
        ]

        any_updated = False
        for hook_type, default_hooks in hook_configs:
            if default_hooks:  # 空リストはスキップ
                updated = self._merge_hook_entries(settings, hook_type, default_hooks)
                any_updated = any_updated or updated

        if not any_updated:
            print("  フック設定は既に存在します（変更なし）")
            return

        # 設定の書き込み
        if self.dry_run:
            print("  [dry-run] settings.json を更新")
        else:
            self._save_settings(settings_path, settings)
            print(f"  更新: {settings_path}")

    def _load_settings(self, path: Path) -> dict[str, Any]:
        """settings.json を読み込み"""
        if not path.exists():
            return {}

        try:
            content = path.read_text(encoding="utf-8")
            return json.loads(content)
        except json.JSONDecodeError:
            print(f"  警告: {path} のパースに失敗。新規作成します。")
            return {}

    def _merge_pretooluse_hooks(self, settings: dict[str, Any]) -> bool:
        """PreToolUseフックをマージ（後方互換性のためのラッパー）

        Returns:
            bool: 変更があった場合True
        """
        return self._merge_hook_entries(settings, "PreToolUse", self.DEFAULT_PRETOOLUSE_HOOKS)

    def _merge_hook_entries(
        self,
        settings: dict[str, Any],
        hook_type: str,
        default_hooks: list[dict[str, Any]]
    ) -> bool:
        """指定タイプのフックをマージ（汎用）

        Args:
            settings: 設定dict
            hook_type: フックタイプ (PreToolUse/Notification/Stop)
            default_hooks: 追加するデフォルトフック

        Returns:
            bool: 変更があった場合True
        """
        if "hooks" not in settings:
            settings["hooks"] = {}

        hooks = settings["hooks"]

        if hook_type not in hooks:
            hooks[hook_type] = []

        hook_list = hooks[hook_type]

        # 既存の(matcher, command)ペアを収集
        existing_entries = set()
        for hook_entry in hook_list:
            matcher = hook_entry.get("matcher", "")
            for hook in hook_entry.get("hooks", []):
                if "command" in hook:
                    existing_entries.add((matcher, hook["command"]))

        # 新規フックを追加（matcher+commandの組み合わせで重複回避）
        added = False
        for new_entry in default_hooks:
            matcher = new_entry.get("matcher", "")
            for hook in new_entry.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd and (matcher, cmd) not in existing_entries:
                    hook_list.append(new_entry)
                    existing_entries.add((matcher, cmd))
                    added = True
                    print(f"  追加 [{hook_type}]: {cmd}")
                elif cmd:
                    print(f"  スキップ（既存）[{hook_type}]: {cmd}")

        return added

    def _save_settings(self, path: Path, settings: dict[str, Any]):
        """settings.json を保存"""
        content = json.dumps(settings, indent=2, ensure_ascii=False)
        path.write_text(content + "\n", encoding="utf-8")


def ensure_config_exists(project_root: Path = None) -> bool:
    """設定ファイルの存在を保証する（冪等）
    
    .claude-nagger/ディレクトリと設定ファイル群が存在しない場合は生成する。
    フック実行時に自動的に呼び出される。
    
    Args:
        project_root: プロジェクトルートパス（デフォルト: カレントディレクトリ）
    
    Returns:
        bool: ファイルが生成された場合True、既存の場合False
    """
    if project_root is None:
        project_root = Path.cwd()
    
    nagger_dir = project_root / ".claude-nagger"
    config_path = nagger_dir / "config.yaml"
    
    # 設定ファイルが存在すれば何もしない
    if config_path.exists():
        return False
    
    # 設定ファイルを生成
    generated = False
    
    # ディレクトリ作成
    if not nagger_dir.exists():
        nagger_dir.mkdir(exist_ok=True)
        generated = True
    
    # 各ファイルを不足分のみ生成（conventions.yamlはrules/をフォールバックで使用するため生成しない）
    files = {
        "config.yaml": InstallHooksCommand.CONFIG_TEMPLATE,
    }
    
    for filename, content in files.items():
        file_path = nagger_dir / filename
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")
            generated = True
    
    # vault/ディレクトリと機密ファイル生成
    vault_dir = nagger_dir / "vault"
    if not vault_dir.exists():
        vault_dir.mkdir(exist_ok=True)
        generated = True
    
    vault_files = {
        "secrets.yaml": InstallHooksCommand.SECRETS_TEMPLATE,
        ".gitignore": InstallHooksCommand.GITIGNORE_TEMPLATE,
    }
    
    for filename, content in vault_files.items():
        file_path = vault_dir / filename
        if not file_path.exists():
            file_path.write_text(content, encoding="utf-8")
            generated = True

    # .claude-nagger/.gitignore 生成（ランタイムファイル除外用）
    gitignore_path = nagger_dir / ".gitignore"
    if not gitignore_path.exists():
        gitignore_path.write_text(InstallHooksCommand.DOTCN_GITIGNORE_TEMPLATE, encoding="utf-8")
        generated = True

    # 自動生成時の警告出力
    if generated:
        print("警告: 設定ファイルを自動生成しました (.claude-nagger/)", file=sys.stderr)
    
    return generated
