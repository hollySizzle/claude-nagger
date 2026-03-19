# tasukiワークフロー図

## tech-lead peer-to-peerレビューフロー

```mermaid
flowchart TD
    A[coder: issue_id で確認依頼] --> B[tech-lead: Redmineで実装報告確認]
    B --> C[tech-lead: git diff でコード変更確認]
    C --> D{設計整合性・ドキュメント整合性・コード品質}
    D -->|OK| E[Redmineにレビュー承認コメント]
    E --> F["leaderに SendMessage: issue_id 完了"]
    D -->|改善可能な指摘あり| G[Redmineに修正指示コメント]
    G --> H["coderに SendMessage: issue_id 指示"]
    H --> I[coder: 修正実施]
    I --> A
    D -->|設計判断が必要| J[Redmineにエスカレーション理由コメント]
    J --> K["leaderに SendMessage: issue_id 要判断"]

    style F fill:#4a4,color:#fff
    style H fill:#c90,color:#fff
    style K fill:#c33,color:#fff
```

### 重要ルール
- 承認 → **leaderに**報告（coderのタスク完了通知）
- 修正指示 → **coderに**直接送信（leader不介在）
- エスカレーション → **leaderに**送信（設計判断はleader/オーナーの責務）

## PMOワークフロー提案フロー

```mermaid
flowchart TD
    A[leader: タスク概要をpmoに送信] --> B[pmo: チケット情報確認]
    B --> C{コード変更あり?}
    C -->|あり| D[tech-lead常駐 + レビュー必須を提案]
    C -->|なし| E[簡易確認フローを提案]
    D --> F{ドキュメント更新が必要?}
    E --> F
    F -->|あり| G[tech-leadにドキュメント更新を振る]
    F -->|なし| H[ワークフロー確定]
    G --> H
    H --> I[Redmineにワークフロー提案コメント]
    I --> J["leaderに SendMessage: issue_id 完了"]

    style G fill:#36a,color:#fff
    style J fill:#4a4,color:#fff
```

## コミット責務

| role | git commit | git push | 備考 |
|------|-----------|----------|------|
| leader | 許可 | 許可 | 最終検収者。必要に応じてコミット・push実行 |
| tech-lead | 許可 | 許可 | レビュー承認後のコミット担当。coderの変更をレビュー→コミット |
| coder | **禁止** | **禁止** | 実装のみ。コミットはtech-leadまたはleaderが実行 |

### コミットフロー
1. coder: コード変更を実施（コミットしない）
2. tech-lead: レビュー承認後、変更をコミット
3. leader: 必要に応じて最終確認・push

## OK/NG例

### OK: 正しいワークフロー
- coder実装完了 → tech-leadにpeer-to-peerレビュー依頼 → 承認後leaderに完了報告
- ドキュメント更新必要 → tech-leadに振る（tech-leadがvibes/docs編集・コミット）
- 設計判断が必要 → tech-leadがleaderにエスカレーション
- coder実装完了 → tech-leadレビュー承認 → tech-leadがgit commit実行

### NG: 禁止パターン
- **NG**: PMOがcoderにドキュメント修正を指示する（ドキュメント更新はtech-leadの責務）
- **NG**: tech-leadが承認後coderに完了報告する（承認報告先はleader）
- **NG**: coderがleaderを介さずtech-leadにレビュー依頼をスキップする
- **NG**: tech-leadがleaderを介さずPMO/researcherに直接送信する
- **NG**: coderがgit commit/pushを実行する（コミットはtech-lead/leaderの責務）
