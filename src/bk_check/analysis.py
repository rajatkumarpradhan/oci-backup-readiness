"""Backup readiness rules. Findings are review priorities from a simplified model, not an assessment of real recoverability."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from .model import Inventory

SEV = {"high": 0, "medium": 1, "low": 2}
MIN_RETENTION = {"critical": 35, "standard": 14, "dev": 7}
RESTORE_TEST_MAX_DAYS = 180
DEV_RETENTION_MAX = 365
DEFAULT_TRANSFER_MINUTES = 60
NO_BACKUP_SEVERITY = {"critical": "high", "standard": "high", "dev": "low"}


@dataclass
class Finding:
    rule: str
    severity: str
    subject: str
    message: str
    evidence: dict

    def to_dict(self):
        return asdict(self)


def analyze(inv: Inventory, now: datetime, transfer_minutes: int = DEFAULT_TRANSFER_MINUTES) -> list[Finding]:
    out: list[Finding] = []
    used = set()
    for r in inv.resources:
        sub = f"resource:{r.name}"
        pol = inv.policies.get(r.policy) if r.policy else None
        if r.policy:
            used.add(r.policy)
        if r.policy is None:
            out.append(Finding("BK001", NO_BACKUP_SEVERITY[r.tier], sub, f"No backup policy ({r.tier} tier).", {"tier": r.tier}))
        elif pol is None:
            out.append(Finding("BK008", "high", sub, f"Backup policy {r.policy!r} does not exist.", {"policy": r.policy}))
        if r.rto_minutes is not None and r.restore_minutes is not None:
            total = r.restore_minutes + (transfer_minutes if r.restore_from == "copy" else 0)
            if total > r.rto_minutes:
                out.append(Finding("BK011", "high" if r.tier == "critical" else "medium", sub,
                                   f"Estimated restore {total} min ({r.restore_minutes} + {total - r.restore_minutes} cross-region allowance) exceeds the {r.rto_minutes} min RTO.",
                                   {"estimate_minutes": total, "rto_minutes": r.rto_minutes}))
        elif r.tier == "critical" and r.policy is not None:
            out.append(Finding("BK012", "medium", sub, "Critical resource has no RTO and restore estimate, so recovery time is unchecked.",
                               {"rto_minutes": r.rto_minutes, "restore_minutes": r.restore_minutes}))
        if pol is not None:
            if pol.frequency_hours > r.rpo_hours:
                out.append(Finding("BK003", "high", sub, f"Policy runs every {pol.frequency_hours}h but the RPO is {r.rpo_hours}h.",
                                   {"frequency_hours": pol.frequency_hours, "rpo_hours": r.rpo_hours}))
            if pol.retention_days < MIN_RETENTION[r.tier]:
                out.append(Finding("BK004", "medium", sub, f"Retention {pol.retention_days} days is below the {MIN_RETENTION[r.tier]} days this tier expects.",
                                   {"retention_days": pol.retention_days, "minimum": MIN_RETENTION[r.tier]}))
            if r.tier == "critical" and pol.copy_region is None:
                out.append(Finding("BK005", "medium", sub, "Critical resource has no cross-region backup copy.", {}))
            if pol.copy_region is not None and pol.copy_region == r.region:
                out.append(Finding("BK006", "medium", sub, f"Backup copy region {pol.copy_region!r} is the same as the resource region, so it is not a DR copy.",
                                   {"region": r.region}))
            if r.tier == "dev" and pol.retention_days > DEV_RETENTION_MAX:
                out.append(Finding("BK010", "low", sub, f"Dev resource keeps backups {pol.retention_days} days (over {DEV_RETENTION_MAX}).",
                                   {"retention_days": pol.retention_days}))
            if r.last_backup is None:
                out.append(Finding("BK002", "high", sub, "A policy is attached but no backup has ever completed.", {}))
            else:
                age_h = (now - r.last_backup).total_seconds() / 3600
                if age_h < 0:
                    out.append(Finding("BK002", "low", sub, "Last backup is in the future relative to the reference time; check the inputs.",
                                       {"last_backup": r.last_backup.isoformat()}))
                elif age_h > r.rpo_hours:
                    out.append(Finding("BK002", "high", sub, f"Last backup is {age_h:.1f}h old, older than the {r.rpo_hours}h RPO.",
                                       {"age_hours": round(age_h, 1), "rpo_hours": r.rpo_hours}))
        if r.tier != "dev" and pol is not None:
            if r.last_restore_test is None:
                out.append(Finding("BK007", "medium", sub, "No restore test recorded.", {}))
            elif (now - r.last_restore_test).days > RESTORE_TEST_MAX_DAYS:
                out.append(Finding("BK007", "medium", sub, f"Last restore test was {(now - r.last_restore_test).days} days ago (limit {RESTORE_TEST_MAX_DAYS}).",
                                   {"days": (now - r.last_restore_test).days}))
    for name in inv.policies:
        if name not in used:
            out.append(Finding("BK009", "low", f"policy:{name}", "Backup policy is not attached to any resource.", {}))
    out.sort(key=lambda f: (SEV[f.severity], f.rule, f.subject, f.message))
    return out
