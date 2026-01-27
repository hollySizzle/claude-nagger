# claude-nagger プロジェクト概要

## 目的
Claude Code統合ツールシステム - フック・規約管理CLI

## 技術スタック
- Python 3.10+, pytest, pytest-asyncio
- hatchling (build), uv (package manager)
- 依存: questionary, pytz, json5, pyyaml, rich, aiohttp, wcmatch

## コード構造
```
src/
  application/   # CLI・エントリーポイント (diagnose.py等)
  domain/        # フック・マッチャー (hooks/base_hook.py等)
  infrastructure/ # 外部連携 (config/config_manager.py等)
  shared/        # 共通ユーティリティ (utils/session_manager.py等)
tests/           # pytest (test_*.py)
```

## 規約
- テスト必須、コメント日本語
- Redmine追跡: コミットにissue_{id}含める
- ロガー: `logging.getLogger(__name__)` or クラス固有 `self.log_debug()`
