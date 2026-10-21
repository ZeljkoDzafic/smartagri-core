"""Versioned schema migrations (spec 052, audit DATA-1/DATA-2).

The schema is a document store (store.TABLES / store.INDEXES) whose DDL has always been idempotent. This runner adds
what was missing around it, without changing the resulting schema:

- a `schema_migrations` table recording what ran (version, name, kind, checksum, applied_at);
- one run at a time: a PostgreSQL session advisory lock (several API replicas and the worker may start together;
  SQLite: the store lock);
- `0001_baseline`: today's idempotent DDL, applied once (on an existing database it changes nothing);
- `R:schema_sync`: a repeatable step that re-applies the idempotent DDL only when its checksum (TABLES, INDEXES and
  the backend extras) changes, so additive changes of later specs keep working as before. Anything that is not
  additive (type change, rename, NOT NULL, backfill) must be a new numbered entry in VERSIONS;
- startup data tasks (`D:*`: orphan parcels to the demo organisation, spec 011; default farms and field crops,
  spec 027) run after the schema under the same lock. They are idempotent and run on every `up`, exactly as they did
  in the API lifespan, but never concurrently.

CLI: `python -m smartagri.migrate up|status`.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("agrovid.migrate")

TABLE = "schema_migrations"
DDL = ("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, name TEXT NOT NULL, "
       "kind TEXT NOT NULL, checksum TEXT, applied_at TEXT NOT NULL)")


def _baseline(store: Any) -> None:
    store.sync_schema()


# (version, name, function(store)). Append only; never edit or reorder an applied entry.
VERSIONS: List[Tuple[str, str, Callable[[Any], None]]] = [
    ("0001", "baseline: document tables, key columns, indexes (idempotent DDL of specs 001-031)", _baseline),
    ("0002", "parcel jurisdiction back-fill: country, subdivision, time zone, climate class (spec 037)",
     lambda store: _jurisdiction_037(store)),
    ("0003", "analyses, analysis events, reference datasets and their events (spec 032; additive tables only)",
     lambda store: store.sync_schema()),
    ("0005", "hourly weather and station observations (typed, monthly partitions on PostgreSQL), stations, risk runs "
             "(specs 035 and 034; additive tables only)", lambda store: _weather_035(store)),
    ("0006", "cadastral import jobs and cache, index layer rasters, validation samples, feature layers, spatial results "
             "(specs 048, 049, 050; additive tables only)", lambda store: store.sync_schema()),
    ("0007", "subscriptions, billing profiles, billing events, invoice mirror, entitlement overrides and events, usage "
             "counters, active parcel selection, coupons (spec 058; additive tables only)", lambda store: store.sync_schema()),
    ("0008", "custom crops of an organisation (spec 059; additive table only)", lambda store: store.sync_schema()),
    ("0009", "tasks and task events (spec 044), inventory products, locations, lots, movements and events (spec 045; "
             "additive tables only)", lambda store: store.sync_schema()),
    ("0010", "imagery scene catalogue and true-colour images (spec 040; additive tables only)",
     lambda store: store.sync_schema()),
    ("0011", "plant-protection registry: sources, imports, products, uses, groups, import events, EU substances, merge "
             "decisions, proposals, guidance objects and append-only guidance events (spec 051; additive tables, "
             "append-only triggers)", lambda store: _ppp_051(store)),
    ("0012", "machinery imports, datasets and point columns (spec 043), boundary suggestions (spec 046; additive tables "
             "only)", lambda store: store.sync_schema()),
    ("0013", "messaging channel links, link codes, delivery log, inbound deduplication and rate-limit counters (spec 060; "
             "additive tables only)", lambda store: store.sync_schema()),
]


APPEND_ONLY_051 = ("ppp_import_events", "ppp_guidance_events")


def _ppp_051(store: Any) -> None:
    """Spec 051: additive tables (store.TABLES), then triggers that refuse UPDATE and DELETE on the append-only audit
    tables (both backends; the single application role owns the tables, so a REVOKE would not bind it)."""
    store.sync_schema()
    for table in APPEND_ONLY_051:
        if store.backend == "postgresql":
            store._exec("CREATE OR REPLACE FUNCTION ppp_append_only() RETURNS trigger LANGUAGE plpgsql AS "
                        "$$ BEGIN RAISE EXCEPTION USING MESSAGE = 'append-only table ' || TG_TABLE_NAME; END $$")
            store._exec("DROP TRIGGER IF EXISTS %s_append_only ON %s" % (table, table))
            store._exec("CREATE TRIGGER %s_append_only BEFORE UPDATE OR DELETE ON %s FOR EACH ROW "
                        "EXECUTE FUNCTION ppp_append_only()" % (table, table))
        else:
            for op in ("UPDATE", "DELETE"):
                store._exec("CREATE TRIGGER IF NOT EXISTS %s_no_%s BEFORE %s ON %s BEGIN "
                            "SELECT RAISE(ABORT, 'append-only table %s'); END" % (table, op.lower(), op, table, table))


def _weather_035(store: Any) -> None:
    store.sync_schema()                       # document tables of specs 034/035 (store.TABLES)
    from ..weather.store import ensure_schema
    ensure_schema(store)                      # time-series tables; partitions are created on demand


def _jurisdiction_037(store: Any) -> None:
    store.sync_schema()                       # the parcels.country_code column must exist before the back-fill
    product = _product()
    if product is not None:                   # research repository: no regions package, nothing to back-fill
        product.jurisdiction_037(store)


# Spec 057 (open core): steps that need product packages live in `product_steps.py`, which the research repository
# does not ship. It is found by name, never imported statically, so the research core never depends on the product.
PRODUCT_STEPS = "smartagri.migrate.product_steps"


def _product() -> Any:
    try:
        return importlib.import_module(PRODUCT_STEPS)
    except ModuleNotFoundError as exc:
        if exc.name != PRODUCT_STEPS:         # the module exists but one of its own imports is missing: a real error
            raise
        return None


def schema_checksum(store: Any) -> str:
    from .. import store as store_mod
    extra = store_mod._pg_schema() if store.backend == "postgresql" else store_mod._sqlite_schema()
    blob = json.dumps({"tables": store_mod.TABLES, "indexes": store_mod.INDEXES, "backend": extra}, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _applied(store: Any) -> Dict[str, Dict[str, Any]]:
    rows = store._rows("SELECT version, name, kind, checksum, applied_at FROM schema_migrations ORDER BY version")
    return {r["version"]: dict(r) for r in rows}


def _record(store: Any, version: str, name: str, kind: str, checksum: Optional[str]) -> None:
    store._exec(store._q("DELETE FROM schema_migrations WHERE version = ?"), (version,))
    store._exec(store._q("INSERT INTO schema_migrations (version, name, kind, checksum, applied_at) "
                         "VALUES (?, ?, ?, ?, ?)"), (version, name, kind, checksum, _now()))


def schema_up(store: Any) -> List[str]:
    """Apply pending versioned migrations and the schema sync under the migration lock; returns what ran."""
    ran: List[str] = []
    with store.migration_lock():
        store._exec(DDL)
        done = _applied(store)
        for version, name, fn in VERSIONS:
            if version in done:
                continue
            log.info("migration %s: %s", version, name)
            fn(store)
            _record(store, version, name, "versioned", None)
            ran.append(version)
        checksum = schema_checksum(store)
        sync = done.get("R:schema_sync")
        if sync is None or sync.get("checksum") != checksum:
            if "0001" in done:                        # a fresh database was just built by 0001 from the same DDL
                store.sync_schema()
            _record(store, "R:schema_sync", "repeatable: idempotent DDL of store.TABLES/INDEXES", "repeatable", checksum)
            ran.append("R:schema_sync")
    return ran


DATA_TASKS: List[Tuple[str, str, Callable[[Any, Any], Any]]] = list(getattr(_product(), "DATA_TASKS", []))


def up(store: Any, svc: Any = None) -> Dict[str, Any]:
    """Schema migrations, then the startup data tasks, all under one migration lock (safe with several replicas)."""
    out: Dict[str, Any] = {"schema": schema_up(store), "data": {}}
    with store.migration_lock():
        for key, name, fn in DATA_TASKS:
            out["data"][key] = fn(store, svc)
            _record(store, key, name, "data", None)
    return out


def status(store: Any) -> List[Dict[str, Any]]:
    """Every known step with its state: applied (with time), pending, or changed (schema sync checksum differs)."""
    store._exec(DDL)
    done = _applied(store)
    rows: List[Dict[str, Any]] = []
    for version, name, _ in VERSIONS:
        rec = done.get(version)
        rows.append({"version": version, "name": name, "kind": "versioned",
                     "state": "applied" if rec else "pending", "applied_at": rec and rec["applied_at"]})
    rec = done.get("R:schema_sync")
    current = schema_checksum(store)
    rows.append({"version": "R:schema_sync", "name": "repeatable: idempotent DDL of store.TABLES/INDEXES",
                 "kind": "repeatable", "applied_at": rec and rec["applied_at"],
                 "state": "pending" if not rec else ("applied" if rec.get("checksum") == current else "changed")})
    for key, name, _ in DATA_TASKS:
        rec = done.get(key)
        rows.append({"version": key, "name": name, "kind": "data", "applied_at": rec and rec["applied_at"],
                     "state": "last run" if rec else "never run"})
    return rows
