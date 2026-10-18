"""Resources with several policies: strictest frequency and longest retention win."""
import unittest
from datetime import datetime

from bk_check import analysis, model

NOW = datetime(2026, 10, 15)


def run(d):
    return analysis.analyze(model.load(d), NOW)


def rules(d):
    return {f.rule for f in run(d)}


def inv(policies, resource):
    d = {"policies": policies,
         "resources": [dict({"name": "r", "kind": "database", "region": "ap-mumbai-1", "tier": "standard",
                              "rpo_hours": 24, "last_backup": "2026-10-14T12:00:00",
                              "last_restore_test": "2026-09-01T00:00:00"}, **resource)]}
    return d


P6 = {"name": "fast", "frequency_hours": 6, "retention_days": 7}
P24 = {"name": "slowish", "frequency_hours": 24, "retention_days": 30}


class MultiPolicyTests(unittest.TestCase):
    def test_single_policy_key_and_list_are_equivalent(self):
        a = rules(inv([P24], {"policy": "slowish"}))
        b = rules(inv([P24], {"policies": ["slowish"]}))
        self.assertEqual(a, b)
        self.assertEqual(a, set())                      # the single-policy case is unchanged

    def test_strictest_frequency_wins(self):
        d = inv([P6, P24], {"policies": ["slowish", "fast"]})
        self.assertNotIn("BK003", rules(d))             # 6h <= 24h RPO
        d["resources"][0]["rpo_hours"] = 5
        f = [x for x in run(d) if x.rule == "BK003"]
        self.assertEqual(f[0].evidence["frequency_hours"], 6)

    def test_longest_retention_wins(self):
        d = inv([P6, P24], {"policies": ["fast", "slowish"]})
        self.assertNotIn("BK004", rules(d))             # 30 days >= 14
        d["policies"] = [P6, {"name": "short", "frequency_hours": 24, "retention_days": 10}]
        d["resources"][0]["policies"] = ["fast", "short"]
        f = [x for x in run(d) if x.rule == "BK004"]
        self.assertEqual(f[0].evidence["retention_days"], 10)

    def test_copy_on_any_policy_satisfies_critical(self):
        d = inv([P24, {"name": "xr", "frequency_hours": 24, "retention_days": 35, "copy_region": "ap-hyderabad-1"}],
                {"policies": ["slowish", "xr"], "tier": "critical"})
        self.assertNotIn("BK005", rules(d))
        d["resources"][0]["policies"] = ["slowish"]
        self.assertIn("BK005", rules(d))

    def test_same_region_copy_flagged_per_policy(self):
        d = inv([P24, {"name": "local-copy", "frequency_hours": 24, "retention_days": 30, "copy_region": "ap-mumbai-1"}],
                {"policies": ["slowish", "local-copy"]})
        f = [x for x in run(d) if x.rule == "BK006"]
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0].evidence["policy"], "local-copy")

    def test_single_key_and_list_merge(self):
        d = inv([P6, P24], {"policy": "fast", "policies": ["slowish"]})
        self.assertNotIn("BK003", rules(d))
        self.assertNotIn("BK009", rules(d))             # both policies count as used

    def test_missing_names_reported_individually(self):
        d = inv([P24], {"policies": ["ghost-a", "slowish", "ghost-b"]})
        f = [x for x in run(d) if x.rule == "BK008"]
        self.assertEqual({x.evidence["policy"] for x in f}, {"ghost-a", "ghost-b"})
        self.assertNotIn("BK001", rules(d))             # it does have policies, just dangling ones

    def test_empty_list_means_no_policy(self):
        f = [x for x in run(inv([], {"policies": []})) if x.rule == "BK001"]
        self.assertEqual(len(f), 1)

    def test_duplicate_in_list_is_rejected(self):
        d = inv([P24], {"policies": ["slowish", "slowish"]})
        with self.assertRaises(model.ModelError):
            model.load(d)
        d = inv([P24], {"policy": "slowish", "policies": ["slowish"]})
        with self.assertRaises(model.ModelError):
            model.load(d)

    def test_list_validation(self):
        for bad in ("slowish", [7], [""], [None]):
            with self.subTest(bad=bad):
                with self.assertRaises(model.ModelError):
                    model.load(inv([P24], {"policies": bad}))


if __name__ == "__main__":
    unittest.main()
