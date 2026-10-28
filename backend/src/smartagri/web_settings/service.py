"""Web settings of the research core: layers, limits, versions, audit log and the per-request overlay.

Effective value of a parameter = the parcel's override, else the user's, else the global one (set by an administrator),
else the default read from the YAML file. Every layer is a set of overrides keyed by the registry's dotted key.

- Limits (administrator): per parameter, whether users may override it and the allowed range (and, for lists and
  tables, their shape). A write outside the range is refused. An override that was valid when it was saved and is
  outside a limit set later is ignored in the effective value and reported as ignored.
- History: every change writes one version (the whole set of that layer afterwards) and one audit row per parameter,
  both append-only (migration 0015 installs triggers that refuse UPDATE and DELETE). Restoring is a new version.
- Evaluation: this module is used by the research API only. evalkit and the protocol lock read the YAML files through
  `config.load_file` and never see an overlay.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .. import config
from ..store import Store, new_id, now_iso
from . import registry as reg

ENV_ADMINS = "SMARTAGRI_ADMINS"
SCOPES = ("global", "user", "parcel", "limits")
AUDIT_SCOPES = SCOPES + ("admin_role",)       # the log also holds the operator's grants and revocations of the role
LOCAL_USER = "local"
MAX_REASON = 300
PAGE_MAX = 200
CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def admin_emails() -> frozenset:
    raw = os.environ.get(ENV_ADMINS) or ""
    return frozenset(e.strip().lower() for e in raw.split(",") if e.strip())


class SettingsError(Exception):
    """status: 400 refused values (errors lists key, code, params), 403 not allowed, 404 unknown, 409 changed meanwhile."""

    def __init__(self, status: int, message: str, errors: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.errors = errors or []


@dataclass
class Actor:
    """Who is asking. user_id is None for an anonymous visitor (read only)."""
    user_id: Optional[str]
    admin: bool = False
    mode: str = "off"                # accounts mode: off | optional
    label: str = ""

    @property
    def can_write(self) -> bool:
        return self.user_id is not None


def clean_reason(text: Any, required: bool = False) -> str:
    reason = CTRL.sub(" ", text).strip() if isinstance(text, str) else ""
    if required and not reason:
        raise SettingsError(400, "A reason is required for this change.", [{"key": "reason", "code": "required", "params": {}}])
    if len(reason) > MAX_REASON:
        raise SettingsError(400, "The reason is too long.", [{"key": "reason", "code": "too_long", "params": {"max": MAX_REASON}}])
    return reason


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def empty_summary() -> Dict[str, Any]:
    """The settings block of an answer computed from the files alone (no layer set anything)."""
    snap: Dict[str, Any] = {}
    return {"hash": hashlib.sha256(_canon(snap).encode("utf-8")).hexdigest(), "version": "files",
            "layers": {"global": 0, "user": 0, "parcel": 0}, "n_overrides": 0, "snapshot": snap, "ignored": [],
            "outside_recommended": [], "defaults": "config files (hashes in config_hashes)"}


class SettingsService:
    def __init__(self, store: Store):
        self.store = store

    # ------------------------------------------------------------------------------------------ layers
    def _doc(self, scope: str, scope_id: str) -> Dict[str, Any]:
        table = {"global": "settings_global", "limits": "settings_limits", "user": "settings_user",
                 "parcel": "settings_parcel"}[scope]
        doc = self.store.get(table, scope_id)
        return doc or {"id": scope_id, "values": {}, "version": 0}

    def layer(self, scope: str, scope_id: str) -> Tuple[Dict[str, Any], int]:
        doc = self._doc(scope, scope_id)
        return dict(doc.get("values") or {}), int(doc.get("version") or 0)

    def limits(self) -> Dict[str, Dict[str, Any]]:
        return self.layer("limits", "limits")[0]

    @staticmethod
    def _scope_id(scope: str, user_id: Optional[str], parcel_id: Optional[str]) -> str:
        if scope == "global":
            return "global"
        if scope == "limits":
            return "limits"
        if scope == "user":
            if not user_id:
                raise SettingsError(403, "Sign in to save settings.")
            return user_id
        if scope == "parcel":
            if not parcel_id:
                raise SettingsError(404, "Parcel not found.")
            return parcel_id
        raise SettingsError(400, "Unknown settings level.")

    def _user_editable(self, entry: reg.Entry, limits: Dict[str, Any]) -> bool:
        if not entry.editable:
            return False
        lim = limits.get(entry.key) or {}
        return bool(lim.get("user_editable", entry.spec.user))

    # ------------------------------------------------------------------------------------------ resolution
    def resolve(self, user_id: Optional[str], parcel_id: Optional[str] = None) -> Dict[str, Any]:
        """Everything about the effective values for one user and, optionally, one parcel."""
        emap = reg.entry_map()
        limits = self.limits()
        gvals, gver = self.layer("global", "global")
        uvals, uver = self.layer("user", user_id) if user_id else ({}, 0)
        pvals, pver = self.layer("parcel", parcel_id) if parcel_id else ({}, 0)
        layers = (("global", gvals), ("user", uvals), ("parcel", pvals))
        per: Dict[str, Dict[str, Any]] = {}
        ignored: List[Dict[str, Any]] = []
        for layer, vals in layers:
            for key, raw in vals.items():
                entry = emap.get(key)
                reason = None
                value = None
                if entry is None:
                    reason = "unknown_key"
                elif not entry.editable:
                    reason = "not_editable"
                elif layer != "global" and not self._user_editable(entry, limits):
                    reason = "not_editable_by_user"
                else:
                    try:
                        value = reg.validate(entry, raw, limits.get(key))
                    except reg.Invalid as exc:
                        reason = exc.code
                if reason:
                    ignored.append({"key": key, "layer": layer, "reason": reason})
                    continue
                per.setdefault(key, {})[layer] = value
        effective: Dict[str, Tuple[Any, str]] = {}
        for key, byl in per.items():
            for layer in ("parcel", "user", "global"):
                if layer in byl:
                    effective[key] = (byl[layer], layer)
                    break
        snapshot = {k: {"value": v, "layer": lay} for k, (v, lay) in sorted(effective.items())}
        meta = {"hash": hashlib.sha256(_canon(snapshot).encode("utf-8")).hexdigest(),
                "version": "g%d.u%d.p%d" % (gver, uver, pver), "layers": {"global": gver, "user": uver, "parcel": pver},
                "n_overrides": len(snapshot), "snapshot": snapshot, "ignored": sorted(ignored, key=lambda i: (i["key"], i["layer"])),
                # values in use that are outside the recommended range of their parameter (development band or source)
                "outside_recommended": [{k: w[k] for k in ("key", "where", "value", "range", "basis")}
                                        for key, (v, _l) in sorted(effective.items()) for w in reg.warnings(emap[key], v)],
                "defaults": "config files (hashes in config_hashes)"}
        overlay = config.Overlay({k: v for k, (v, _l) in effective.items()}, meta)
        return {"entries": emap, "limits": limits, "per": per, "effective": effective, "meta": meta, "overlay": overlay,
                "ignored": ignored, "versions": {"global": gver, "user": uver, "parcel": pver,
                                                 "limits": self.layer("limits", "limits")[1]}}

    def overlay_for(self, user_id: Optional[str], parcel_id: Optional[str] = None) -> config.Overlay:
        return self.resolve(user_id, parcel_id)["overlay"]

    # ------------------------------------------------------------------------------------------ the API view
    def view(self, actor: Actor, parcel_id: Optional[str] = None) -> Dict[str, Any]:
        res = self.resolve(actor.user_id, parcel_id)
        entries = []
        ignored_by_key: Dict[str, List[Dict[str, Any]]] = {}
        for item in res["ignored"]:
            ignored_by_key.setdefault(item["key"], []).append(item)
        for e in res["entries"].values():
            d = reg.describe(e)
            lim = res["limits"].get(e.key) or {}
            eff, layer = res["effective"].get(e.key, (e.default, "default"))
            d.update({"layers": res["per"].get(e.key, {}), "effective": eff, "layer": layer,
                      "limit": lim, "user_editable": self._user_editable(e, res["limits"]),
                      "bounds": reg.merged_bounds(e, lim), "warnings": reg.warnings(e, eff) if layer != "default" else [],
                      "ignored": ignored_by_key.get(e.key, [])})
            entries.append(d)
        return {"capabilities": {"accounts": actor.mode, "signed_in": actor.can_write, "can_write": actor.can_write,
                                 "is_admin": actor.admin, "parcel_id": parcel_id},
                "groups": reg.groups(), "statuses": reg.statuses(), "entries": entries,
                "versions": res["versions"], "effective": {k: res["meta"][k] for k in ("hash", "version", "n_overrides")}}

    # ------------------------------------------------------------------------------------------ writes
    def _check_updates(self, scope: str, updates: Any, limits: Dict[str, Any]) -> Dict[str, Any]:
        """Canonical values for an update ({key: value|None}); SettingsError(400) listing every refused key."""
        if not isinstance(updates, dict) or not updates or len(updates) > 400:
            raise SettingsError(400, "Some values were refused.", [{"key": "values", "code": "shape", "params": {}}])
        emap = reg.entry_map()
        out: Dict[str, Any] = {}
        errors: List[Dict[str, Any]] = []
        for key, raw in updates.items():
            entry = emap.get(key) if isinstance(key, str) else None
            if entry is None:
                errors.append({"key": str(key)[:120], "code": "unknown_key", "params": {}})
                continue
            if not entry.editable:
                errors.append({"key": key, "code": "not_editable", "params": {}})
                continue
            if scope in ("user", "parcel") and not self._user_editable(entry, limits):
                errors.append({"key": key, "code": "not_editable_by_user", "params": {}})
                continue
            if raw is None:
                out[key] = None
                continue
            try:
                out[key] = reg.validate(entry, raw, limits.get(key))
            except reg.Invalid as exc:
                errors.append({"key": key, "code": exc.code, "params": exc.params})
        if errors:
            raise SettingsError(400, "Some values were refused.", errors)
        return out

    def _flat(self, user_id: Optional[str], parcel_id: Optional[str], scope: str, new_values: Dict[str, Any]) -> Dict[str, Any]:
        """Effective values of the keys used by the relations, with one layer replaced by new_values."""
        wanted = {k for a, _o, b, _c in reg.RELATIONS for k in (a, b)}
        emap = reg.entry_map()
        layers = {"global": self.layer("global", "global")[0],
                  "user": self.layer("user", user_id)[0] if user_id else {},
                  "parcel": self.layer("parcel", parcel_id)[0] if parcel_id else {}}
        if scope in layers:
            layers[scope] = new_values
        flat = {}
        for k in wanted:
            if k in emap:
                flat[k] = emap[k].default
                for layer in ("global", "user", "parcel"):
                    if k in layers[layer]:
                        flat[k] = layers[layer][k]
        return flat

    def _commit(self, scope: str, scope_id: str, old: Dict[str, Any], new: Dict[str, Any], actor: Actor, reason: str,
                action: str, restored_from: Optional[int] = None) -> Dict[str, Any]:
        changed = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k) or (k in old) != (k in new))
        if not changed:
            return {"version": self._doc(scope, scope_id).get("version", 0), "changed": [], "unchanged": True}
        table = {"global": "settings_global", "limits": "settings_limits", "user": "settings_user",
                 "parcel": "settings_parcel"}[scope]
        cur = self._doc(scope, scope_id)
        n = int(cur.get("version") or 0) + 1
        now = now_iso()
        doc = {"id": scope_id, "created_at": cur.get("created_at") or now, "updated_at": now, "values": new, "version": n}
        if scope == "user":
            doc["user_id"] = scope_id
        if scope == "parcel":
            doc["parcel_id"] = scope_id
        self.store.put(table, doc)
        self.store.put("settings_versions", {"id": new_id(), "created_at": now, "scope": scope, "scope_id": scope_id, "n": n,
                                             "values": new, "changed": changed, "action": action, "actor": actor.user_id,
                                             "reason": reason, "restored_from": restored_from})
        for k in changed:
            self.store.put("settings_audit", {"id": new_id(), "created_at": now, "at": now, "scope": scope, "scope_id": scope_id,
                                             "actor": actor.user_id, "param": k, "old": old.get(k), "new": new.get(k),
                                             "action": action, "version": n, "reason": reason})
        return {"version": n, "changed": changed, "unchanged": False}

    def _writer(self, actor: Actor, scope: str) -> None:
        if not actor.can_write:
            raise SettingsError(403, "Sign in to save settings.")
        if scope in ("global", "limits") and not actor.admin:
            raise SettingsError(403, "Not allowed.")

    def update(self, actor: Actor, scope: str, parcel_id: Optional[str], updates: Any, reason: Any = "",
               base_version: Optional[int] = None) -> Dict[str, Any]:
        """Set (value) or remove (None) overrides of one layer, atomically."""
        self._writer(actor, scope)
        if scope == "limits":
            raise SettingsError(400, "Use the limits endpoint.")
        sid = self._scope_id(scope, actor.user_id, parcel_id)
        reason = clean_reason(reason, required=scope == "global")
        with self.store.transaction():
            limits = self.limits()
            old, ver = self.layer(scope, sid)
            if base_version is not None and int(base_version) != ver:
                raise SettingsError(409, "The settings changed in the meantime. Reload and try again.")
            checked = self._check_updates(scope, updates, limits)
            new = dict(old)
            for k, v in checked.items():
                if v is None:
                    new.pop(k, None)
                else:
                    new[k] = v
            bad = reg.check_relations(self._flat(actor.user_id, parcel_id, scope, new))
            if bad:
                raise SettingsError(400, "Some values were refused.", bad)
            out = self._commit(scope, sid, old, new, actor, reason, "set")
        emap = reg.entry_map()
        out["warnings"] = [w for k, v in checked.items() if v is not None for w in reg.warnings(emap[k], v)]
        return out

    def reset(self, actor: Actor, scope: str, parcel_id: Optional[str], keys: Optional[List[str]] = None,
              everything: bool = False, reason: Any = "") -> Dict[str, Any]:
        """Remove overrides of one layer (the values fall back to the layer below, or to the file default)."""
        self._writer(actor, scope)
        sid = self._scope_id(scope, actor.user_id, parcel_id)
        reason = clean_reason(reason, required=scope in ("global", "limits"))
        with self.store.transaction():
            old, _ver = self.layer(scope, sid)
            if everything:
                new: Dict[str, Any] = {}
            else:
                if not isinstance(keys, list) or not keys or not all(isinstance(k, str) for k in keys):
                    raise SettingsError(400, "Some values were refused.", [{"key": "keys", "code": "shape", "params": {}}])
                unknown = [k for k in keys if k not in old and k not in reg.entry_map()]
                if unknown:
                    raise SettingsError(400, "Some values were refused.", [{"key": k[:120], "code": "unknown_key", "params": {}} for k in unknown])
                new = {k: v for k, v in old.items() if k not in keys}
            return self._commit(scope, sid, old, new, actor, reason, "reset")

    # ------------------------------------------------------------------------------------------ limits
    def set_limits(self, actor: Actor, updates: Any, reason: Any) -> Dict[str, Any]:
        """Administrator: user-editable switch and allowed range per parameter ({key: limit | None})."""
        self._writer(actor, "limits")
        reason = clean_reason(reason, required=True)
        if not isinstance(updates, dict) or not updates or len(updates) > 400:
            raise SettingsError(400, "Some values were refused.", [{"key": "limits", "code": "shape", "params": {}}])
        emap = reg.entry_map()
        errors: List[Dict[str, Any]] = []
        with self.store.transaction():
            old, _ = self.layer("limits", "limits")
            new = dict(old)
            gvals, _gv = self.layer("global", "global")
            for key, raw in updates.items():
                entry = emap.get(key) if isinstance(key, str) else None
                if entry is None:
                    errors.append({"key": str(key)[:120], "code": "unknown_key", "params": {}})
                    continue
                if raw is None or raw == {}:
                    new.pop(key, None)
                    continue
                try:
                    new[key] = reg.validate_limit(entry, raw)
                except reg.Invalid as exc:
                    errors.append({"key": key, "code": exc.code, "params": exc.params})
                    continue
                if key in gvals:                     # the global value must stay inside the new limit
                    try:
                        reg.validate(entry, gvals[key], new[key])
                    except reg.Invalid:
                        errors.append({"key": key, "code": "global_outside_limit", "params": {}})
            if errors:
                raise SettingsError(400, "Some values were refused.", errors)
            return self._commit("limits", "limits", old, new, actor, reason, "limit")

    # ------------------------------------------------------------------------------------------ versions
    def versions(self, actor: Actor, scope: str, parcel_id: Optional[str] = None, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sid = self._scope_for_read(actor, scope, parcel_id, user_id)
        rows = self.store.find("settings_versions", order="seq DESC", scope=scope, scope_id=sid)
        return [{"n": r["n"], "at": r["created_at"], "actor": self._actor_view(actor, r.get("actor")), "action": r["action"],
                 "reason": r.get("reason") or "", "changed": r.get("changed") or [], "values": r.get("values") or {},
                 "restored_from": r.get("restored_from")} for r in rows]

    def _scope_for_read(self, actor: Actor, scope: str, parcel_id: Optional[str], user_id: Optional[str]) -> str:
        if scope not in SCOPES:
            raise SettingsError(400, "Unknown settings level.")
        if scope in ("global", "limits"):
            if not actor.admin:
                raise SettingsError(403, "Not allowed.")
            return scope
        if not actor.can_write:
            raise SettingsError(403, "Sign in to see the history.")
        if scope == "user":
            if user_id and user_id != actor.user_id:
                if not actor.admin:
                    raise SettingsError(403, "Not allowed.")
                return user_id
            return actor.user_id or ""
        if not parcel_id:
            raise SettingsError(404, "Parcel not found.")
        return parcel_id

    def _actor_view(self, actor: Actor, actor_id: Optional[str]) -> str:
        if not actor_id:
            return ""
        if actor_id == actor.user_id:
            return "you"
        if not actor.admin:
            return ""
        if actor_id == LOCAL_USER:
            return LOCAL_USER
        if actor_id == "operator-cli":
            return "operator (server command)"
        user = self.store.get("core_users", actor_id) if self._has_users() else None
        return user["email"] if user else "deleted account"

    def _has_users(self) -> bool:
        try:
            self.store._rows("SELECT 1 FROM core_users LIMIT 1")
            return True
        except Exception:
            return False

    def restore(self, actor: Actor, scope: str, parcel_id: Optional[str], version: Any, keys: Optional[List[str]] = None,
                reason: Any = "") -> Dict[str, Any]:
        """Back to a previous version of one layer: the whole set, or only `keys`. version "default" means the file
        defaults (no override). The result is a new version; nothing is deleted."""
        self._writer(actor, scope)
        sid = self._scope_id(scope, actor.user_id, parcel_id)
        reason = clean_reason(reason, required=scope in ("global", "limits"))
        with self.store.transaction():
            old, _ver = self.layer(scope, sid)
            from_n: Optional[int] = None
            if version == "default":
                target: Dict[str, Any] = {}
            else:
                try:
                    from_n = int(version)
                except (TypeError, ValueError):
                    raise SettingsError(400, "Unknown version.")
                rows = [r for r in self.store.find("settings_versions", scope=scope, scope_id=sid) if r["n"] == from_n]
                if not rows:
                    raise SettingsError(404, "Version not found.")
                target = dict(rows[0].get("values") or {})
            if keys:
                if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                    raise SettingsError(400, "Some values were refused.", [{"key": "keys", "code": "shape", "params": {}}])
                new = dict(old)
                for k in keys:
                    if k in target:
                        new[k] = target[k]
                    else:
                        new.pop(k, None)
            else:
                new = dict(target)
            self._validate_restored(actor, scope, new)
            return self._commit(scope, sid, old, new, actor, reason, "restore", restored_from=from_n)

    def _validate_restored(self, actor: Actor, scope: str, values: Dict[str, Any]) -> None:
        """A restored set is validated like a new one (the registry or the limits may have changed since)."""
        emap = reg.entry_map()
        limits = self.limits()
        errors = []
        for key, raw in values.items():
            entry = emap.get(key)
            try:
                if entry is None:
                    raise reg.Invalid("unknown_key")
                if scope == "limits":
                    reg.validate_limit(entry, raw)
                else:
                    if not entry.editable or (scope in ("user", "parcel") and not self._user_editable(entry, limits)):
                        raise reg.Invalid("not_editable")
                    reg.validate(entry, raw, limits.get(key))
            except reg.Invalid as exc:
                errors.append({"key": key, "code": exc.code, "params": exc.params})
        if errors:
            raise SettingsError(400, "Some values were refused.", errors)

    # ------------------------------------------------------------------------------------------ audit log
    def audit(self, actor: Actor, scope: Optional[str] = None, parcel_id: Optional[str] = None, param: str = "",
              who: str = "", since: str = "", until: str = "", action: str = "", limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """The audit log, newest first. An administrator sees every layer and can filter by actor; a user sees only
        the log of their own settings and of a parcel they were allowed to open (the caller checks ownership)."""
        if not actor.can_write:
            raise SettingsError(403, "Sign in to see the history.")
        eq: Dict[str, Any] = {}
        if actor.admin:
            if scope:
                if scope not in AUDIT_SCOPES:
                    raise SettingsError(400, "Unknown settings level.")
                eq["scope"] = scope
            if parcel_id:
                eq["scope_id"] = parcel_id
            if who:
                eq["actor"] = who
        else:
            if scope == "parcel" and parcel_id:
                eq.update(scope="parcel", scope_id=parcel_id)
            elif scope in (None, "", "user"):
                eq.update(scope="user", scope_id=actor.user_id)
            else:
                raise SettingsError(403, "Not allowed.")
        rows = self.store.find("settings_audit", order="seq DESC", **eq)
        out = []
        for r in rows:
            if param and param.lower() not in (r.get("param") or "").lower():
                continue
            if action and r.get("action") != action:
                continue
            if since and r["at"] < since:
                continue
            if until and r["at"] > until + "~":       # a date matches the whole day
                continue
            out.append(r)
        total = len(out)
        limit = max(1, min(int(limit), PAGE_MAX))
        page = out[max(0, int(offset)):max(0, int(offset)) + limit]
        return {"total": total, "items": [{"at": r["at"], "scope": r["scope"], "scope_id": r["scope_id"] if actor.admin or r["scope"] != "user" else "",
                                           "actor": self._actor_view(actor, r.get("actor")), "param": r["param"],
                                           "old": r.get("old"), "new": r.get("new"), "action": r.get("action"),
                                           "version": r.get("version"), "reason": r.get("reason") or ""} for r in page]}

    # ------------------------------------------------------------------------------------------ account removal
    def forget_user(self, user_id: str) -> None:
        """The user's current overrides go with the account (their history keeps only the opaque id)."""
        self.store.delete("settings_user", id=user_id)
