import json
import os
import tempfile
import unittest
from datetime import datetime

from bk_check import analysis, model
from bk_check.cli import main
from bk_check.sarif import LEVEL, RULES, to_sarif

EX = os.path.join(os.path.dirname(__file__), "..", "examples")
NOW = datetime(2026, 10, 15)


def findings(n="risky.json"):
    return analysis.analyze(model.load_file(os.path.join(EX, n)), NOW)


class SarifTests(unittest.TestCase):
    def test_shape_and_levels(self):
        fs = findings()
        doc = to_sarif(fs, "examples/risky.json")
        self.assertEqual(doc["version"], "2.1.0")
        self.assertEqual(doc["runs"][0]["tool"]["driver"]["name"], "oci-backup-readiness")
        self.assertEqual(LEVEL, {"high": "error", "medium": "warning", "low": "note"})
        for f, r in zip(fs, doc["runs"][0]["results"]):
            self.assertEqual((r["ruleId"], r["level"]), (f.rule, LEVEL[f.severity]))

    def test_rules_cover_all_and_indexes_match(self):
        run = to_sarif(findings(), "x")["runs"][0]
        rules = run["tool"]["driver"]["rules"]
        self.assertEqual(len(rules), 13)
        self.assertEqual({f.rule for f in findings()}, set(RULES))
        for r in run["results"]:
            self.assertEqual(rules[r["ruleIndex"]]["id"], r["ruleId"])

    def test_empty_and_location(self):
        self.assertEqual(to_sarif(findings("good.json"), "g")["runs"][0]["results"], [])
        loc = to_sarif(findings(), "d/i.json")["runs"][0]["results"][0]["locations"][0]
        self.assertEqual(loc["physicalLocation"]["artifactLocation"]["uri"], "d/i.json")

    def test_cli(self):
        a = ["--as-of", "2026-10-15T00:00:00"]
        with tempfile.TemporaryDirectory() as t:
            s = os.path.join(t, "r.sarif")
            self.assertEqual(main([os.path.join(EX, "risky.json"), "--output", s, "--format", "sarif"] + a), 0)
            self.assertEqual(len(json.load(open(s, encoding="utf-8"))["runs"][0]["results"]), len(findings()))
            self.assertEqual(main([os.path.join(EX, "good.json"), "--format", "sarif"] + a), 1)


if __name__ == "__main__":
    unittest.main()
