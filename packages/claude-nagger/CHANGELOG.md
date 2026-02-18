# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

## [2.5.0] - 2026-02-18

### Added
- Redmine操作Discord通知フック — PostToolUseで全Redmine MCPツール操作をDiscord転送 (issue_6257)
  - RedmineDiscordHookクラス新規作成 (issue_6258)
  - CLI `hook redmine-discord` サブコマンド (issue_6259)
  - install_hooks.py PostToolUse登録 (issue_6260)
  - ツール種別別メッセージフォーマット（コメント/ステータス/作成/更新/その他）
  - チケットURLリンク（Markdown hyperlink）付与
  - secrets.yaml直接読み込み方式でwebhook_url取得
- CONFIG_TEMPLATEにnotifications.discordセクション追加 (issue_6269)

### Changed
- init-firewall.sh allowlistにdiscord.com追加 (issue_6269)

## [2.4.1] - 2026-02-17

### Changed
- suggest_rules機能のデフォルトをON→OFFに変更 — 明示的enabled設定が必要 (issue_6229)

## [2.4.0] - 2026-02-17

### Added
- mcp_conventions基本実装 — YAML定義・ツール名マッチ・hook統合 (issue_6168)
- mcp_conventions input_match拡張 — tool_inputフィールド条件マッチ (issue_6169)
- トランスクリプトDB保存: raw mode基本実装 (issue_6174)
- トランスクリプトDB保存: indexed/structured mode拡張とサマリカラム追加 (issue_6175)
- SubagentStop時のsubagentトランスクリプト即時DB格納 (issue_6184)
- config.yamlにtranscript_storageセクション追加 (issue_6190)
- suffix除去ロジック実装・ROLEパターン正規表現修正 (issue_6172)
- task_spawn_guardテスト追加・既存テスト更新 (issue_6218)

### Changed
- check_command/check_fileを全ルール評価方式に変更 (issue_6115)
- CLAUDE_PROJECT_DIR環境変数を優先したconfig.yaml探索に統一 (issue_6188)
- config.yaml探索に__file__ベースのパッケージルートフォールバックを追加 (issue_6189)
- hook整理 — settings.jsonからhooksセクション削除、redmine_guard撤廃 (issue_6205)
- プラグイン開発ワークフローをplugin_development.yamlに統合 (issue_6187)
- docs/rules → vibes/docs/rules 移動・全参照更新 (issue_6152)
- editable installパスを/tmp→/workspaceに修正 (issue_6186)
- EXDEV修正(TMPDIR追加) (issue_6178)
- テスト修正: tempdir参照の環境非依存化、期待値の実装追従

### Removed
- leader_constraint_hook削除 — ticket-tasukiに移管 (issue_6170, issue_6217)
- leader_constraint_hook残留参照の完全削除 (issue_6194)
- redmine_guard撤廃 (issue_6205)

## [2.3.1] - 2026-02-12

### Added
- ticket-tasukiプラグインhook: task_spawn_guard, redmine_guard (issue_6093, issue_6118)
- task_spawn_guard, redmine_guardのテスト追加 (issue_6102, issue_6103)

### Changed
- 全hookブロックメッセージに `[claude-nagger]` プレフィックス付与 (issue_6100)
- conventions YAML規約エントリ追記 (issue_6099)

## [2.3.0] - 2026-02-11

### Added
- SendMessageGuardHook 新規作成 — SendMessage通信時のissue_idパターン強制ガード (issue_6046)
- sendmessage_guard の CLI/settings.json/config.yaml 統合 (issue_6047)
- LeaderConstraintHook 新規作成 — subagent存在時のleader直接作業ブロック (issue_6059)
- TaskSpawnGuardHook 新設 — ticket-tasuki:* 直接起動ブロック + team_name許可 (issue_6093)
- subagent_historyテーブル新設・ライフサイクルログ記録 (issue_6089)
- session_startupに前回セッションsubagent履歴サマリ表示を追加 (issue_6094, issue_6095)
- SKILL.md拡張 — 4ロール委譲テンプレート埋め込み (issue_6062)
- block_messageカスタマイズ対応 (issue_6056)
- CHANGELOG.md新規作成 — 全リリース履歴を網羅

### Changed
- Leader規約を方式E（Agent Teams + sendmessage_guard）前提に更新 (issue_6049)
- leader/subagent transcript_path区別によるブロッキング対象修正 (issue_6057)
- base_hookセッション管理リファクタリング — should_skip_session切り出し (issue_5933)
- cleanup_sessionのsubagent_historyコピー対応 (issue_6090)
- README.md充実化 — PyPIパッケージ説明文として利用可能な内容に更新 (issue_6093)

## [2.2.0] - 2026-02-09

### Added
- researcherカスタムagent定義を追加 (issue_6005)
- .claude-nagger/.gitignore自動生成を追加 (issue_6018)
- 各agent.mdにチケットコメント規約を追加 (issue_6015)
- ticket-tasukiプラグイン統合・gitignore整備

