#!/usr/bin/env python3
"""SubagentStart/SubagentStop イベントのhook入力JSONキャプチャ

settings.jsonのSubagentStart/SubagentStopフックから呼び出される。
stdinのJSONを/tmp/claude_subagent_event/に保存する。
処理をブロックしないよう終了コード0で終了する。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = Path("/tmp/claude_subagent_event")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        data = {"_raw": raw, "_error": "JSONDecodeError"}

    # イベント名をファイル名に含める
    event_name = data.get("hook_event_name", "unknown")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{event_name}_{timestamp}.json"

    filepath = OUTPUT_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 処理をブロックしない
    sys.exit(0)


if __name__ == "__main__":
    main()
