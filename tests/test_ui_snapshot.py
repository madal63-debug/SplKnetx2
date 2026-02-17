from __future__ import annotations

import difflib
import json
import sys
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
  sys.path.insert(0, str(ROOT_DIR))


class UISnapshotTest(unittest.TestCase):
  def test_ui_snapshot_matches_baseline(self) -> None:
    try:
      from tools.ui_snapshot_dump import dump_ui_snapshot
    except ModuleNotFoundError as exc:
      self.skipTest(f"Missing runtime dependency: {exc}")

    baseline_path = ROOT_DIR / "docs" / "UI_SNAPSHOT_BASELINE.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    current = dump_ui_snapshot()

    if current != baseline:
      expected = json.dumps(baseline, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
      actual = json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False).splitlines()
      diff = "\n".join(
        difflib.unified_diff(
          expected,
          actual,
          fromfile="docs/UI_SNAPSHOT_BASELINE.json",
          tofile="current_ui_snapshot",
          lineterm="",
          n=2,
        )
      )
      self.fail(f"UI snapshot differs from baseline.\n{diff}")


if __name__ == "__main__":
  unittest.main()
