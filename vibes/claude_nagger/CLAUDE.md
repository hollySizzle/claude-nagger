# CLAUDE.md

詳細は README.md 参照

## コマンド

```bash
# テスト実行
python3 -m pytest tests/ -v

# 特定テスト
python3 -m pytest tests/test_xxx.py -v          # ファイル指定
python3 -m pytest tests/ -k "keyword" -v        # キーワード指定

# カバレッジ
python3 -m pytest --cov=src --cov-report=term-missing

# ローカルテスト環境
./scripts/setup_test_env.sh --help

# フィクスチャキャプチャ
python3 scripts/capture_fixture.py --sanitize -n 10

# リリース（PyPI自動公開）
./scripts/release.sh <version>           # フル: バージョン更新→push→GitHubリリース
./scripts/release.sh <version> --release-only  # GitHubリリースのみ
# 要: .env に GH_TOKEN 設定
```

## ディレクトリ構成

```
src/
  application/   # CLI・エントリーポイント
  domain/        # フック・マッチャー
  infrastructure/ # 外部連携
  shared/        # 共通ユーティリティ
tests/           # pytest
scripts/         # 開発用スクリプト
.claude-nagger/  # 設定ファイル雛形
```

## 規約

- テスト必須: 新機能は必ずテスト実装
- Redmine追跡: 作業前にチケット起票
- コミット: issue_{id} を含める