### Changed
- Leader向けセッション開始メッセージをカスタムagent方式に対応 (issue_6015)
- session_startupメッセージの委譲先をカスタムagent名に変更 (issue_6006)
- config.yaml subagent規約の重複排除・agent.md権威化 (issue_6015)

### Fixed
- suggested_rulesファイル爆発問題の修正 (issue_5964)
- DEFAULT_LOG_DIR参照をself.log_dirに統一 (issue_5964)

## [2.1.31] - 2026-02-04

### Added
- NaggerStateDB + データモデル実装 (issue_5938)
- HookLogRepository実装 (issue_5941)
- SubagentRepository, SessionRepository実装 (issue_5939, issue_5940)
- NaggerStateDB + Repository群のテスト実装 (issue_5943)
- TTL機能テスト・SQL日時比較修正 (issue_5955)
- SubagentRepositoryのカバレッジ66%→94%向上 (issue_5955)
- suggested_rules通知後のhook_inputクリア処理実装 (issue_5964)

### Changed
- Hook統合 — 全hookの新DB移行 (issue_5942)
- agent_progressイベントを使用したROLEマッチング修正 (issue_5947)
- ハイブリッドアプローチ（案D簡易版）の実装 (issue_5947)
- hook重複登録の解消・PYTHONPATH版削除 (issue_5951)

### Removed
- 旧SubagentMarkerManager削除 + クリーンアップ (issue_5944)

### Fixed
- suggested_rulesファイル爆発問題の修正 (issue_5963)

## [2.1.30] - 2026-02-02

### Added
- Conductor用promptテンプレート作成 (issue_5834)
- conductor role config/テスト/結合テスト/README追加 (issue_5855)
- hook間連携テスト整備・testing.yaml改善 (issue_5873)

### Changed
- config.yaml Conductorパターン対応 — Leader最小化・role規約詳細化 (issue_5859)
- CONFIG_TEMPLATEのsubagent overridesを有効状態に拡張 (issue_5860)
- SubagentStartでagent_transcript_pathからROLE解析を実装 (issue_5862)
- base_hookバイパス + 親transcript ROLE解析 (issue_5862)
- is_session_processed_context_aware無条件バイパス復元 (issue_5862)
- subagentマーカー構造統合・role識別対応 (issue_5825)
- ticket-tasukiプラグイン登録 + SubagentStart/Stop hook追加 (issue_5785)
- 再発防止策 — CI同期チェック・アーキテクチャ制約・テスト規約・hook開発規約 (issue_5862)

## [2.0.73] - [2.1.29] (2025-12-19 〜 2026-01-31)

upstream（claude-code）との同期リリース。claude-nagger固有の機能変更なし。

## [1.7.0] - 2026-02-02

### Changed
- subagentマーカー構造統合・role識別対応 (issue_5825)
- ticket-tasukiプラグイン登録 + SubagentStart/Stop hook追加 (issue_5785)

## [1.6.1] - 2026-02-02

### Added
- install-hooks CONFIG_TEMPLATEにsubagent overridesサンプル追加 (issue_5789)
- config.yaml: subagent overridesの仕組みコメント追加
- テスト関連のconvention hook設定追加 (issue_5782)

### Changed
- devcontainerビルド時にdev依存を自動インストール (issue_5783)

## [1.6.0] - 2026-02-01

### Added
- ticket-tasukiプラグイン初期構築 — REQ-1〜4 (issue_5730)
- session_startupにleader規約追加 — コード編集禁止・coder委譲・レビュー必須 (issue_5730)
- coder規約にコミットメッセージ[coder]プレフィックスルール追加 (issue_5772)
- leader規約にRedmineコメント実行者マーカー記載ルール追加 (issue_5773)
- ticket-manager→scribeリネーム、tester subagent追加 (issue_5774)
- フィクスチャリプレイによるsession_startup_hookのE2Eテスト追加 (issue_5779)
- claude-naggerテスト仕様書を作成 (issue_5779)

### Changed
- ticket-managerをticket-tasukiプラグインに移動 (issue_5730)
- SubagentMarkerManagerのBASE_DIRをUID付きパスに統一 (issue_5736)
- Claude Codeインストールをnpmからネイティブインストーラに変更 (issue_5739)
- BaseHook.output_response()のhookEventNameを動的に解決 (issue_5778)
- subagent_types設定の名前空間付きagent_typeマッチング対応 (issue_5779)
- ticket-tasukiを独立リポジトリに分離

### Fixed
- main()を最外try/exceptで囲み予期せぬ例外のstderr漏れを防止 (issue_5720)

## [1.5.0] - 2026-02-01

### Added
- hook入力JSON分析エンジン（RuleSuggester）実装 (issue_5621)
- suggest-rules CLIコマンド実装 (issue_5622)
- Stop hook自動トリガー + Claude subagent連携 (issue_5623)
- SessionStartupHookにsuggested_rules通知機能追加 (issue_5624)
- SessionStartup hookのsub-agent別override機構実装 (issue_5620)
- subagent判別フィールド技術検証・hook基盤改善 (issue_5619)
- SubagentStart/Stopフック登録とCLIコマンド追加 (issue_5708)

