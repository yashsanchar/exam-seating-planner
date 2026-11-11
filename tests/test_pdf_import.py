"""PDF / Excel reading and cohort expansion. Needs pdfplumber (and openpyxl for the Excel test), not FastAPI."""

import tempfile
import unittest
from pathlib import Path

import pdf_import as P
from seating import (ExamPlanner, build_sessions, combine, default_rooms, default_timetable, expand_cohorts,
                     find_conflicts, get_rule, get_strategy, load_rooms, load_schedule_rows, timetable_groups)

PDFS = Path(__file__).resolve().parent.parent / "data" / "pdf_samples"
LISTS = [("mba_ba_2025-27.pdf", "MBA BA sem 3", 28), ("msc_dsa_2025-27.pdf", "MSc DSA sem 3", 23),
         ("mtech_2025-30.pdf", "M.Tech sem 3", 67), ("mtech_2024-29.pdf", "M.Tech sem 5", 45)]


def included(pv):
    return [r for r in pv.rows if r["include"]]


class StudentPdfTests(unittest.TestCase):
    def test_real_lists_have_the_expected_counts_and_group(self):
        for name, group, count in LISTS:
            pv = P.parse_student_pdf(PDFS / name)
            self.assertEqual(len(included(pv)), count, name)
            self.assertEqual(pv.suggested_group, group, name)
            self.assertTrue(all(r["name"] for r in pv.rows), name)

    def test_trailing_cancelled_and_transferred_rows_are_not_loaded(self):
        pv = P.parse_student_pdf(PDFS / "mtech_2024-29.pdf")
        self.assertEqual(len(pv.ignored), 3)
        self.assertTrue(any("CANCELLED" in x for x in pv.ignored))
        self.assertEqual(len(P.parse_student_pdf(PDFS / "mtech_2025-30.pdf").ignored), 1)

    def test_messy_names_are_cleaned(self):
        rows = {r["roll_no"]: r["name"] for r in P.parse_student_pdf(PDFS / "mtech_2025-30.pdf").rows}
        self.assertEqual(rows["DS6A-2529"], "KHUSHI KHANCHANDANI")
        self.assertEqual(rows["DS6A-2511"], "BHAVESH KUMAR SONI")     # blank enrolment number, fee column "1"
        self.assertEqual(rows["DS6A-2521"], "JAGRATI PUNDIR")          # stray "EW" column removed
        msc = {r["roll_no"]: r["name"] for r in P.parse_student_pdf(PDFS / "msc_dsa_2025-27.pdf").rows}
        self.assertEqual(msc["DS5B-2502"], "ANJALI KEWAT")             # "OLD STUDENT" removed
        self.assertEqual(msc["DS5B-2501"], "ABHISHEK")                 # gender column removed

    def test_merged_glued_and_wrapped_text(self):
        text = ["17 DS6A-2417 DE1 F URF UR Y DISHA SIRWANI18 DS6A-2418 DE2 M URO UR Y ESHIT GUPTA\n"
                "19 DS6A\u20132419 F JKM UR Y GURLEEN KAUR CHIBBER\n20 DS6A- 2420 OBCO Y HARSH SINGH\nPANWAR\n"
                "21 DS6A-2421 Y SOMEONE CANCELLED\n22 DS6A-2421 Y SAME ROLL\n9 F URF NOBODY CANCELLED"]
        pv = P.parse_student_text(text)
        names = [r["name"] for r in pv.rows]
        self.assertEqual(names[:4], ["DISHA SIRWANI", "ESHIT GUPTA", "GURLEEN KAUR CHIBBER", "HARSH SINGH PANWAR"])
        self.assertFalse(pv.rows[4]["include"])        # marked cancelled
        self.assertFalse(pv.rows[5]["include"])        # repeated roll number
        self.assertEqual(len(pv.ignored), 1)

    def test_no_roll_numbers_gives_plain_message(self):
        with self.assertRaises(P.PdfProblem) as cm:
            P.parse_student_text(["title\nnothing useful here"])
        self.assertIn("roll numbers", str(cm.exception))

    def test_scanned_pdf_is_rejected_with_plain_message(self):
        scanned = PDFS / "timetable_scanned.pdf"
        for kind, hint in (("students", "CSV"), ("schedule", "timetable table"), ("rooms", "Rooms tab")):
            with self.assertRaises(P.PdfProblem) as cm:
                if kind == "students":
                    P.parse_student_pdf(scanned)
                else:
                    P.pdf_table_to_csv(scanned, kind)
            self.assertIn("no readable text", str(cm.exception))
            self.assertIn(hint, str(cm.exception))

    def test_not_a_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "x.pdf"
            bad.write_bytes(b"this is not a pdf")
            with self.assertRaises(P.PdfProblem):
                P.parse_student_pdf(bad)


