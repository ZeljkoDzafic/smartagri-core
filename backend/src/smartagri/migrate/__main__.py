"""python -m smartagri.migrate up|status  (spec 052). Uses DATABASE_URL (else the SQLite file of SMARTAGRI_DB)."""
from __future__ import annotations

import argparse
import json
import logging
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m smartagri.migrate")
    parser.add_argument("command", choices=["up", "status"])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    from ..store import make_store
    from . import status, up
    store = make_store(migrate=False)
    try:
        if args.command == "up":
            out = up(store)
            print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
        rows = status(store)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                print("%-18s %-10s %-26s %s" % (r["version"], r["state"], r["applied_at"] or "-", r["name"]))
        return 1 if any(r["state"] in ("pending", "changed") for r in rows) else 0
    finally:
        store.close()


if __name__ == "__main__":
    sys.exit(main())
