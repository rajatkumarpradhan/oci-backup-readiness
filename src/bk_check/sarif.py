"""SARIF 2.1.0 output. Results point at the input file as a whole (no line numbers) and name the resource or policy as a logical location.
Minimal hand-built subset: the tests check its shape; it has not been validated against the official schema or a real viewer.
"""
from __future__ import annotations

from .analysis import Finding

SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
LEVEL = {"high": "error", "medium": "warning", "low": "note"}
RULES = {
    "BK001": "Resource has no backup policy",
    "BK002": "Last backup is older than the RPO or never completed",
    "BK003": "Backup frequency is longer than the RPO",
    "BK004": "Retention is below the tier minimum",
    "BK005": "Critical resource has no cross-region copy",
    "BK006": "Backup copy region equals the resource region",
    "BK007": "No restore test recorded",
    "BK008": "Backup policy reference does not exist",
    "BK009": "Backup policy is not attached to any resource",
    "BK010": "Dev resource keeps backups longer than a year",
    "BK011": "Estimated restore time exceeds the RTO",
    "BK012": "Critical resource has no RTO and restore estimate",
    "BK013": "Restore-test cadence missed for the resource tier",
}


def to_sarif(findings: list[Finding], artifact_uri: str, version: str = "0.1.0") -> dict:
    rules = [{"id": r, "shortDescription": {"text": t}} for r, t in sorted(RULES.items())]
    index = {r["id"]: i for i, r in enumerate(rules)}
    results = []
    for f in findings:
        res = {
            "ruleId": f.rule,
            "level": LEVEL[f.severity],
            "message": {"text": f.message},
            "locations": [{
                "physicalLocation": {"artifactLocation": {"uri": artifact_uri}},
                "logicalLocations": [{"name": f.subject}],
            }],
        }
        if f.rule in index:
            res["ruleIndex"] = index[f.rule]
        if f.evidence:
            res["properties"] = {"evidence": f.evidence}
        results.append(res)
    return {
        "$schema": SCHEMA,
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {"name": "oci-backup-readiness", "version": version, "rules": rules}},
            "results": results,
        }],
    }
