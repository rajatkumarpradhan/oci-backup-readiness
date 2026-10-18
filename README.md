# oci-backup-readiness

Offline check of backup and disaster-recovery settings for OCI-style resources (boot volumes, block volumes, databases, buckets). It reads a JSON inventory, applies 13 rules and prints findings by severity. It can also write JSON or SARIF 2.1.0.

This is a portfolio project. The inventory format is a simplified schema I made up, not the OCI API shape. The data in `examples/` is synthetic. Nothing here has been run against a real tenancy, it calls no OCI API, and a clean result says nothing about whether a restore would actually work. The thresholds (retention minimums per tier, the 90/180-day restore-test cadences) are my own assumptions, not an OCI or industry standard.

## Run

```
python -m pip install -e .
bk-check examples/risky.json --as-of 2026-10-15T00:00:00
bk-check examples/risky.json --as-of 2026-10-15T00:00:00 --output report.sarif --format sarif --fail-on high
```

`--as-of` sets the reference time so results are repeatable (default: now). Exit codes: 0 ok, 1 bad input, 2 a finding at or above `--fail-on`.

## Rules

| Rule | Severity | What it flags |
|---|---|---|
| BK001 | high (dev: low) | resource with no backup policy |
| BK002 | high | last backup older than the RPO, or never completed (a future timestamp is a low "check inputs" note) |
| BK003 | high | policy frequency longer than the RPO |
| BK004 | medium | retention below the tier minimum (critical 35 days, standard 14, dev 7) |
| BK005 | medium | critical resource with no cross-region copy |
| BK006 | medium | backup copy region equal to the resource region |
| BK007 | medium | no restore test recorded (critical and standard) |
| BK008 | high | resource points at a policy that does not exist |
| BK009 | low | policy attached to nothing |
| BK010 | low | dev resource keeping backups over 365 days |
| BK011 | high (critical) / medium | estimated restore time longer than the RTO |
| BK012 | medium | critical resource with a policy but no RTO and restore estimate |
| BK013 | medium | restore-test cadence missed: critical tests every 90 days, standard every 180 (reports the missed cycles) |

## Several policies per resource

A resource can name one policy with `"policy"` or several with `"policies": [...]` (the two merge). Combined, the strictest frequency and the longest retention win: BK003 compares the RPO against the shortest backup interval across the attached policies, and BK004/BK010 use the longest retention. A cross-region copy on any one policy satisfies BK005, while BK006 flags each policy whose copy region is the resource's own region. Dangling names are reported one finding each (BK008).

Restore tests are modeled as a cadence per tier: critical every 90 days, standard every 180, dev not required. BK013 flags a missed cycle and says how many; BK007 is only for "never tested". The cadence only looks at the last test date - it does not track a real schedule.

## Recovery time (RTO)

Give a resource `rto_minutes` and `restore_minutes`. BK011 compares them. With `"restore_from": "copy"` (restoring from the cross-region copy) the check adds a transfer allowance, 60 minutes by default, set with `--transfer-minutes`. Both numbers are supplied by you: the tool does not measure restores and the allowance is a flat guess, not a model of data size or bandwidth. If only one of the two is given, it counts as missing.

## Limits

- Checks configuration and recorded timestamps only. It cannot tell whether a backup is restorable.
- Policies combine into one effective frequency/retention; there are no per-backup-type schedules, no volume groups and no object storage replication policies.
- RPO is a per-resource number you provide. Frequency and last-backup age are checked against it, nothing else.
- Cross-region means only "copy region is set and differs from the resource region".

## Tests

```
python -m unittest discover -s tests -v
```

Tests cover each boundary (exactly at the RPO, 180 vs 181 days, retention minus one, 365 vs 366 days), the missing-policy case, validation errors, CLI exit codes and SARIF. `examples/good.json` must produce zero findings and `examples/risky.json` must trigger all 13 rules.
