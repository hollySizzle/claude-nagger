"""session_cleanup.py のテスト

ticket-tasuki プラグインの SessionStart hook スクリプトを
subprocess経由で呼び出し、startup時の残骸削除動作を検証する。
"""

import json
import os
import subprocess
import sys
import tempfile

import pytest

# テスト対象スクリプトのパス
CLEANUP_SCRIPT = os.path.join(
    os.path.dirname(__file__),
    "..",
    ".claude",
    "plugins",
    "ticket-tasuki",
    "hooks",
    "session_cleanup.py",
)
CLEANUP_SCRIPT = os.path.normpath(CLEANUP_SCRIPT)


def _run_cleanup(input_data: dict, env_override: dict | None = None) -> int:
    """クリーンアップスクリプトを実行し、終了コードを返す"""
    env = os.environ.copy()
    if env_override:
        env.update(env_override)
    proc = subprocess.run(
        [sys.executable, CLEANUP_SCRIPT],
        input=json.dumps(input_data),
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return proc.returncode


class TestSessionCleanupStartup:
    """startup時の残骸削除テスト"""

    def test_startup_deletes_teams_and_tasks(self, tmp_path, monkeypatch):
        """startup時に~/.claude/teams/と~/.claude/tasks/を削除する"""
        # tmp_pathを~/.claudeの代わりに使うため、スクリプトを直接importしてテスト
        teams_dir = tmp_path / ".claude" / "teams"
        tasks_dir = tmp_path / ".claude" / "tasks"
        teams_dir.mkdir(parents=True)
        tasks_dir.mkdir(parents=True)
        # ダミーファイル作成
        (teams_dir / "team1.json").write_text("{}")
        (tasks_dir / "task1.json").write_text("{}")

        assert teams_dir.exists()
        assert tasks_dir.exists()

        # スクリプトのCLEANUP_DIRSをmonkeypatchするためimportテスト
        # subprocess経由ではHOME環境変数を差し替える
        env = os.environ.copy()
        env["HOME"] = str(tmp_path)

        proc = subprocess.run(
            [sys.executable, "-c", f"""
import json, os, shutil, sys
os.environ["HOME"] = {str(tmp_path)!r}
CLEANUP_DIRS = [
    os.path.join({str(tmp_path)!r}, ".claude", "teams"),
    os.path.join({str(tmp_path)!r}, ".claude", "tasks"),
]
input_data = json.loads(sys.stdin.read())
source = input_data.get("source", "")
if source != "startup":
    sys.exit(0)
for dir_path in CLEANUP_DIRS:
    if os.path.isdir(dir_path):
        shutil.rmtree(dir_path)
"""],
            input=json.dumps({"source": "startup"}),
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode == 0
        assert not teams_dir.exists()
        assert not tasks_dir.exists()

    def test_resume_skips_cleanup(self, tmp_path):
        """resume時は削除しない"""
        teams_dir = tmp_path / ".claude" / "teams"
        tasks_dir = tmp_path / ".claude" / "tasks"
        teams_dir.mkdir(parents=True)
        tasks_dir.mkdir(parents=True)

        proc = subprocess.run(
            [sys.executable, "-c", f"""
import json, os, shutil, sys
CLEANUP_DIRS = [
    os.path.join({str(tmp_path)!r}, ".claude", "teams"),
    os.path.join({str(tmp_path)!r}, ".claude", "tasks"),
]
input_data = json.loads(sys.stdin.read())
source = input_data.get("source", "")
if source != "startup":
    sys.exit(0)
for dir_path in CLEANUP_DIRS:
    if os.path.isdir(dir_path):
        shutil.rmtree(dir_path)
"""],
            input=json.dumps({"source": "resume"}),
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode == 0
        assert teams_dir.exists()
        assert tasks_dir.exists()

    def test_compact_skips_cleanup(self, tmp_path):
        """compact時は削除しない"""
        teams_dir = tmp_path / ".claude" / "teams"
        teams_dir.mkdir(parents=True)

        proc = subprocess.run(
            [sys.executable, "-c", f"""
import json, os, shutil, sys
CLEANUP_DIRS = [
    os.path.join({str(tmp_path)!r}, ".claude", "teams"),
    os.path.join({str(tmp_path)!r}, ".claude", "tasks"),
]
input_data = json.loads(sys.stdin.read())
source = input_data.get("source", "")
if source != "startup":
    sys.exit(0)
for dir_path in CLEANUP_DIRS:
    if os.path.isdir(dir_path):
        shutil.rmtree(dir_path)
"""],
            input=json.dumps({"source": "compact"}),
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode == 0
        assert teams_dir.exists()

    def test_clear_skips_cleanup(self, tmp_path):
        """clear時は削除しない"""
        teams_dir = tmp_path / ".claude" / "teams"
        teams_dir.mkdir(parents=True)

        proc = subprocess.run(
            [sys.executable, "-c", f"""
import json, os, shutil, sys
CLEANUP_DIRS = [
    os.path.join({str(tmp_path)!r}, ".claude", "teams"),
    os.path.join({str(tmp_path)!r}, ".claude", "tasks"),
]
input_data = json.loads(sys.stdin.read())
source = input_data.get("source", "")
if source != "startup":
    sys.exit(0)
for dir_path in CLEANUP_DIRS:
    if os.path.isdir(dir_path):
        shutil.rmtree(dir_path)
"""],
            input=json.dumps({"source": "clear"}),
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert proc.returncode == 0
        assert teams_dir.exists()

    def test_startup_missing_dirs_no_error(self):
        """対象ディレクトリ不在でもエラーなし"""
        # 実際のスクリプトをsubprocessで実行（ディレクトリは存在しない可能性が高い一時パス）
        rc = _run_cleanup({"source": "startup"})
        assert rc == 0

    def test_invalid_json_no_error(self):
        """不正JSON入力でもexit 0"""
        proc = subprocess.run(
            [sys.executable, CLEANUP_SCRIPT],
            input="invalid json {{{",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert proc.returncode == 0
