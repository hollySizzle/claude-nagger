# アーキテクチャ仕様書

## 概要

[TODO: フレームワーク名] MVC に[TODO: 表示層パターン名]パターンを追加し、設定駆動によるユーザタイプ別 UI 制御を実現。

## システム構成

**レイヤー構成**:

- [TODO: コントローラ層名]: HTTPリクエスト制御
- [TODO: サービス層名]: 外部API連携、複雑業務処理
- [TODO: 表示層名]: 表示ロジック、フォーム制御
- [TODO: モデル層名]: ビジネスロジック、データ永続化
- [TODO: ビュー層名]: UI表示

**動作フロー**: Request → [TODO: コントローラ層] → [TODO: モデル/サービス層] → [TODO: 表示層] → [TODO: ビュー層] → Response

## 設定仕様

**ファイルパス**: `[TODO: 設定ファイルパス]/{model_name}_fields.yml`

**基本構造**: search_fields, index_fields, show_fields, form_fields
**権限別設定**: overrides 配下でユーザタイプ別に項目をオーバーライド

## 実装パターン

**[TODO: 表示層クラス]**: `display_#{field_name}`, `select_collection_#{field_name}`メソッドで表示制御
**[TODO: サービス層クラス]**: 外部 API 連携や複雑業務処理を抽象化、`{ドメイン名}{処理内容}[TODO: サービスクラスサフィックス]`形式で命名
**動的メソッド呼び出し**: 設定に基づいた自動メソッド実行

## 技術仕様

**外部依存**: [TODO: フレームワークバージョン], [TODO: 検索ライブラリ], [TODO: 国際化ライブラリ], [TODO: パラレルテストライブラリ], [TODO: E2E テストライブラリ]
**認証**: `authenticate_user!`, `check_permission`でアクセス制御

## エラーハンドリング

**主要エラー**: ConfigurationError(設定不正), PermissionError(権限不足), ValidationError(データ検証)
**通知**: Rails 標準エラーハンドリング、log/production.log 出力

## テスト仕様

**E2E テスト**: `[TODO: E2Eテストコマンド]`でパラレル実行、[TODO: E2E テストライブラリ]使用
**単体テスト**: [TODO: テストフレームワーク]で[TODO: 表示層]/[TODO: サービス層]のテスト
**パフォーマンス目標**: 画面表示 100ms 以内、メモリ使用量 500MB 以内

## 運用・保守

**定期メンテナンス**: 設定ファイル見直し(四半期毎), ドキュメント整合性チェック(二週間毎)
**監視項目**: レスポンス時間 1 秒以上, エラー率 5%以上でアラート
**トラブルシューティング**: 表示崩れ → `display_#{field_name}`形式確認

## 関連ドキュメント

- @vibes/rules/coding_standards.md
