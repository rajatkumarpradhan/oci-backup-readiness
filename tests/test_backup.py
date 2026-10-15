import copy
import json
import os
import tempfile
import unittest
from datetime import datetime

from bk_check import analysis, model
from bk_check.cli import main

EX = os.path.join(os.path.dirname(__file__), "..", "examples")
NOW = datetime(2026, 10, 15, 0, 0, 0)


def ex(n):
    with open(os.path.join(EX, n), encoding="utf-8") as f:
        return json.load(f)


GOOD = ex("good.json")


def run(d, now=NOW):
    return analysis.analyze(model.load(d), now)


def rules(d, now=NOW):
    return {f.rule for f in run(d, now)}


def one(tier="standard", rpo=24, freq=24, ret=35, copy_region="ap-hyderabad-1", last="2026-10-14T12:00:00",
        test="2026-09-01T00:00:00", region="ap-mumbai-1", policy="p"):
    pol = {"name": "p", "frequency_hours": freq, "retention_days": ret}
    if copy_region:
        pol["copy_region"] = copy_region
    return {"policies": [pol], "resources": [{"name": "r", "kind": "database", "region": region, "tier": tier, "rpo_hours": rpo,
                                              "policy": policy, "last_backup": last, "last_restore_test": test}]}


class ExampleTests(unittest.TestCase):
    def test_good_is_clean(self):
        self.assertEqual(run(copy.deepcopy(GOOD)), [])

    def test_risky_triggers_every_rule(self):
        self.assertEqual(rules(ex("risky.json")), {f"BK{n:03d}" for n in range(1, 13)})

    def test_sorted_by_severity(self):
        s = [analysis.SEV[f.severity] for f in run(ex("risky.json"))]
        self.assertEqual(s, sorted(s))

    def test_empty(self):
        self.assertEqual(run({}), [])

    def test_baseline_helper_is_clean(self):
        self.assertEqual(rules(one()), set())


class RuleTests(unittest.TestCase):
    def test_no_policy_severity_by_tier(self):
        for tier, sev in (("critical", "high"), ("standard", "high"), ("dev", "low")):
            d = one(tier=tier, policy=None)
            d["policies"] = []
            f = [x for x in run(d) if x.rule == "BK001"]
            self.assertEqual([x.severity for x in f], [sev])

    def test_missing_policy_reference_reports_bk008_not_noise(self):
        d = one(policy="ghost")
        self.assertEqual(rules(d), {"BK008", "BK009"})   # the real policy "p" is now unused

    def test_rpo_boundary(self):
        self.assertNotIn("BK002", rules(one(rpo=12, freq=12, last="2026-10-14T12:00:00")))   # exactly 12h old
        self.assertIn("BK002", rules(one(rpo=12, freq=12, last="2026-10-14T11:59:59")))      # one second over

    def test_never_backed_up(self):
        self.assertIn("BK002", rules(one(last=None)))

    def test_future_backup_is_low_not_high(self):
        f = [x for x in run(one(last="2026-10-16T00:00:00")) if x.rule == "BK002"]
        self.assertEqual([x.severity for x in f], ["low"])

    def test_frequency_boundary(self):
        self.assertNotIn("BK003", rules(one(rpo=24, freq=24)))
        self.assertIn("BK003", rules(one(rpo=24, freq=25)))

    def test_retention_boundary_per_tier(self):
        for tier, minimum in (("critical", 35), ("standard", 14), ("dev", 7)):
            with self.subTest(tier=tier):
                self.assertNotIn("BK004", rules(one(tier=tier, ret=minimum)))
                self.assertIn("BK004", rules(one(tier=tier, ret=minimum - 1)))

    def test_cross_region_copy_only_required_for_critical(self):
        self.assertIn("BK005", rules(one(tier="critical", copy_region=None)))
        self.assertNotIn("BK005", rules(one(tier="standard", copy_region=None)))

    def test_same_region_copy(self):
        self.assertIn("BK006", rules(one(copy_region="ap-mumbai-1")))
        self.assertNotIn("BK006", rules(one(copy_region="ap-hyderabad-1")))

    def test_restore_test_boundary(self):
        self.assertNotIn("BK007", rules(one(test="2026-04-18T00:00:00")))    # exactly 180 days
        self.assertIn("BK007", rules(one(test="2026-04-17T00:00:00")))       # 181 days
        self.assertIn("BK007", rules(one(test=None)))

    def test_restore_test_not_required_for_dev(self):
        self.assertNotIn("BK007", rules(one(tier="dev", test=None)))

    def test_unused_policy(self):
        d = one()
        d["policies"].append({"name": "idle", "frequency_hours": 1, "retention_days": 1})
        f = [x for x in run(d) if x.rule == "BK009"]
        self.assertEqual([x.subject for x in f], ["policy:idle"])

    def test_dev_retention_boundary(self):
        self.assertNotIn("BK010", rules(one(tier="dev", ret=365)))
        self.assertIn("BK010", rules(one(tier="dev", ret=366)))
        self.assertNotIn("BK010", rules(one(tier="standard", ret=400)))


