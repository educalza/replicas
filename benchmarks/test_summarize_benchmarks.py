"""Verifica as medias e a rejeicao de resultados incompletos/divergentes."""

import json
from pathlib import Path
import statistics
import tempfile
import unittest

from run_benchmarks import MODES, PROFILES, parse_metrics, summarize
from summarize_benchmarks import aggregate, write_report


class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        rows = []
        for n, rate in ((1, 100), (2, 200)):
            for profile in PROFILES:
                for mode in MODES:
                    case = self.directory / f"{n}-{profile}-{mode}"
                    case.mkdir()
                    metrics = case / "metrics.txt"
                    metrics.write_text(
                        f"[OVERALL], Throughput(ops/sec), {rate}\n"
                        f"[OVERALL], RunTime(ms), {1000000 / rate}\n"
                        f"[READ], Return=OK, {1000 - n}\n"
                        f"[READ], Return=ERROR, {n}\n"
                        f"[READ], AverageLatency(us), {n * 1000}\n"
                        f"[READ], 95thPercentileLatency(us), {n * 2000}\n",
                        encoding="utf-8")
                    result = summarize(parse_metrics(metrics))
                    result.update({"round": n, "profile": profile, "mode": mode,
                                   "convergence": {"converged": True, "records": 1000,
                                                   "wait_seconds": n}})
                    rows.append(result)
        self.saved = {"metadata": {"repetitions": 2, "operations": 1000, "records": 1000,
                                    "threads": 8, "delay": 1.0}, "results": rows}
        self.save()

    def save(self):
        (self.directory / "results.json").write_text(json.dumps(self.saved), encoding="utf-8")

    def test_arithmetic_mean_sd_units_and_errors(self):
        data = aggregate(self.directory)
        self.assertEqual(data["verified_runs"], 18)
        for group in data["summary"]:
            self.assertEqual(group["n"], 2)
            self.assertEqual(group["statistics"]["ops_sec"]["mean"], 150)
            self.assertAlmostEqual(group["statistics"]["ops_sec"]["sample_sd"], statistics.stdev([100, 200]))
            self.assertEqual(group["statistics"]["read_mean_ms"]["mean"], 1.5)
            self.assertEqual(group["statistics"]["read_p95_ms"]["mean"], 3)
            self.assertIsNone(group["statistics"]["update_mean_ms"]["mean"])
            self.assertEqual(group["total_errors"], 3)
            self.assertAlmostEqual(group["error_rate_percent"], 0.15)
            self.assertAlmostEqual(group["pooled_ops_sec"], 2000 / 15)
        write_report(self.directory, data)
        page = (self.directory / "medias.html").read_text(encoding="utf-8")
        self.assertEqual(page.count("<tr>"), 14)
        self.assertIn("150,00", page)

    def test_missing_or_duplicate_runs_are_rejected(self):
        self.saved["results"].pop()
        self.save()
        with self.assertRaises(ValueError):
            aggregate(self.directory)
        self.saved["results"].append(self.saved["results"][0])
        self.save()
        with self.assertRaises(ValueError):
            aggregate(self.directory)

    def test_modified_summary_is_rejected(self):
        self.saved["results"][0]["ops_sec"] += 1
        self.save()
        with self.assertRaisesRegex(ValueError, "diverge"):
            aggregate(self.directory)


if __name__ == "__main__":
    unittest.main()
