"""Storage of hourly weather rows and raw station observations.

Two typed tables outside the generic document store, because they are time series:
  - `weather_hourly`: Open-Meteo hourly rows per grid point, model, hour and issue key (one row per forecast as
    issued; a newer forecast adds rows, the old ones stay as history until retention);
  - `station_observations`: raw station observations per station and observation time (sub-hourly allowed).
PostgreSQL: declarative range partitioning by month on the time column (partitions created on demand before an
insert, dropped by retention), BRIN index on time, the primary key as the btree on (series, time).
SQLite (development, tests): the same columns in plain tables; partition DDL is PostgreSQL-only.
Created by migration 0003 (smartagri.migrate); `ensure_schema` is idempotent.
"""
from __future__ import annotations

import json
import threading
from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

HOURLY_VALUES = ("temp_c", "rh_pct", "dew_point_c", "precip_mm", "wind_ms", "sw_rad_wm2")
HOURLY_COLS = ("grid_key", "model", "ts", "issued_key", "origin", "issued_at", "lead_hours", "fetched_at",
               "source_id") + HOURLY_VALUES
OBS_VALUES = ("temp_c", "rh_pct", "dew_point_c", "precip_mm", "wind_ms", "wind_gust_ms", "wind_dir_deg",
              "sw_rad_wm2", "leaf_wet_min", "leaf_wet_flag")
OBS_COLS = ("station_id", "observed_at", "org_id", "interval_min", "received_at", "source", "api_key_id") + OBS_VALUES
TIME_COLS = {"ts", "issued_at", "fetched_at", "observed_at", "received_at"}
INT_COLS = {"lead_hours", "interval_min", "leaf_wet_flag"}

_partitions_done: set = set()
_lock = threading.Lock()


def _pg_type(col: str) -> str:
    if col in TIME_COLS:
        return "TIMESTAMPTZ"
    if col in INT_COLS:
        return "INTEGER"
    if col in HOURLY_VALUES or col in OBS_VALUES:
        return "DOUBLE PRECISION"
    return "TEXT"


def _sqlite_type(col: str) -> str:
    if col in INT_COLS:
        return "INTEGER"
    if col in HOURLY_VALUES or col in OBS_VALUES:
        return "REAL"
    return "TEXT"


def schema_statements(backend: str) -> List[str]:
    """DDL of both tables for a backend (idempotent)."""
    typ = _pg_type if backend == "postgresql" else _sqlite_type
    jtype = "JSONB" if backend == "postgresql" else "TEXT"
    nn = {"grid_key", "model", "ts", "issued_key", "origin", "station_id", "observed_at"}

    def cols(names):
        return ", ".join("%s %s%s" % (c, typ(c), " NOT NULL" if c in nn else "") for c in names)

    part = " PARTITION BY RANGE (%s)" if backend == "postgresql" else ""
    stmts = [
        "CREATE TABLE IF NOT EXISTS weather_hourly (%s, extra %s, PRIMARY KEY (grid_key, model, ts, issued_key))%s"
        % (cols(HOURLY_COLS), jtype, part % "ts" if part else ""),
        "CREATE TABLE IF NOT EXISTS station_observations (%s, extra %s, qc_flags %s, raw %s, "
        "PRIMARY KEY (station_id, observed_at))%s" % (cols(OBS_COLS), jtype, jtype, jtype, part % "observed_at" if part else ""),
    ]
    if backend == "postgresql":
        stmts += ["CREATE INDEX IF NOT EXISTS weather_hourly_ts_brin ON weather_hourly USING brin (ts)",
                  "CREATE INDEX IF NOT EXISTS station_observations_time_brin ON station_observations USING brin (observed_at)",
                  "CREATE INDEX IF NOT EXISTS station_observations_org_idx ON station_observations (org_id, observed_at)"]
    else:
        stmts += ["CREATE INDEX IF NOT EXISTS weather_hourly_ts_idx ON weather_hourly (ts)",
                  "CREATE INDEX IF NOT EXISTS station_observations_org_idx ON station_observations (org_id, observed_at)"]
    return stmts


def ensure_schema(store: Any) -> None:
    for stmt in schema_statements(store.backend):
        store._exec(stmt)


def month_start(d: date) -> date:
    return date(d.year, d.month, 1)