class RtoTests(unittest.TestCase):
    def rto(self, rto, est, src="local", tier="standard", transfer=60):
        d = one(tier=tier)
        d["resources"][0].update(rto_minutes=rto, restore_minutes=est, restore_from=src)
        return [f for f in analysis.analyze(model.load(d), NOW, transfer) if f.rule in ("BK011", "BK012")]

    def test_boundary(self):
        self.assertEqual(self.rto(120, 120), [])
        f = self.rto(120, 121)
        self.assertEqual([x.rule for x in f], ["BK011"])
        self.assertEqual(f[0].evidence, {"estimate_minutes": 121, "rto_minutes": 120})

    def test_copy_adds_allowance(self):
        self.assertEqual(self.rto(120, 60, "copy"), [])
        self.assertEqual(len(self.rto(120, 61, "copy")), 1)
        self.assertEqual(self.rto(120, 61, "copy", transfer=59), [])

    def test_local_ignores_allowance(self):
        self.assertEqual(self.rto(120, 120, "local", transfer=500), [])

    def test_zero_allowance(self):
        self.assertEqual(self.rto(120, 120, "copy", transfer=0), [])

    def test_severity_by_tier(self):
        self.assertEqual(self.rto(10, 20, tier="critical")[0].severity, "high")
        self.assertEqual(self.rto(10, 20, tier="standard")[0].severity, "medium")

    def test_missing_estimate_only_flagged_for_critical(self):
        for tier, expect in (("critical", ["BK012"]), ("standard", []), ("dev", [])):
            d = one(tier=tier)
            self.assertEqual([f.rule for f in run(d) if f.rule == "BK012"], expect)

    def test_half_filled_pair_counts_as_missing(self):
        d = one(tier="critical")
        d["resources"][0]["rto_minutes"] = 60
        self.assertIn("BK012", rules(d))

    def test_no_estimate_check_without_policy(self):
        d = one(tier="critical", policy=None)
        d["policies"] = []
        self.assertNotIn("BK012", rules(d))

    def test_validation(self):
        for field, val in (("rto_minutes", 0), ("restore_minutes", True), ("restore_minutes", "5"), ("restore_from", "tape"),
                           ("rto_minutes", 60 * 24 * 30 + 1)):
            with self.subTest(field=field, val=val):
                d = one()
                d["resources"][0][field] = val
                with self.assertRaises(model.ModelError):
                    model.load(d)

    def test_cli_transfer_minutes(self):
        a = [os.path.join(EX, "risky.json"), "--as-of", "2026-10-15T00:00:00"]
        self.assertEqual(main(a + ["--transfer-minutes", "-1"]), 1)
        with tempfile.TemporaryDirectory() as t:
            def count(m):
                out = os.path.join(t, "r.json")
                main(a + ["--transfer-minutes", str(m), "--output", out])
                return sum(f["rule"] == "BK011" for f in json.load(open(out, encoding="utf-8"))["findings"])
            self.assertGreater(count(60), count(0))


class ValidationTests(unittest.TestCase):
    def bad(self, m):
        d = copy.deepcopy(GOOD)
        m(d)
        with self.assertRaises(model.ModelError):
            model.load(d)

    def test_errors(self):
        r = lambda d: d["resources"][0]
        cases = [
            lambda d: r(d).update(kind="vm"),
            lambda d: r(d).update(tier="gold"),
            lambda d: r(d).update(rpo_hours=0),
            lambda d: r(d).update(rpo_hours=True),
            lambda d: r(d).update(last_backup="2026-10-14"),
            lambda d: r(d).update(last_backup="2026-13-14T00:00:00"),
            lambda d: r(d).update(last_backup="2026-10-14 20:00:00"),
            lambda d: r(d).pop("region"),
            lambda d: r(d).update(name=""),
            lambda d: d["resources"].append(copy.deepcopy(r(d))),
            lambda d: d["policies"].append(copy.deepcopy(d["policies"][0])),
            lambda d: d["policies"][0].update(frequency_hours=0),
            lambda d: d["policies"][0].update(retention_days="30"),
            lambda d: d["policies"][0].update(copy_region=""),
        ]
        for i, m in enumerate(cases):
            with self.subTest(case=i):
                self.bad(m)


class CliTests(unittest.TestCase):
    A = ["--as-of", "2026-10-15T00:00:00"]

    def test_exit_codes(self):
        self.assertEqual(main([os.path.join(EX, "good.json")] + self.A + ["--fail-on", "low"]), 0)
        self.assertEqual(main([os.path.join(EX, "risky.json")] + self.A), 0)
        self.assertEqual(main([os.path.join(EX, "risky.json")] + self.A + ["--fail-on", "high"]), 2)

    def test_errors_and_report(self):
        with tempfile.TemporaryDirectory() as t:
            out = os.path.join(t, "r.json")
            main([os.path.join(EX, "risky.json"), "--output", out] + self.A)
            rep = json.load(open(out, encoding="utf-8"))
            self.assertIn("Not tested against a live tenancy", rep["disclaimer"])
            self.assertEqual(rep["as_of"], "2026-10-15T00:00:00")
            bad = os.path.join(t, "b.json")
            open(bad, "w").write("{x")
            self.assertEqual(main([bad]), 1)
            self.assertEqual(main([os.path.join(EX, "good.json"), "--as-of", "yesterday"]), 1)
            self.assertEqual(main([os.path.join(t, "none.json")]), 1)


if __name__ == "__main__":
    unittest.main()