class TablePdfTests(unittest.TestCase):
    def test_schedule_table_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.csv"
            path.write_text(P.pdf_table_to_csv(PDFS / "schedule_text_sample.pdf", "schedule"), encoding="utf-8")
            rows = load_schedule_rows(path)
        self.assertEqual(rows[0]["date"], "2026-11-23")                # 23-11-2026 -> ISO
        self.assertEqual(rows[0]["course"], "DS6A-201")                # "DS6A - 201" cleaned
        self.assertEqual(rows[1]["slot"], rows[0]["slot"])             # blank (merged) time cell filled from above
        self.assertEqual(rows[3]["date"], "2026-11-27")                # blank date cell filled from above
        sessions, _names, _w = build_sessions(rows, "row", 1)
        self.assertEqual(len(sessions), 3)

    def test_rooms_table_pdf(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.csv"
            path.write_text(P.pdf_table_to_csv(PDFS / "rooms_text_sample.pdf", "rooms"), encoding="utf-8")
            rooms = load_rooms(path)
        self.assertEqual([(r.room_id, r.capacity) for r in rooms], [("A-101", 22), ("A-102", 25)])


class ExcelTests(unittest.TestCase):
    def test_xlsx_becomes_csv(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.xlsx"
            wb = openpyxl.Workbook()
            wb.active.append(["Roll No", "Student Name", "Paper Code"])
            wb.active.append(["A1", "Asha", "P1"])
            wb.save(path)
            text = P.excel_to_csv(path)
        self.assertIn("Roll No,Student Name,Paper Code", text)
        self.assertIn("A1,Asha,P1", text)


class CohortTests(unittest.TestCase):
    def setUp(self):
        self.tt = default_timetable()
        self.cohorts = {}
        for name, group, _ in LISTS:
            pv = P.parse_student_pdf(PDFS / name)
            self.cohorts[group] = [(r["roll_no"], r["name"], False) for r in included(pv)]

    def test_each_student_gets_the_papers_of_their_group(self):
        students, _names, warnings = expand_cohorts(self.cohorts, self.tt)
        self.assertEqual(warnings, [])
        self.assertEqual(len({s.roll_no for s in students}), 163)
        courses = {s.course for s in students}
        self.assertNotIn("DS5A-623", courses)                          # MBA does not write Marketing Analytics
        self.assertEqual(sum(1 for s in students if s.course == "DS6A-603"), 28 + 23)   # shared paper

    def test_group_without_papers_is_reported(self):
        _s, _n, warnings = expand_cohorts({"Unknown batch": [("X-1", "A", False)]}, self.tt)
        self.assertIn("Unknown batch", warnings[0])

    def test_timetable_groups_in_order(self):
        self.assertEqual(timetable_groups(self.tt)[:2], ["MBA BA sem 3", "MSc DSA sem 3"])

    def test_real_lists_can_be_seated_without_conflicts(self):
        students, names, w = expand_cohorts(self.cohorts, self.tt)
        sessions, cn, cw = build_sessions(self.tt, "row", 1)
        data = combine(students, names, w, default_rooms(), sessions, cn, cw)
        for rule_name in ("horizontal", "fourway"):
            rule = get_rule(rule_name)
            plans = ExamPlanner(data, rule, get_strategy("hybrid")).plan_all()
            self.assertTrue(all(p.ok for p in plans), rule_name)
            self.assertEqual(sum(len(find_conflicts(rp.room, rule)) for p in plans for rp in p.room_plans), 0)


if __name__ == "__main__":
    unittest.main()
