"""The two DUMMY student lists (M.Tech sem 7 and sem 9). Needs pdfplumber only, not FastAPI."""

import re
import unittest
from pathlib import Path

import pdf_import as P
from seating import (ExamPlanner, build_sessions, combine, default_rooms, default_timetable, expand_cohorts,
                     find_conflicts, get_rule, get_strategy)

PDFS = Path(__file__).resolve().parent.parent / "data" / "pdf_samples"
DUMMIES = [("DUMMY_MTECH_AIDS_2023-2028_7TH_SEM.pdf", "M.Tech sem 7", "DS6A-23", 55),
           ("DUMMY_MTECH_AIDS_2022-2027_9TH_SEM.pdf", "M.Tech sem 9", "DS6A-22", 45)]
REAL = ["mba_ba_2025-27.pdf", "msc_dsa_2025-27.pdf", "mtech_2024-29.pdf", "mtech_2025-30.pdf"]


class DummyListTests(unittest.TestCase):
    def test_every_row_is_read_and_the_group_is_suggested(self):
        for name, group, prefix, count in DUMMIES:
            pv = P.parse_student_pdf(PDFS / name)
            self.assertEqual(len(pv.rows), count, name)
            self.assertTrue(all(r["include"] and not r["note"] for r in pv.rows), name)
            self.assertEqual(pv.suggested_group, group, name)
            self.assertEqual([], pv.warnings + pv.ignored, name)
            self.assertEqual([f"{prefix}{i:02d}" for i in range(1, count + 1)], [r["roll_no"] for r in pv.rows], name)

    def test_names_are_sorted_unique_letters_only(self):
        seen = set()
        for name, *_ in DUMMIES:
            names = [r["name"] for r in P.parse_student_pdf(PDFS / name).rows]
            self.assertEqual(sorted(names), names, name)
            for n in names:
                self.assertRegex(n, r"^[A-Z]+( [A-Z]+){1,2}$")
                self.assertNotIn(n, seen)
                seen.add(n)

    def test_no_dummy_name_is_a_real_name(self):
        real_full, real_pairs = set(), set()
        for name in REAL:
            if not (PDFS / name).exists():
                self.skipTest(f"{name} is not in data/pdf_samples")
            for r in P.parse_student_pdf(PDFS / name).rows:
                real_full.add(r["name"]); real_pairs.add((r["name"].split()[0], r["name"].split()[-1]))
        for name, *_ in DUMMIES:
            for r in P.parse_student_pdf(PDFS / name).rows:
                parts = r["name"].split()
                self.assertNotIn(r["name"], real_full)
                self.assertNotIn((parts[0], parts[-1]), real_pairs)

    def test_pdf_has_no_phone_email_or_fee_text(self):
        for name, *_ in DUMMIES:
            for page in P._pages_text(PDFS / name, "students"):
                self.assertNotIn("@", page)
                self.assertIsNone(re.search(r"\d{7,}", page))
                for line in page.splitlines():
                    if re.match(r"^\d", line):        # a student row: serial, roll number, name and nothing else
                        self.assertRegex(line, r"^\d{1,2} DS6A-\d{4} [A-Z ]+$")

    def test_dummy_lists_load_and_the_plan_has_no_conflicts(self):
        cohorts = {}
        for name, group, *_ in DUMMIES:
            cohorts[group] = [(r["roll_no"], r["name"], False) for r in P.parse_student_pdf(PDFS / name).rows]
        for name in REAL:                                  # with the real lists loaded as well, like the real app
            if not (PDFS / name).exists():
                self.skipTest(f"{name} is not in data/pdf_samples")
        for name, group in [("mba_ba_2025-27.pdf", "MBA BA sem 3"), ("msc_dsa_2025-27.pdf", "MSc DSA sem 3"),
                            ("mtech_2025-30.pdf", "M.Tech sem 3"), ("mtech_2024-29.pdf", "M.Tech sem 5")]:
            cohorts[group] = [(r["roll_no"], r["name"], False) for r in P.parse_student_pdf(PDFS / name).rows if r["include"]]
        timetable = default_timetable()
        students, names, warns = expand_cohorts(cohorts, timetable)
        sessions, cnames, cwarns = build_sessions(timetable, "row", 1)
        data = combine(students, names, warns, default_rooms(), sessions, cnames, cwarns)
        rule = get_rule("fourway")
        plans = ExamPlanner(data, rule, get_strategy("hybrid")).plan_all()
        self.assertTrue(all(p.ok for p in plans), [p.error for p in plans if not p.ok])
        self.assertEqual(0, sum(len(find_conflicts(rp.room, rule)) for p in plans for rp in p.room_plans))


if __name__ == "__main__":
    unittest.main()