### Changed
- MD5からSHA256への移行 (issue_5334)
- /tmpパスのハードコード解消 (issue_5333)
- _merge_contained_patternsの推移的マージ対応 (issue_5648)
- _fallback_yamlの件数制限を合計10件に統一 (issue_5623)

## [1.4.2] - 2026-01-20

### Fixed
- 例外の握りつぶし解消: log出力追加 (issue_5332)

### Changed
- テストカバレッジ改善: matcher系ファイル (issue_5331)
- ログ設定統一: structured_logging活用 (issue_5331)

## [1.4.1] - 2026-01-19

### Changed
- README.mdにcompact検知機能(v1.4.0)を追加

## [1.4.0] - 2026-01-19

### Added
- CompactDetectedHook: SessionStart[compact]イベント処理フック追加 (issue_5289)
- install_hooks: SessionStart[compact]設定追加 (issue_5291)
- CLI: hook compact-detectedサブコマンド追加 (issue_5293)
- MarkerPatterns: マーカーパターンの一元管理クラス追加 (issue_5314)

### Changed
- CompactDetectedHook: 履歴保存→マーカーリセット方式に変更 (issue_5289)
- CompactDetectedHook: 削除→リネーム方式に変更 (issue_5295)
- トークン閾値判定からabs()削除 + ログディレクトリUID固有化 (issue_5287)

## [1.3.10] - 2026-01-11

### Changed
- バージョン管理の単一ソース化: importlib.metadata採用 (issue_4560)

## [1.3.7] - [1.3.9] (2026-01-11)

### Fixed
- GitHub Actions publish.yml パス修正 (v1.3.8)
- CI用README.mdコピー方式に変更 (v1.3.9)

### Added
- hookSpecificOutput形式の完全対応: HookResponse型 + 新出力メソッド (issue_4474)
- permission_modeによるスマートスキップ実装 (issue_4475)
- 基盤刷新: ExitCode enum + 環境変数プロパティ追加 (issue_4517)
- 契約テスト強化: ask decision、全イベント名、終了コード、permission_mode対応 (issue_4516)

### Changed
- デバッグ機能改善: 構造化ログ・出力先統一・デバッグモード検出 (issue_4477)
- TestCLIIntegration: python -m実行に変更し環境非依存化 (issue_4548)
- テストPYTHONPATH明示設定で環境非依存化 (issue_4556)
- README配置整理: hatchlingでルート参照 (issue_4555)

## [1.3.6] - 2026-01-06

### Added
- match-test dry-runコマンド追加 (issue_4075)

### Fixed
- FileConventionMatcher: 絶対パス→相対パス変換対応 (issue_4074)

## [1.3.5] - 2026-01-06

### Changed
- READMEにPATH設定手順を追記 (issue_4064)

## [1.3.4] - 2026-01-06

### Changed
- BaseHook.output_response()を公式スキーマに準拠 (issue_4062)

## [1.3.3] - 2026-01-06

### Fixed
- discord_notifier.pyの相対インポートを絶対インポートに修正

## [1.3.2] - 2026-01-06

### Added
- Discord通知用CLIサブコマンド追加 (issue_4044)

## [1.3.1] - 2026-01-05

### Added
- Edit/Write/MultiEdit matcherをDEFAULT_PRETOOLUSE_HOOKSに追加
- GLOBSTARパターン記法のドキュメント・テスト追加 (issue_4046)

## [1.3.0] - 2026-01-05

### Added
- install_hooksにBash用matcher追加 (issue_4032)
- CONFIG_TEMPLATEにrepeated設定を追加 (issue_4029)

### Changed
- diagnoseコマンド診断機能強化 (issue_4033)

## [1.2.0] - 2026-01-05

### Changed
- フック実行方式をサブコマンド形式に変更 (issue_4020)

### Added
- release.shスクリプト追加 (issue_4016)

## [1.1.0] - 2026-01-05

### Added
- install-hooksにNotification/Stopフック設定追加 (issue_4009)
- 開発用インストールスクリプト追加 (issue_4012)
- install-hooks実行時の既存フックスキップ通知追加 (issue_4001)
- フック実行時の設定ファイル自動生成機能 (issue_3910)
- secrets管理をvaultディレクトリに移行 (issue_3984)
- .claude-nagger/config.yaml 優先読み込み対応 (issue_3974)
- issue報告テンプレート・トラブルシュート手順整備 (issue_3962)

### Changed
- install-hooksのフック呼び出しパスをモジュール形式に修正 (issue_3998)
- テストカバレッジ46%→80%向上 (issue_3915, issue_3975)

## [1.0.1] - 2026-01-05

### Fixed
- PyPI publish workflow修正

## [1.0.0] - 2026-01-05

初回リリース。

### Added
- install-hooksコマンド実装 (issue_3835)
- ConfigManager YAML対応実装 (issue_3890)
- FileConventionMatcher: wcmatch導入で**パターン対応 (issue_3873)
- .claude-nagger/設定読み込み対応 (issue_3843)
- Claude Code結合テスト自動化・規約YAML化 (issue_3848)
- PyPI公開準備 (issue_3838)
- README.md全面改訂 (issue_3839)
