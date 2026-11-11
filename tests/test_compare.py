"""Tests for the strategy comparison export (step 2)."""

import csv
import io
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module
from seating import compare_strategies, load_all, strategy_names
from seating.compare import comparison_table

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def sample_data():
    return load_all(SAMPLE / "students.csv", SAMPLE / "rooms.csv", SAMPLE / "schedule.csv")


class CompareTests(unittest.TestCase):
    def test_one_row_per_session_with_every_strategy(self):
        data = sample_data()
        rows = compare_strategies(data, "fourway", repeats=1)
        self.assertEqual(len(rows), len(data.sessions))
        for row in rows:
            for name in strategy_names():
                self.assertEqual(row[f"{name}_result"], "ok")
                self.assertGreater(row[f"{name}_steps"], 0)
                self.assertGreaterEqual(row[f"{name}_ms"], 0)

    def test_table_has_header_and_total_line(self):
        data = sample_data()
        table = comparison_table(compare_strategies(data, "horizontal", repeats=1), "horizontal")
        self.assertEqual(len(table), len(data.sessions) + 2)
        self.assertEqual(table[-1][0], "TOTAL")
        self.assertEqual({len(line) for line in table}, {len(table[0])})   # same width everywhere
        self.assertIn("hybrid search steps", table[0])

    def test_hybrid_never_takes_fewer_steps_than_greedy(self):
        # hybrid = greedy first, so it can only add work when greedy fails
        for row in compare_strategies(sample_data(), "fourway", repeats=1):
            self.assertGreaterEqual(row["hybrid_steps"], row["greedy_steps"])


class CompareApiTests(unittest.TestCase):
    def setUp(self):
        app_module.state.__init__()
        self.client = TestClient(app_module.app)

    def test_needs_data_first(self):
        self.assertEqual(self.client.get("/api/compare").status_code, 409)

    def test_csv_download(self):
        self.client.post("/api/data", data={"demo": "true"})
        r = self.client.get("/api/compare?rule=fourway")
        self.assertEqual(r.status_code, 200)
        self.assertIn("strategy_comparison.csv", r.headers["content-disposition"])
        lines = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        self.assertEqual(lines[0][0], "Date")
        self.assertEqual(lines[-1][0], "TOTAL")

    def test_unknown_rule(self):
        self.client.post("/api/data", data={"demo": "true"})
        self.assertEqual(self.client.get("/api/compare?rule=nope").status_code, 400)


if __name__ == "__main__":
    unittest.main()
