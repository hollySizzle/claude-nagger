# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## プロジェクト規約

## 作業開始前チェック

[ ] @vibes/INDEX.md を参照した
[ ] 関連ドキュメントを確認した  
[ ] 不明点をユーザ(指示者)に質問し解消した

## プロジェクト概要

- **目的**:
- **技術スタック**:
- **ワークスペース**:

## アーキテクチャ概要

### バックエンド

### フロントエンド (React)

### 統合ポイント

## 重要な制約事項

### 絶対的禁止事項

## 推奨ワークフロー: **Explore→Plan→Code→Verify**

- **Explore**: "think hard"で設計書確認・影響範囲特定
- **Plan**: 実装方針明文化・機能 ID 対応確認
- **Code**: 最小単位実装 → テスト → 改善サイクル
- **Verify**: 自動チェック・設計書準拠性確認

## 基本方針

**設計思想**: 外部設計 → 内部設計 → 実装
**BDD 原則**: [TODO: BDD 実装言語] DSL による実行可能ドキュメント
**TDD 遵守**: Red → Green → Refactor

**AI 思考レベル**: "think hard"(設計書確認)、"think harder"(アーキテクチャ変更)
詳細手順: @vibes/docs/tasks/development_workflow_guide.md

## コマンド

```bash
# ドキュメント管理
cd vibes/scripts
npm run update-toc                      # 目次更新
npm run check-references                # 参照整合性チェック
npm run generate-document               # 新規ドキュメント生成
npm run doc-help                        # ドキュメント生成ヘルプ
```

## 品質・セキュリティ基準

### コード品質

- **ESLint 準拠必須**：JavaScript/JSX コードの静的解析
- **テスト必須**：新機能は必ずテスト実装（現在テストインフラ未整備）
- **コメント日本語**: コードのコメントは日本語であること
- **クリーンアーキテクチャ**: app/adapters, app/domain, app/usecases の構造（現在未実装）
- **緩やかな DRY 原則**: DRY 原則は適用しつつ､過剰な抽象化は避け､最小限の反復とする

## エラー対応・作業完了基準

### エラー発生時

1. **設計書整合性確認**：まず設計書との差分確認
2. **ユーザ報告**：不明事項は推測せずユーザ確認
3. **バックアップ確認**：重要データ操作前は必ずバックアップ

### 作業完了チェック

- [ ] テスト成功確認（テストインフラ整備後）
- [ ] **設計書準拠性自動チェック実行**
- [ ] ESLint・品質チェック完了
- [ ] ドキュメント更新完了
- [ ] Redmine プラグインの動作確認

**設計書準拠確認**: 機能 ID 存在・シーケンス図一致・未定義機能追加なし・権限整合性
詳細: @vibes/rules/design_compliance_standards.md

## ドキュメント

**重要**

- ドキュメントは､簡潔かつ記載漏れのない圧縮言語で記載する
  - 専門用語の活用/簡潔な文章表現/情報の集約/繰り返しを避ける 等を実行すること
- 作成ルールに従うこと
  - **重要** : 手動でドキュメントを作成せず､自動生成ツールを使用すること
  - @vibes/INDEX.md を確認し新規ドキュメントの必要性を再考
  - 新規作成(`npm run generate-document`)
  - ガイドラインの確認(@vibes/docs/rules/documentation_standards.md)
  - 目次更新(`npm run update-toc`)
  - 参照整合性チェック(`npm run check-references`)

### vibes/docs ディレクトリ構成

- **apis**: 外部サービスの前提条件（原則変更不可）
- **logics**: ビジネスロジック記載
- **rules**: プロジェクト規約・制約事項
- **tasks**: 作業手順書・ガイド
- **specs**: ドメイン仕様（ビジネスロジック非依存）
- **temps**: 一時ドキュメント・チェックリスト
