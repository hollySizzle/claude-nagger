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

    # デフォルトのPreToolUseフック設定
    # モジュール呼び出し形式（python3 -m）を使用
    # パッケージインストール後は domain.hooks.* でアクセス可能
    DEFAULT_PRETOOLUSE_HOOKS = [
        {
            "matcher": "",
            "hooks": [
                {
                    "type": "command",
                    "command": "python3 -m domain.hooks.session_startup_hook"
                }
            ]
        },
        {
            "matcher": "mcp__.*__write.*",
            "hooks": [
                {
                    "type": "command",
                    "command": "python3 -m domain.hooks.implementation_design_hook"
                }
            ]
        },
        {
            "matcher": "mcp__.*replace.*",
            "hooks": [
                {
                    "type": "command",
                    "command": "python3 -m domain.hooks.implementation_design_hook"
                }
            ]
        },
        {
            "matcher": "mcp__.*insert.*",
            "hooks": [
                {
                    "type": "command",
                    "command": "python3 -m domain.hooks.implementation_design_hook"
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

        # 雛形ファイル生成
        files = {
            "file_conventions.yaml": self.FILE_CONVENTIONS_TEMPLATE,
            "command_conventions.yaml": self.COMMAND_CONVENTIONS_TEMPLATE,
            "config.yaml": self.CONFIG_TEMPLATE,
        }

        for filename, content in files.items():
            file_path = nagger_dir / filename
            self._write_file(file_path, content)

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
        """`.claude/settings.json` にPreToolUseフック設定を追加"""
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

        # PreToolUseフック設定のマージ
        updated = self._merge_pretooluse_hooks(settings)

        if not updated:
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
        """PreToolUseフックをマージ（スマートマージ）

        Returns:
            bool: 変更があった場合True
        """
        if "hooks" not in settings:
            settings["hooks"] = {}

        hooks = settings["hooks"]

        if "PreToolUse" not in hooks:
            hooks["PreToolUse"] = []

        pretooluse = hooks["PreToolUse"]

        # 既存の(matcher, command)ペアを収集
        existing_entries = set()
        for hook_entry in pretooluse:
            matcher = hook_entry.get("matcher", "")
            for hook in hook_entry.get("hooks", []):
                if "command" in hook:
                    existing_entries.add((matcher, hook["command"]))

        # 新規フックを追加（matcher+commandの組み合わせで重複回避）
        added = False
        for new_entry in self.DEFAULT_PRETOOLUSE_HOOKS:
            matcher = new_entry.get("matcher", "")
            for hook in new_entry.get("hooks", []):
                cmd = hook.get("command", "")
                if cmd and (matcher, cmd) not in existing_entries:
                    pretooluse.append(new_entry)
                    existing_entries.add((matcher, cmd))
                    added = True
                    print(f"  追加: {cmd}")

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
    
    # 各ファイルを不足分のみ生成
    files = {
        "file_conventions.yaml": InstallHooksCommand.FILE_CONVENTIONS_TEMPLATE,
        "command_conventions.yaml": InstallHooksCommand.COMMAND_CONVENTIONS_TEMPLATE,
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
    
    # 自動生成時の警告出力
    if generated:
        print("警告: 設定ファイルを自動生成しました (.claude-nagger/)", file=sys.stderr)
    
    return generated
