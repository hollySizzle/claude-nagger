# 開発コマンド

```bash
# テスト実行
python3 -m pytest tests/ -v

# 特定テスト
python3 -m pytest tests/test_xxx.py -v
python3 -m pytest tests/ -k "keyword" -v

# カバレッジ
python3 -m pytest --cov=src --cov-report=term-missing
```
