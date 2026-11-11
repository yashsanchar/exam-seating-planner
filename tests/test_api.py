"""API tests (FastAPI TestClient - no server needed).  Run: python -m unittest discover -s tests -t ."""

import csv
import io
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app as app_module

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def sample_files():
    return {name: (f"{name}.csv", (SAMPLE / f"{name}.csv").read_bytes(), "text/csv")
            for name in ("students", "rooms", "schedule")}


class ApiTests(unittest.TestCase):
    def setUp(self):
        app_module.state.__init__()      # fresh in-memory state for every test
        self.client = TestClient(app_module.app)

    def load_demo(self):
        return self.client.post("/api/data", data={"demo": "true"})

    def test_options(self):
        body = self.client.get("/api/options").json()
        self.assertIn("fourway", body["rules"])
        self.assertIn("hybrid", body["strategies"])

    def test_demo_load_summary(self):
        r = self.load_demo()
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreater(body["students"], 0)
        self.assertGreater(len(body["rooms"]), 0)
        self.assertGreater(len(body["sessions"]), 0)
        self.assertEqual(self.client.get("/api/data").json()["students"], body["students"])

    def test_upload_three_files(self):
        r = self.client.post("/api/data", files=sample_files())
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.json()["sessions"]), 0)

    def test_upload_needs_the_student_list(self):
        files = sample_files()
        del files["students"]
        r = self.client.post("/api/data", files=files)
        self.assertEqual(r.status_code, 400)
        self.assertIn("student", r.json()["detail"].lower())

    def test_students_only_uses_builtin_rooms_and_timetable(self):
        r = self.client.post("/api/data", files={"students": sample_files()["students"]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual([x["room_id"] for x in body["rooms"]], ["B-002", "B-003", "B-004", "B-005"])
        self.assertTrue(all(x["provisional"] for x in body["rooms"]))
        self.assertEqual(len(body["sessions"]), 12)

    def test_rooms_and_schedule_upload_replace_builtin(self):
        self.client.post("/api/data", files=sample_files())
        self.assertEqual(self.client.get("/api/rooms").json()["rooms"][0]["room_id"], "R101")
        rows = self.client.get("/api/timetable").json()["rows"]
        self.assertEqual(rows[0]["course"], "CS201")

    def test_empty_optional_file_box_is_ignored(self):
        files = {"students": sample_files()["students"], "rooms": ("", b"", "application/octet-stream")}
        r = self.client.post("/api/data", files=files)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["rooms"][0]["room_id"], "B-002")

    def test_bad_rooms_upload_changes_nothing(self):
        files = sample_files()
        files["rooms"] = ("rooms.csv", b"foo,bar\n1,2\n", "text/csv")
        self.assertEqual(self.client.post("/api/data", files=files).status_code, 400)
        self.assertEqual(self.client.get("/api/data").status_code, 409)               # students not half-loaded
        self.assertEqual(self.client.get("/api/rooms").json()["rooms"][0]["room_id"], "B-002")

    def test_rooms_get_save_reset(self):
        rooms = self.client.get("/api/rooms").json()["rooms"]
        self.assertEqual(len(rooms), 4)
        self.assertEqual(rooms[0]["capacity"], 39)
        rooms[0]["layout"][0] = "000000000"
        rooms[0]["provisional"] = False
        saved = self.client.put("/api/rooms", json={"rooms": rooms}).json()["rooms"]
        self.assertEqual(saved[0]["capacity"], 39 - 7)
        self.assertFalse(saved[0]["provisional"])
        self.assertEqual(self.client.get("/api/rooms").json()["rooms"][0]["capacity"], 32)
        self.assertEqual(self.client.post("/api/rooms/reset").json()["rooms"][0]["capacity"], 39)

    def test_rooms_bad_save_is_rejected_and_keeps_old(self):
        r = self.client.put("/api/rooms", json={"rooms": [{"room_id": "A", "layout": ["000"]}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("no seats", r.json()["detail"])
        self.assertEqual(len(self.client.get("/api/rooms").json()["rooms"]), 4)

    def test_editing_rooms_or_timetable_drops_the_old_plan(self):
        self.client.post("/api/data", files={"students": ("students.csv", (SAMPLE / "students_placeholder.csv").read_bytes(), "text/csv")})
        self.assertEqual(self.client.post("/api/plan", json={}).json()["failed_sessions"], 0)
        self.assertEqual(self.client.get("/api/download/csv").status_code, 200)
        self.client.put("/api/rooms", json={"rooms": self.client.get("/api/rooms").json()["rooms"]})
        self.assertEqual(self.client.get("/api/download/csv").status_code, 409)
        self.client.post("/api/plan", json={})
        self.client.put("/api/timetable", json={"rows": self.client.get("/api/timetable").json()["rows"]})
        self.assertEqual(self.client.get("/api/download/csv").status_code, 409)

    def test_plan_uses_edited_rooms(self):
        self.client.post("/api/data", files={"students": ("students.csv", (SAMPLE / "students_placeholder.csv").read_bytes(), "text/csv")})
        rooms = self.client.get("/api/rooms").json()["rooms"]
        for r in rooms[1:]:
            r["available"] = False                       # only B-002 (39 seats) left: 118 students cannot fit
        self.client.put("/api/rooms", json={"rooms": rooms})
        body = self.client.post("/api/plan", json={}).json()
        self.assertGreater(body["failed_sessions"], 0)
        self.assertTrue(any(s["error"] for s in body["sessions"]))

    def test_plan_marks_provisional_rooms(self):
        self.client.post("/api/data", files={"students": ("students.csv", (SAMPLE / "students_placeholder.csv").read_bytes(), "text/csv")})
        body = self.client.post("/api/plan", json={}).json()
        self.assertTrue(all(r["provisional"] for s in body["sessions"] for r in s["rooms"]))

    def test_timetable_get_save_reset(self):
        t = self.client.get("/api/timetable").json()
        self.assertEqual((len(t["rows"]), t["days"], t["sessions"]), (36, 12, 12))
        rows = t["rows"]
        rows[0]["course"] = "ds5a - 621x"
        saved = self.client.put("/api/timetable", json={"rows": rows}).json()
        self.assertEqual(saved["rows"][0]["course"], "DS5A-621X")
        rows.append({"date": "2026-12-10", "slot": "11:00 AM - 2:00 PM", "course": "", "course_name": "", "group": ""})
        r = self.client.put("/api/timetable", json={"rows": rows})
        self.assertEqual(r.status_code, 400)
        self.assertIn("row 37", r.json()["detail"])
        self.assertEqual(self.client.post("/api/timetable/reset").json()["rows"][0]["course"], "DS5A-621")

    def test_upload_bad_content_gives_readable_error(self):
        files = sample_files()
        files["rooms"] = ("rooms.csv", b"foo,bar\n1,2\n", "text/csv")
        r = self.client.post("/api/data", files=files)
        self.assertEqual(r.status_code, 400)
        self.assertTrue(r.json()["detail"])

    def test_upload_empty_file(self):
        files = sample_files()
        files["students"] = ("students.csv", b"", "text/csv")
        self.assertEqual(self.client.post("/api/data", files=files).status_code, 400)

    def test_plan_before_data(self):
        self.assertEqual(self.client.post("/api/plan", json={}).status_code, 409)

    def test_plan_has_no_conflicts_for_every_rule_and_strategy(self):
        self.load_demo()
        for rule in ("horizontal", "fourway"):
            for strategy in ("greedy", "backtracking", "hybrid"):
                body = self.client.post("/api/plan", json={"rule": rule, "strategy": strategy}).json()
                self.assertEqual(body["total_conflicts"], 0, (rule, strategy))
                self.assertEqual(body["failed_sessions"], 0, (rule, strategy))
                self.assertGreater(len(body["sessions"]), 0)

    def test_plan_defaults(self):
        self.load_demo()
        body = self.client.post("/api/plan", json={}).json()
        self.assertEqual((body["rule"], body["strategy"]), ("fourway", "hybrid"))
        seat = body["sessions"][0]["rooms"][0]["seats"][0]
        self.assertIn("row", seat)

    def test_unknown_rule_and_strategy(self):
        self.load_demo()
        self.assertEqual(self.client.post("/api/plan", json={"rule": "diagonal"}).status_code, 400)
        self.assertEqual(self.client.post("/api/plan", json={"strategy": "magic"}).status_code, 400)

    def test_downloads(self):
        self.load_demo()
        self.assertEqual(self.client.get("/api/download/csv").status_code, 409)   # no plan yet
        self.client.post("/api/plan", json={})
        r = self.client.get("/api/download/csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("attachment", r.headers["content-disposition"])
        rows = list(csv.reader(io.StringIO(r.text)))
        self.assertEqual(rows[0][:3], ["date", "slot", "room"])
        self.assertGreater(len(rows), 1)
        self.assertIn("sessions", self.client.get("/api/download/json").json())
        self.assertIn("students", self.client.get("/api/download/txt").text)
        self.assertEqual(self.client.get("/api/download/pdf").status_code, 404)

    def test_new_upload_clears_old_plan(self):
        self.load_demo()
        self.client.post("/api/plan", json={})
        self.load_demo()
        self.assertEqual(self.client.get("/api/download/csv").status_code, 409)

    def test_benchmarks(self):
        body = self.client.get("/api/benchmarks").json()
        self.assertGreater(len(body["rows"]), 0)
        self.assertIn("variant", body["rows"][0])
        self.assertIn("note", body)



PDFS = Path(__file__).resolve().parent.parent / "data" / "pdf_samples"


def pdf_file(name):
    return (name, (PDFS / name).read_bytes(), "application/pdf")


class PdfApiTests(unittest.TestCase):
    def setUp(self):
        app_module.state.__init__()
        self.client = TestClient(app_module.app)

    def preview(self, kind, name):
        return self.client.post("/api/pdf/preview", data={"kind": kind}, files={"file": pdf_file(name)})

    def confirm_all_lists(self):
        for name in ("mba_ba_2025-27.pdf", "msc_dsa_2025-27.pdf", "mtech_2025-30.pdf", "mtech_2024-29.pdf"):
            body = self.preview("students", name).json()
            r = self.client.post("/api/students/confirm", json={"group": body["suggested_group"], "rows": body["rows"]})
            self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_student_preview_loads_nothing(self):
        r = self.preview("students", "mtech_2025-30.pdf")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["included"], 67)
        self.assertEqual(body["suggested_group"], "M.Tech sem 3")
        self.assertIn("M.Tech sem 3", body["groups"])
        self.assertEqual(self.client.get("/api/data").status_code, 409)          # still nothing loaded

    def test_confirm_loads_and_plans_with_no_conflicts(self):
        summary = self.confirm_all_lists()
        self.assertEqual(summary["students"], 163)
        self.assertEqual({c["group"] for c in summary["cohorts"]},
                         {"MBA BA sem 3", "MSc DSA sem 3", "M.Tech sem 3", "M.Tech sem 5"})
        plan = self.client.post("/api/plan", json={"rule": "fourway", "strategy": "hybrid"}).json()
        self.assertEqual(plan["failed_sessions"], 0)
        self.assertEqual(plan["total_conflicts"], 0)

    def test_fixed_name_and_unticked_row_are_respected(self):
        body = self.preview("students", "mba_ba_2025-27.pdf").json()
        body["rows"][0]["name"] = "Fixed Name"
        body["rows"][1]["include"] = False
        r = self.client.post("/api/students/confirm", json={"group": "MBA BA sem 3", "rows": body["rows"]})
        self.assertEqual(r.json()["students"], 27)

    def test_confirm_needs_a_known_group_and_complete_rows(self):
        rows = self.preview("students", "mba_ba_2025-27.pdf").json()["rows"]
        self.assertEqual(self.client.post("/api/students/confirm", json={"group": "", "rows": rows}).status_code, 400)
        self.assertEqual(self.client.post("/api/students/confirm", json={"group": "Nope", "rows": rows}).status_code, 400)
        rows[0]["name"] = ""
        self.assertEqual(self.client.post("/api/students/confirm", json={"group": "MBA BA sem 3", "rows": rows}).status_code, 400)

    def test_loading_a_group_again_replaces_it_and_remove_works(self):
        self.confirm_all_lists()
        self.confirm_all_lists()
        self.assertEqual(self.client.get("/api/data").json()["students"], 163)
        self.client.delete("/api/students/MBA%20BA%20sem%203")
        self.assertEqual(self.client.get("/api/data").json()["students"], 135)

    def test_scanned_pdf_gives_plain_message(self):
        for kind in ("students", "schedule", "rooms"):
            r = self.preview(kind, "timetable_scanned.pdf")
            self.assertEqual(r.status_code, 400)
            self.assertIn("no readable text", r.json()["detail"])

    def test_text_pdf_tables_for_schedule_and_rooms(self):
        sched = self.preview("schedule", "schedule_text_sample.pdf").json()
        self.assertEqual(sched["rows"][0]["date"], "2026-11-23")
        rooms = self.preview("rooms", "rooms_text_sample.pdf").json()
        self.assertEqual([x["room_id"] for x in rooms["rooms"]], ["A-101", "A-102"])
        self.assertEqual(self.client.get("/api/rooms").json()["rooms"][0]["room_id"], "B-002")   # preview changed nothing
        self.assertEqual(self.client.put("/api/rooms", json={"rooms": rooms["rooms"]}).status_code, 200)

    def test_pdf_sent_to_the_plain_upload_is_refused_with_a_hint(self):
        r = self.client.post("/api/data", files={"students": pdf_file("mba_ba_2025-27.pdf")})
        self.assertEqual(r.status_code, 400)
        self.assertIn("PDF", r.json()["detail"])

    def test_not_a_pdf_and_bad_kind(self):
        r = self.client.post("/api/pdf/preview", data={"kind": "students"}, files={"file": ("a.pdf", b"nope", "application/pdf")})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/pdf/preview", data={"kind": "x"}, files={"file": pdf_file("mba_ba_2025-27.pdf")})
        self.assertEqual(r.status_code, 400)

    def test_csv_upload_replaces_pdf_lists_and_tables_endpoint(self):
        self.confirm_all_lists()
        self.client.post("/api/data", files={"students": sample_files()["students"]})
        self.assertEqual(self.client.get("/api/data").json()["cohorts"], [])
        r = self.client.post("/api/tables", files={"rooms": sample_files()["rooms"]})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get("/api/rooms").json()["rooms"][0]["room_id"], "R101")
        self.assertEqual(self.client.post("/api/tables").status_code, 400)

    def test_xlsx_student_file(self):
        import io as _io
        import openpyxl
        wb = openpyxl.Workbook()
        for row in (["Roll No", "Student Name", "Paper Code"], ["A1", "Asha", "P1"], ["A2", "Ravi", "P1"]):
            wb.active.append(row)
        buf = _io.BytesIO()
        wb.save(buf)
        r = self.client.post("/api/data", files={"students": ("s.xlsx", buf.getvalue(), "application/octet-stream")})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["students"], 2)

if __name__ == "__main__":
    unittest.main()
