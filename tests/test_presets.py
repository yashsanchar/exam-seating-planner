"""Built-in rooms, the printed timetable and the room/timetable editing helpers (no web server needed)."""

import unittest
from pathlib import Path

from seating import (DataFormatError, ExamPlanner, build_sessions, combine, default_rooms, default_timetable,
                     find_conflicts, get_rule, get_strategy, load_students, room_to_spec, rooms_from_specs,
                     timetable_rows_clean)
from seating.io_csv import norm_code

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "sample"


def spec(room_id="X1", layout=("111", "111"), **extra):
    return {"room_id": room_id, "name": room_id, "layout": list(layout), **extra}


class RoomTests(unittest.TestCase):
    def test_default_rooms(self):
        rooms = {r.room_id: r for r in default_rooms()}
        self.assertEqual(sorted(rooms), ["B-002", "B-003", "B-004", "B-005"])
        for rid in ("B-002", "B-003", "B-004"):
            r = rooms[rid]
            self.assertEqual((r.rows, r.cols, r.capacity), (6, 9, 39))
            self.assertTrue(r.provisional)
            self.assertTrue(r.note)
            # aisles (cols 3 and 7) and the back row of the middle block (cols 4-6) have no seat
            for row in range(6):
                self.assertFalse(r.is_usable(row, 2))
                self.assertFalse(r.is_usable(row, 6))
            self.assertTrue(all(not r.is_usable(5, c) for c in (3, 4, 5)))
            self.assertTrue(all(r.is_usable(4, c) for c in (3, 4, 5)))
        self.assertEqual(rooms["B-005"].capacity, 38)
        self.assertTrue(rooms["B-005"].provisional)

    def test_spec_round_trip(self):
        for room in default_rooms():
            again = rooms_from_specs([room_to_spec(room)])[0]
            self.assertEqual((again.rows, again.cols, again.blocked, again.provisional, again.note),
                             (room.rows, room.cols, room.blocked, room.provisional, room.note))

    def test_clone_keeps_provisional(self):
        room = default_rooms()[0]
        self.assertTrue(room.clone_empty().provisional)

    def test_editor_validation(self):
        bad = [
            ([], "at least one room"),
            ([spec(room_id="  ")], "Room ID"),
            ([spec(layout=())], "layout is empty"),
            ([spec(layout=("000", "000"))], "no seats"),
            ([spec(layout=("1q1", "111"))], "unknown layout character"),
            ([spec("A"), spec("a")], "used twice"),
            ([spec(layout=["1" * 41])], "at most"),
        ]
        for specs, text in bad:
            with self.assertRaises(DataFormatError, msg=text) as cm:
                rooms_from_specs(specs)
            self.assertIn(text.lower(), str(cm.exception).lower())

    def test_editor_pads_short_rows(self):
        room = rooms_from_specs([spec(layout=("111", "1"))])[0]
        self.assertEqual((room.rows, room.cols, room.capacity), (2, 3, 4))


class TimetableTests(unittest.TestCase):
    def test_default_timetable_groups_into_twelve_days(self):
        sessions, names, warnings = build_sessions(default_timetable(), "timetable row", 1)
        self.assertEqual(len(default_timetable()), 36)
        self.assertEqual(len(sessions), 12)
        self.assertEqual(warnings, [])
        self.assertEqual([s.date for s in sessions], sorted(s.date for s in sessions))   # in date order
        by_date = {s.date: s.courses for s in sessions}
        self.assertEqual(by_date["2026-11-30"], ("DS6A-603", "DS6A-204"))      # LLM is one shared paper
        sem3 = {"2026-11-23", "2026-11-25", "2026-11-27", "2026-11-30", "2026-12-01", "2026-12-03"}
        for date, courses in by_date.items():
            self.assertEqual(any(c.startswith(("DS5", "DS6A-2", "DS6A-6")) for c in courses), date in sem3, date)
        self.assertEqual(names["DS6A-203"], "Computer Architecture")

    def test_same_paper_same_group_twice_is_reported(self):
        rows = [{"date": "2026-11-23", "slot": "S", "course": "A1", "group": "G"}] * 2
        _, _, warnings = build_sessions(rows, "row", 1)
        self.assertEqual(len(warnings), 1)

    def test_clean_normalises_and_checks(self):
        rows = timetable_rows_clean([
            {"date": "2026-11-23", "slot": " 11:00  AM ", "course": "ds6a – 201", "course_name": "X", "group": ""},
            {"date": "", "slot": "", "course": "", "course_name": "", "group": ""},       # blank row is dropped
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["course"], "DS6A-201")
        self.assertEqual(rows[0]["slot"], "11:00 AM")
        with self.assertRaisesRegex(DataFormatError, "row 2: the paper code is missing"):
            timetable_rows_clean([{"date": "2026-11-23", "course": "A"}, {"date": "2026-11-24", "course": ""}])
        with self.assertRaisesRegex(DataFormatError, "row 1: the date is missing"):
            timetable_rows_clean([{"date": "", "course": "A"}])
        with self.assertRaises(DataFormatError):
            timetable_rows_clean([])

    def test_norm_code_dashes(self):
        for text in ("DS6A – 201", "ds6a-201", "DS6A—201", "DS6A - 201"):
            self.assertEqual(norm_code(text), "DS6A-201")


class RealSizedDataTests(unittest.TestCase):
    """Provisional rooms + printed timetable + placeholder students (231 across six groups)."""

    def test_every_day_fits_with_no_conflicts(self):
        students, names, warns = load_students(SAMPLE / "students_placeholder.csv")
        sessions, c_names, c_warns = build_sessions(default_timetable(), "timetable row", 1)
        data = combine(students, names, warns, default_rooms(), sessions, c_names, c_warns)
        self.assertEqual(data.warnings, [])
        self.assertEqual(len({s.roll_no for s in data.students}), 231)
        for rule_name in ("horizontal", "fourway"):
            rule = get_rule(rule_name)
            plans = ExamPlanner(data, rule, get_strategy("hybrid")).plan_all()
            for plan in plans:
                self.assertTrue(plan.ok, (rule_name, plan.session.date, plan.error))
                self.assertEqual(sum(len(find_conflicts(rp.room, rule)) for rp in plan.room_plans), 0)
                self.assertEqual(sum(rp.room.occupied for rp in plan.room_plans), plan.student_count)


if __name__ == "__main__":
    unittest.main()
