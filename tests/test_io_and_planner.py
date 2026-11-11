import json
import tempfile
import unittest
from pathlib import Path

from seating import (DataFormatError, ExamPlanner, export_csv, export_json, export_text, find_conflicts,
                     get_rule, get_strategy, load_all, load_rooms, load_schedule, load_students)

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def write(tmp, name, text, encoding="utf-8"):
    p = Path(tmp) / name
    p.write_text(text, encoding=encoding)
    return p


class LoaderTests(unittest.TestCase):
    def test_flexible_headers_bom_and_semicolons(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "s.csv", "Roll Number;Full Name;Subject Code\n 24cs 001 ;Ann   Lee;cs 201\n", "utf-8-sig")
            students, _, warnings = load_students(p)
            self.assertEqual((students[0].roll_no, students[0].name, students[0].course),
                             ("24CS001", "Ann Lee", "CS201"))
            self.assertEqual(warnings, [])

    def test_duplicates_and_blank_rows_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "s.csv", "roll,name,course\n1,A,X\n1,A,X\n,B,X\n2,C,X\n")
            students, _, warnings = load_students(p)
            self.assertEqual(len(students), 2)
            self.assertEqual(len(warnings), 2)

    def test_missing_column_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "s.csv", "roll,name\n1,A\n")
            with self.assertRaises(DataFormatError) as ctx:
                load_students(p)
            self.assertIn("course", str(ctx.exception))

    def test_column_map_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "s.csv", "ID Card,Who,Paper\n7,Zed,P1\n")
            students, _, _ = load_students(p, {"roll_no": "ID Card", "name": "Who", "course": "Paper"})
            self.assertEqual(students[0].roll_no, "7")

    def test_rooms_rows_cols_blocked_layout_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "r.csv",
                      "room,rows,cols,blocked,layout,available\n"
                      "A,3,4,1-1;3-4,,yes\n"
                      "B,,,,111/101/11,no\n")
            a, b = load_rooms(p)
            self.assertEqual((a.rows, a.cols, a.capacity), (3, 4, 10))
            self.assertEqual((b.rows, b.cols, b.capacity, b.available), (3, 3, 7, False))

    def test_bad_room_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            for body in ("room,rows,cols,blocked\nA,2,2,9-9\n", "room,rows,cols\nA,x,2\n",
                         "room,rows,cols\nA,2,2\nA,3,3\n", "room,layout\nA,11?1\n"):
                with self.assertRaises(DataFormatError):
                    load_rooms(write(tmp, "r.csv", body))

    def test_schedule_groups_by_date_and_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "x.csv", "date,time,subject\n1-Dec,AM,a1\n1-Dec,AM,b1\n1-Dec,PM,c1\n")
            sessions, _, _ = load_schedule(p)
            self.assertEqual([s.courses for s in sessions], [("A1", "B1"), ("C1",)])


class PlannerTests(unittest.TestCase):
    def test_sample_data_both_rules_all_strategies(self):
        data = load_all(SAMPLE / "students.csv", SAMPLE / "rooms.csv", SAMPLE / "schedule.csv")
        for rule_name in ("horizontal", "fourway"):
            for strategy in ("greedy", "hybrid"):
                rule = get_rule(rule_name)
                plans = ExamPlanner(data, rule, get_strategy(strategy)).plan_all()
                self.assertEqual(len(plans), 6)
                for plan in plans:
                    self.assertTrue(plan.ok, plan.error)
                    seated = sum(rp.room.occupied for rp in plan.room_plans)
                    self.assertEqual(seated, plan.student_count)
                    for rp in plan.room_plans:
                        self.assertEqual(find_conflicts(rp.room, rule), [])
                    self.assertNotIn("R204", [rp.room.room_id for rp in plan.room_plans])  # unavailable room

    def test_every_student_seated_once_per_session(self):
        data = load_all(SAMPLE / "students.csv", SAMPLE / "rooms.csv", SAMPLE / "schedule.csv")
        for plan in ExamPlanner(data, get_rule("fourway"), get_strategy("hybrid")).plan_all():
            rolls = [s.roll_no for rp in plan.room_plans for s in rp.room.students()]
            self.assertEqual(len(rolls), len(set(rolls)))

    def test_not_enough_seats_is_reported_not_crashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = write(tmp, "s.csv", "roll,name,course\n" + "".join(f"{i},N{i},A\n" for i in range(10)))
            r = write(tmp, "r.csv", "room,rows,cols\nX,2,2\n")
            c = write(tmp, "c.csv", "date,slot,course\nd,s,A\n")
            plan = ExamPlanner(load_all(s, r, c), get_rule("fourway"), get_strategy("hybrid")).plan_all()[0]
            self.assertFalse(plan.ok)
            self.assertIn("Not enough", plan.error)

    def test_clash_between_two_papers_in_one_slot(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = write(tmp, "s.csv", "roll,name,course\n1,A,P\n1,A,Q\n2,B,P\n3,C,Q\n")
            r = write(tmp, "r.csv", "room,rows,cols\nX,3,3\n")
            c = write(tmp, "c.csv", "date,slot,course\nd,s,P\nd,s,Q\n")
            plan = ExamPlanner(load_all(s, r, c), get_rule("fourway"), get_strategy("hybrid")).plan_all()[0]
            self.assertTrue(plan.ok)
            self.assertEqual(plan.student_count, 3)
            self.assertTrue(any("Clash" in w for w in plan.warnings))

    def test_tight_room_forces_extra_room_retry(self):
        # One room fits the headcount but not the pattern; a second room must be added.
        with tempfile.TemporaryDirectory() as tmp:
            s = write(tmp, "s.csv", "roll,name,course\n" + "".join(f"{i:02d},N,A\n" for i in range(5))
                      + "".join(f"{i + 10},N,B\n" for i in range(3)))
            r = write(tmp, "r.csv", "room,rows,cols\nX,1,8\nY,1,4\n")
            c = write(tmp, "c.csv", "date,slot,course\nd,s,A\nd,s,B\n")
            plan = ExamPlanner(load_all(s, r, c), get_rule("horizontal"), get_strategy("hybrid")).plan_all()[0]
            self.assertTrue(plan.ok, plan.error)

    def test_exports(self):
        data = load_all(SAMPLE / "students.csv", SAMPLE / "rooms.csv", SAMPLE / "schedule.csv")
        plans = ExamPlanner(data, get_rule("fourway"), get_strategy("hybrid")).plan_all()
        with tempfile.TemporaryDirectory() as tmp:
            n = export_csv(plans, data, Path(tmp) / "a.csv")
            export_json(plans, data, Path(tmp) / "a.json")
            export_text(plans, Path(tmp) / "a.txt")
            self.assertEqual(n, sum(p.student_count for p in plans))
            payload = json.loads((Path(tmp) / "a.json").read_text())
            self.assertEqual(len(payload["sessions"]), 6)
            self.assertIn("rooms", payload["sessions"][0])
            self.assertTrue((Path(tmp) / "a.txt").read_text().startswith("="))


if __name__ == "__main__":
    unittest.main()
