"""Rewrite dev_decisions.json from the current code. Run on purpose, from backend/:  python tests/golden_dev/update.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from golden_dev import digest  # noqa: E402

if __name__ == "__main__":
    old = digest.load()["items"] if digest.GOLDEN.exists() else {}
    new = digest.compute()
    digest.write(new)
    moved = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    print("%d decisions, %d changed against the previous file%s" % (len(new), len(moved), (": " + ", ".join(moved[:20])) if moved else ""))
