# Vibes Scripts

Railsプロジェクト用のユーティリティスクリプト集

## セットアップ

```bash
# 依存関係のインストール
pip install -r requirements.txt

# 設定ファイルの準備
cp config.sample.json5 config.json5
cp secrets.sample.json5 secrets.json5  # 機密情報（APIキーなど）
```

## 主な機能

### Discord通知

```bash
# どこからでも実行可能
python3 /path/to/vibes/scripts/src/infrastructure/notifiers/discord_notifier.py "メッセージ"

# bin/discord-notifyを使用（実行権限付与済み）
/path/to/vibes/scripts/bin/discord-notify "メッセージ"
```

### セッション管理

- `SessionManager`: セッションIDとエージェント名を統一管理
- Claudeフック環境での自動セッションID取得

### 設定管理

設定の優先順位（高→低）:
1. 環境変数 (os.environ)
2. secrets.json5
3. config.json5

## ディレクトリ構造

```
vibes/scripts/
├── src/
│   ├── infrastructure/        # インフラ層
│   │   ├── config/            # 設定管理
│   │   └── notifiers/         # 通知機能
│   └── shared/                # 共通機能
│       └── utils/             # ユーティリティ
├── tests/                     # テストコード
├── bin/                       # 実行可能スクリプト
├── config.json5              # 一般設定
└── secrets.json5             # 機密情報（Git管理外）
```

## テスト

```bash
# 全テストを実行
python3 -m pytest tests/ -v

# 特定のテストを実行
python3 -m pytest tests/test_discord_notifier.py -v
```