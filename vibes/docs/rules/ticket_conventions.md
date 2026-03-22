# チケット起票規約

PMOがチケットCRUD時に参照する起票基準・description規約。

## 階層構造

Epic → Feature → UserStory → Task/Bug/Test

- UserStoryに実作業を直接記載しない（Task/Bug/Testに分解）
- subjectは簡潔かつ具体的に（「実装」ではなく機能名を含む）

## Epic新規作成条件（全て満たすこと）

1. 既存Epicに収まらない独立したドメインである
2. 複数Feature（2つ以上）が見込まれる
3. 複数バージョンにまたがる長期ライフサイクルが想定される
4. オーナー承認済みである（Leader経由可）

## Feature新規作成条件（いずれかを満たすこと）

1. 親Epic内で既存Featureと異なる機能領域を扱う
2. 複数US（2つ以上）に分解される規模がある
3. 責任境界の明確化が必要である

## Epic/Feature description規約

- Epic: 「目的・背景・意思決定（該当時）・スコープ」を構造化記載
- Feature: 機能領域・責任範囲の簡潔な説明（1-3文）
- US/Task/Bug/Testの意思決定テンプレート（decision_record.md）はEpic/Featureには適用しない
