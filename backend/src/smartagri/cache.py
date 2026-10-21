"""Export and import a snapshot of the external cache for the protocol lock (see docs/architecture.md).

    python -m smartagri.cache export [--out eval/cache_snapshot_<date>.tar]
    python -m smartagri.cache import <snapshot.tar>

The tar holds `entries.jsonl` (one cache entry per line, ordered by request_hash) and
`manifest.json` with the sha256 of `entries.jsonl`, the entry count and per-provider counts.
Tar members carry fixed metadata, so the same cache content always gives the same tar bytes; the
tar's own sha256 is written next to it as `<file>.sha256` and printed for the protocol lock.
Import verifies the manifest hash (and the .sha256 file when present) before writing anything.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .store import Store, make_store

FORMAT = "smartagri-cache-snapshot/1"


def default_path() -> Path:
    return Path(__file__).resolve().parents[2] / "eval" / ("cache_snapshot_%s.tar" % date.today().isoformat())


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _member(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = len(data), 0, 0o644, 0, 0, "", ""
    tar.addfile(info, io.BytesIO(data))


def export_snapshot(store: Store, out: Path) -> Dict[str, Any]:
    entries = store.cache_entries()
    body = "".join(json.dumps(e, sort_keys=True, ensure_ascii=False) + "\n" for e in entries).encode("utf-8")
    manifest = {"format": FORMAT, "entries": len(entries), "entries_sha256": _sha256(body),
                "providers": dict(sorted(Counter(e["provider"] for e in entries).items()))}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        _member(tar, "manifest.json", json.dumps(manifest, sort_keys=True, indent=1).encode("utf-8"))
        _member(tar, "entries.jsonl", body)
    data = buf.getvalue()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    digest = _sha256(data)
    Path(str(out) + ".sha256").write_text("%s  %s\n" % (digest, out.name), encoding="utf-8")
    return dict(manifest, path=str(out), sha256=digest)


def read_snapshot(path: Path) -> List[Dict[str, Any]]:
    """Entries of a snapshot after checking its hashes; raises ValueError on any mismatch."""
    data = path.read_bytes()
    side = Path(str(path) + ".sha256")
    if side.exists():
        expected = side.read_text(encoding="utf-8").split()[0]
        if expected != _sha256(data):
            raise ValueError("Snapshot sha256 does not match %s" % side.name)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        manifest = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        body = tar.extractfile("entries.jsonl").read()
    if manifest.get("format") != FORMAT:
        raise ValueError("Unknown snapshot format: %s" % manifest.get("format"))
    if manifest["entries_sha256"] != _sha256(body):
        raise ValueError("entries.jsonl does not match the manifest hash")
    entries = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
    if len(entries) != manifest["entries"]:
        raise ValueError("Entry count does not match the manifest")
    return entries


def import_snapshot(store: Store, path: Path) -> int:
    """Write every entry with its original fetched_at; existing entries with the same hash are replaced."""
    entries = read_snapshot(path)
    for e in entries:
        store.cache_put(e["request_hash"], e["provider"], e["request"], e["response"], fetched_at=e["fetched_at"])
    return len(entries)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m smartagri.cache", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export", help="write a snapshot of the external cache")
    ex.add_argument("--out", type=Path, default=None)
    im = sub.add_parser("import", help="load a snapshot into the external cache")
    im.add_argument("path", type=Path)
    args = ap.parse_args(argv)
    store = make_store()
    if args.cmd == "export":
        info = export_snapshot(store, args.out or default_path())
        print("%s  %s  (%d entries: %s)" % (info["sha256"], info["path"], info["entries"],
                                           ", ".join("%s %d" % kv for kv in info["providers"].items()) or "none"))
        return 0
    try:
        n = import_snapshot(store, args.path)
    except (ValueError, KeyError, tarfile.TarError) as exc:
        print("Import refused: %s" % exc, file=sys.stderr)
        return 1
    print("Imported %d entries from %s" % (n, args.path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
