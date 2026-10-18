"""Load and validate the simplified backup inventory (this project's own schema, not the OCI API)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime


class ModelError(ValueError):
    pass


KINDS = {"boot_volume", "block_volume", "database", "bucket"}
TIERS = {"critical", "standard", "dev"}


def parse_time(v, what) -> datetime:
    if not isinstance(v, str) or len(v) != 19 or v[10] != "T":
        raise ModelError(f"{what} must be YYYY-MM-DDTHH:MM:SS, got {v!r}")
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        raise ModelError(f"{what} is not a real timestamp: {v!r}") from None


@dataclass
class Policy:
    name: str
    frequency_hours: int
    retention_days: int
    copy_region: str | None = None


@dataclass
class Resource:
    name: str
    kind: str
    region: str
    tier: str
    rpo_hours: int
    policies: list[str]
    last_backup: datetime | None
    last_restore_test: datetime | None
    rto_minutes: int | None = None
    restore_minutes: int | None = None
    restore_from: str = "local"


@dataclass
class Inventory:
    policies: dict[str, Policy] = field(default_factory=dict)
    resources: list[Resource] = field(default_factory=list)


def _str(v, what):
    if not isinstance(v, str) or not v.strip():
        raise ModelError(f"{what} must be a non-empty string")
    return v


def _int(v, what, lo, hi):
    if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
        raise ModelError(f"{what} must be an integer in [{lo}, {hi}], got {v!r}")
    return v


def _opt_time(v, what):
    return None if v is None else parse_time(v, what)


def _opt_int(v, what):
    return None if v is None else _int(v, what, 1, 60 * 24 * 30)


def _source(v, what):
    if v not in ("local", "copy"):
        raise ModelError(f"{what} must be 'local' or 'copy', got {v!r}")
    return v


def load(data: dict) -> Inventory:
    try:
        pols = {}
        for i, p in enumerate(data.get("policies", [])):
            w = f"policies[{i}]"
            name = _str(p["name"], f"{w}.name")
            if name in pols:
                raise ModelError(f"duplicate policy {name!r}")
            cr = p.get("copy_region")
            pols[name] = Policy(name, _int(p["frequency_hours"], f"{w}.frequency_hours", 1, 24 * 365),
                                _int(p["retention_days"], f"{w}.retention_days", 1, 36500),
                                _str(cr, f"{w}.copy_region") if cr is not None else None)
        res, seen = [], set()
        for i, r in enumerate(data.get("resources", [])):
            w = f"resources[{i}]"
            name = _str(r["name"], f"{w}.name")
            if name in seen:
                raise ModelError(f"duplicate resource {name!r}")
            seen.add(name)
            kind, tier = _str(r["kind"], f"{w}.kind"), _str(r["tier"], f"{w}.tier")
            if kind not in KINDS:
                raise ModelError(f"{w}.kind must be one of {sorted(KINDS)}")
            if tier not in TIERS:
                raise ModelError(f"{w}.tier must be one of {sorted(TIERS)}")
            names = []
            single = r.get("policy")
            if single is not None:
                names.append(_str(single, f"{w}.policy"))
            plist = r.get("policies", [])
            if not isinstance(plist, list) or any(not isinstance(x, str) or not x.strip() for x in plist):
                raise ModelError(f"{w}.policies must be a list of policy names")
            names.extend(plist)
            if len(set(names)) != len(names):
                raise ModelError(f"{w}: duplicate policy name in the resource's policy list")
            res.append(Resource(name, kind, _str(r["region"], f"{w}.region"), tier,
                                _int(r["rpo_hours"], f"{w}.rpo_hours", 1, 24 * 365),
                                names,
                                _opt_time(r.get("last_backup"), f"{w}.last_backup"),
                                _opt_time(r.get("last_restore_test"), f"{w}.last_restore_test"),
                                _opt_int(r.get("rto_minutes"), f"{w}.rto_minutes"),
                                _opt_int(r.get("restore_minutes"), f"{w}.restore_minutes"),
                                _source(r.get("restore_from", "local"), f"{w}.restore_from")))
    except (KeyError, TypeError, AttributeError) as e:
        raise ModelError(f"invalid model: {e!r}") from e
    return Inventory(pols, res)


def load_file(path: str) -> Inventory:
    with open(path, encoding="utf-8") as f:
        return load(json.load(f))
