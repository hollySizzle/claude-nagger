# トラブルシューティング

## クイック診断

```bash
# 環境情報・設定の一括確認
claude-nagger diagnose
```

---

## よくある問題

### 1. フックが実行されない

**症状**: 規約メッセージが表示されない

**確認手順**:

```bash
# 1. settings.json にフックが登録されているか確認
cat .claude/settings.json | grep -A 20 "hooks"

# 2. フックスクリプトが存在するか確認
ls -la .claude-nagger/

# 3. Python が実行可能か確認
which python3
python3 --version
```

**解決策**:
- `claude-nagger install-hooks --force` で再インストール
- `.claude/settings.json` のパスが正しいか確認

---

### 2. "command not found" エラー

**症状**: `claude-nagger: command not found`

**確認手順**:

```bash
# インストール確認
pip show claude-nagger

# PATHの確認
echo $PATH
which claude-nagger
```

**解決策**:
```bash
# pipx でインストール（推奨）
pipx install claude-nagger

# または pip --user
pip install --user claude-nagger
export PATH="$HOME/.local/bin:$PATH"
```

---

### 3. 設定ファイルが読み込まれない

**症状**: 規約を変更しても反映されない

**確認手順**:

```bash
# YAMLの構文チェック
python3 -c "import yaml; yaml.safe_load(open('.claude-nagger/file_conventions.yaml'))"

# 設定ファイルの内容確認
cat .claude-nagger/config.yaml
```

**解決策**:
- YAMLのインデントを確認（スペース、タブ混在禁止）
- 設定ファイル名のスペルミスを確認

---

### 4. セッション開始フックがブロックし続ける

**症状**: 何度確認しても「プロジェクトセットアップ」メッセージが出る

**確認手順**:

```bash
# セッションファイルの確認
ls -la /tmp/claude/
cat /tmp/claude/claude_nagger_session_*.json
```

**解決策**:
- `/tmp/claude/` のセッションファイルを削除
- `.claude-nagger/config.yaml` の `session_startup.enabled` を `false` に変更

---

### 5. パターンマッチが機能しない

**症状**: 特定ファイルで規約が表示されない

**確認手順**:

```bash
# パターンテスト（Pythonで確認）
python3 << 'EOF'
import fnmatch
pattern = "**/*.css"
path = "src/styles/main.css"
print(f"Match: {fnmatch.fnmatch(path, pattern)}")
EOF
```

**解決策**:
- グロブパターンの構文を確認
- `**/*.css` は再帰的マッチ、`*.css` はカレントのみ

---

## ログの確認

### フック実行ログ

```bash
# ログファイルの場所
ls /tmp/claude/

# 最新ログの確認
tail -f /tmp/claude/claude_nagger_*.log
```

### デバッグモードの有効化

`.claude-nagger/config.yaml`:
```yaml
debug:
  enable_logging: true
```

---

## 環境情報の収集

issue報告時に以下を含めてください:

```bash
# 診断コマンド（推奨）
claude-nagger diagnose

# 手動収集
echo "=== OS ===" && uname -a
echo "=== Python ===" && python3 --version
echo "=== claude-nagger ===" && claude-nagger --version
echo "=== settings.json ===" && cat .claude/settings.json
echo "=== config.yaml ===" && cat .claude-nagger/config.yaml
```

---

## サポート

- [GitHub Issues](https://github.com/vibes/claude_nagger/issues) - バグ報告
- [GitHub Discussions](https://github.com/vibes/claude_nagger/discussions) - 質問・議論