def next_month(d: date) -> date:
    return date(d.year + (d.month // 12), d.month % 12 + 1, 1)


def partition_name(table: str, month: date) -> str:
    return "%s_p%04d%02d" % (table, month.year, month.month)


def ensure_partitions(store: Any, table: str, stamps: Iterable[str]) -> List[str]:
    """PostgreSQL: create the monthly partitions that the given UTC stamps fall into (once per process). Returns
    the names created or checked; SQLite: nothing."""
    if store.backend != "postgresql":
        return []
    months = {month_start(date.fromisoformat(s[:10])) for s in stamps if s}
    names = []
    for m in sorted(months):
        name = partition_name(table, m)
        key = (id(store), name)
        if key in _partitions_done:
            continue
        store._exec("CREATE TABLE IF NOT EXISTS %s PARTITION OF %s FOR VALUES FROM ('%s 00:00:00+00') TO ('%s 00:00:00+00')"
                    % (name, table, m.isoformat(), next_month(m).isoformat()))
        with _lock:
            _partitions_done.add(key)
        names.append(name)
    return names


def list_partitions(store: Any, table: str) -> List[str]:
    if store.backend != "postgresql":
        return []
    rows = store._rows("SELECT c.relname AS name FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                       "JOIN pg_class p ON p.oid = i.inhparent WHERE p.relname = %s ORDER BY c.relname", (table,))
    return [r["name"] for r in rows]


def is_partitioned(store: Any, table: str) -> bool:
    if store.backend != "postgresql":
        return False
    rows = store._rows("SELECT 1 AS x FROM pg_partitioned_table pt JOIN pg_class c ON c.oid = pt.partrelid "
                       "WHERE c.relname = %s", (table,))
    return bool(rows)


def _utc_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _json_in(store: Any, value: Any) -> Any:
    if value is None:
        return None
    return store._json(value) if store.backend == "postgresql" else json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_out(value: Any) -> Any:
    if value is None:
        return None
    return json.loads(value) if isinstance(value, (str, bytes)) else value


# ------------------------------------------------------------------ weather_hourly

def upsert_hourly(store: Any, grid_key: str, rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Insert Open-Meteo rows; an existing (grid, model, ts, issued_key) is kept (a repeated refresh with the same issue
    adds nothing), except model values of past hours (`issued_key` "past"/"d0"/"archive"), which are updated."""
    if not rows:
        return {"inserted": 0, "updated": 0}
    ensure_partitions(store, "weather_hourly", [r["ts"] for r in rows])
    cols = list(HOURLY_COLS) + ["extra"]
    marks = ", ".join("?" * len(cols))
    updatable = ", ".join("%s = excluded.%s" % (c, c) for c in HOURLY_VALUES + ("fetched_at", "origin"))
    n_new = n_upd = 0
    with store.transaction():
        for r in rows:
            vals = [grid_key if c == "grid_key" else r.get(c) for c in HOURLY_COLS] + [_json_in(store, r.get("extra"))]
            past = r.get("issued_key") in ("past", "d0", "archive")
            if past:
                sql = ("INSERT INTO weather_hourly (%s) VALUES (%s) ON CONFLICT (grid_key, model, ts, issued_key) "
                       "DO UPDATE SET %s" % (", ".join(cols), marks, updatable))
                n_upd += 1
            else:
                sql = ("INSERT INTO weather_hourly (%s) VALUES (%s) ON CONFLICT (grid_key, model, ts, issued_key) "
                       "DO NOTHING" % (", ".join(cols), marks))
                n_new += 1
            store._exec(store._q(sql), vals)
    return {"inserted": n_new, "past_upserted": n_upd}


def hourly_rows(store: Any, grid_key: str, model: str, start: str, end: str) -> List[Dict[str, Any]]:
    sql = ("SELECT %s, extra FROM weather_hourly WHERE grid_key = ? AND model = ? AND ts >= ? AND ts <= ? "
           "ORDER BY ts, issued_key" % ", ".join(HOURLY_COLS))
    out = []
    for r in store._rows(store._q(sql), (grid_key, model, start, end)):
        d = {c: (_utc_text(r[c]) if c in TIME_COLS else r[c]) for c in HOURLY_COLS}
        d["extra"] = _json_out(r.get("extra"))
        out.append(d)
    return out


def count_hourly(store: Any, grid_key: Optional[str] = None) -> int:
    if grid_key:
        rows = store._rows(store._q("SELECT count(*) AS n FROM weather_hourly WHERE grid_key = ?"), (grid_key,))
    else:
        rows = store._rows("SELECT count(*) AS n FROM weather_hourly")
    return int(rows[0]["n"])


def latest_fetch(store: Any, grid_key: str, model: str) -> Optional[str]:
    # the newest live-forecast fetch (archive and previous-runs rows do not make a grid point "fresh")
    rows = store._rows(store._q("SELECT max(fetched_at) AS f FROM weather_hourly WHERE grid_key = ? AND model = ? "
                                "AND (issued_key = 'past' OR issued_key LIKE 'f:%%')"), (grid_key, model))
    return _utc_text(rows[0]["f"]) if rows else None


PAST_KEYS = ("past", "d0", "archive")


def select_series(rows: Sequence[Dict[str, Any]], as_of: datetime) -> Dict[str, Dict[str, Any]]:
    """One Open-Meteo row per hour as known at `as_of` (SC-002):
      - hours at or after as_of: only forecasts with issued_at <= as_of, the newest issue wins (never a value issued
        later, never a model value of a past hour);
      - hours before as_of: the model value of that past hour (`past`/`d0`/`archive`, newest fetch), else the newest
        forecast issued no later than as_of."""
    cut = _utc_text(as_of.astimezone(timezone.utc))
    best: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ts, issued = r["ts"], r.get("issued_at")
        is_past_value = r.get("issued_key") in PAST_KEYS
        if ts >= cut:
            if is_past_value or not issued or issued > cut:
                continue
            rank = (0, issued)
        else:
            if is_past_value:
                rank = (1, r.get("fetched_at") or "")
            elif issued and issued <= cut:
                rank = (0, issued)
            else:
                continue
        cur = best.get(ts)
        if cur is None or rank > cur[0]:
            best[ts] = (rank, r)
    return {ts: dict(v[1]) for ts, v in best.items()}


# ------------------------------------------------------------------ station_observations

def insert_observation(store: Any, obs: Dict[str, Any]) -> bool:
    """Insert one raw observation; False when (station_id, observed_at) already exists (idempotent ingest)."""
    ensure_partitions(store, "station_observations", [obs["observed_at"]])
    cols = list(OBS_COLS) + ["extra", "qc_flags", "raw"]
    vals = [obs.get(c) for c in OBS_COLS] + [_json_in(store, obs.get("extra")), _json_in(store, obs.get("qc_flags") or {}),
                                             _json_in(store, obs.get("raw"))]
    exists = store._rows(store._q("SELECT 1 AS x FROM station_observations WHERE station_id = ? AND observed_at = ?"),
                         (obs["station_id"], obs["observed_at"]))
    if exists:
        return False
    store._exec(store._q("INSERT INTO station_observations (%s) VALUES (%s) ON CONFLICT (station_id, observed_at) "
                         "DO NOTHING" % (", ".join(cols), ", ".join("?" * len(cols)))), vals)
    return True


def update_qc(store: Any, station_id: str, observed_at: str, flags: Dict[str, List[str]]) -> None:
    store._exec(store._q("UPDATE station_observations SET qc_flags = ? WHERE station_id = ? AND observed_at = ?"),
                (_json_in(store, flags), station_id, observed_at))


def observations(store: Any, station_id: str, start: Optional[str] = None, end: Optional[str] = None,
                 limit: Optional[int] = None, newest_first: bool = False) -> List[Dict[str, Any]]:
    where, args = ["station_id = ?"], [station_id]
    if start:
        where.append("observed_at >= ?")
        args.append(start)
    if end:
        where.append("observed_at <= ?")
        args.append(end)
    sql = "SELECT %s, extra, qc_flags FROM station_observations WHERE %s ORDER BY observed_at%s%s" % (
        ", ".join(OBS_COLS), " AND ".join(where), " DESC" if newest_first else "",
        (" LIMIT %d" % int(limit)) if limit else "")
    out = []
    for r in store._rows(store._q(sql), args):
        d = {c: (_utc_text(r[c]) if c in TIME_COLS else r[c]) for c in OBS_COLS}
        d["extra"] = _json_out(r.get("extra")) or {}
        d["qc_flags"] = _json_out(r.get("qc_flags")) or {}
        out.append(d)
    return out


def last_observed(store: Any, station_id: str) -> Optional[str]:
    rows = store._rows(store._q("SELECT max(observed_at) AS t FROM station_observations WHERE station_id = ?"),
                       (station_id,))
    return _utc_text(rows[0]["t"]) if rows and rows[0]["t"] is not None else None


def delete_station_observations(store: Any, station_id: str) -> None:
    store._exec(store._q("DELETE FROM station_observations WHERE station_id = ?"), (station_id,))


# ------------------------------------------------------------------ retention (T024)

def retention(store: Any, raw_months: int, hourly_months: int, today: date) -> Dict[str, Any]:
    """PostgreSQL: drop whole monthly partitions older than the retention; SQLite: plain DELETE."""
    out: Dict[str, Any] = {"dropped": [], "deleted": 0}

    def cutoff(months: int) -> date:
        y, m = today.year, today.month - months
        while m <= 0:
            y, m = y - 1, m + 12
        return date(y, m, 1)

    for table, months in (("station_observations", raw_months), ("weather_hourly", hourly_months)):
        cut = cutoff(months)
        if store.backend == "postgresql":
            for name in list_partitions(store, table):
                tail = name.rsplit("_p", 1)[-1]
                if len(tail) == 6 and tail.isdigit() and date(int(tail[:4]), int(tail[4:]), 1) < cut:
                    store._exec("DROP TABLE IF EXISTS %s" % name)
                    with _lock:
                        _partitions_done.discard((id(store), name))
                    out["dropped"].append(name)
        else:
            col = "observed_at" if table == "station_observations" else "ts"
            rows = store._rows(store._q("SELECT count(*) AS n FROM %s WHERE %s < ?" % (table, col)), (cut.isoformat(),))
            store._exec(store._q("DELETE FROM %s WHERE %s < ?" % (table, col)), (cut.isoformat(),))
            out["deleted"] += int(rows[0]["n"])
    return out
