import itertools
import random
import unittest

from seating import (BacktrackingStrategy, FourWayRule, GreedyStrategy, HorizontalRule, HybridStrategy,
                     InfeasibleArrangementError, InsufficientCapacityError, Room, Student, find_conflicts,
                     get_rule)
from seating import bitops, seat_encoding
from seating.errors import DataFormatError
from seating.feasibility import check_room_feasible, horizontal_capacity, parity
from seating.strategies import suffix_run_bound


def students(courses):
    return [Student(f"{i:03d}", f"S{i}", c) for i, c in enumerate(courses)]


def brute_force_capacity(room, rule):
    """Largest set of usable seats with no two touching (tries every subset)."""
    seats = room.usable_positions()
    best = 0
    for mask in range(1 << len(seats)):
        chosen = {seats[i] for i in range(len(seats)) if mask >> i & 1}
        if len(chosen) <= best:
            continue
        if all(q not in chosen for p in chosen for q in rule.neighbors(p[0], p[1], room.rows, room.cols)):
            best = len(chosen)
    return best


class RoomTests(unittest.TestCase):
    def test_capacity_and_blocked(self):
        room = Room("A", 3, 4, blocked=[(0, 0), (2, 3)])
        self.assertEqual(room.capacity, 10)
        self.assertEqual(len(room.usable_positions()), 10)
        with self.assertRaises(ValueError):
            room.place(0, 0, Student("1", "x", "C"))

    def test_blocked_outside_grid(self):
        with self.assertRaises(DataFormatError):
            Room("A", 2, 2, blocked=[(5, 5)])

    def test_double_place_and_clone(self):
        room = Room("A", 2, 2)
        room.place(0, 0, Student("1", "x", "C"))
        with self.assertRaises(ValueError):
            room.place(0, 0, Student("2", "y", "C"))
        self.assertEqual(room.clone_empty().occupied, 0)


class FeasibilityTests(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(FourWayRule().independent_capacity(Room("A", 3, 3)), 5)
        self.assertEqual(FourWayRule().independent_capacity(Room("A", 2, 2)), 2)
        self.assertEqual(HorizontalRule().independent_capacity(Room("A", 2, 5)), 6)
        self.assertEqual(horizontal_capacity(Room("A", 1, 5, blocked=[(0, 2)])), 2)

    def test_matches_brute_force(self):
        rng = random.Random(1)
        for _ in range(60):
            rows, cols = rng.randint(1, 3), rng.randint(1, 4)
            blocked = [(r, c) for r in range(rows) for c in range(cols) if rng.random() < 0.2]
            room = Room("T", rows, cols, blocked)
            for rule in (HorizontalRule(), FourWayRule()):
                self.assertEqual(rule.independent_capacity(room), brute_force_capacity(room, rule),
                                 (rows, cols, blocked, rule.name))

    def test_too_many_of_one_course(self):
        room = Room("A", 2, 3)  # 6 seats, 3 can be non-touching under fourway
        with self.assertRaises(InfeasibleArrangementError):
            check_room_feasible(room, {"C1": 4}, FourWayRule())
        with self.assertRaises(InsufficientCapacityError):
            check_room_feasible(room, {"C1": 3, "C2": 4}, FourWayRule())

    def test_parity_is_checkerboard(self):
        self.assertEqual([parity(0, c) for c in range(4)], [0, 1, 0, 1])
        self.assertEqual([parity(1, c) for c in range(4)], [1, 0, 1, 0])

    def test_suffix_bound(self):
        order = [(0, 0), (0, 1), (0, 2), (1, 0)]
        self.assertEqual(suffix_run_bound(order), [3, 2, 2, 1, 0])


class StrategyTests(unittest.TestCase):
    def check_valid(self, room, studs, result, rule):
        room.clear()
        for (r, c), s in result.placement.items():
            room.place(r, c, s)
        self.assertEqual(room.occupied, len(studs))
        self.assertEqual(find_conflicts(room, rule), [])

    def test_all_strategies_alternate(self):
        for strat in (GreedyStrategy(), BacktrackingStrategy(), HybridStrategy()):
            room = Room("A", 4, 6)
            studs = students(["A", "B"] * 10)
            for rule in (HorizontalRule(), FourWayRule()):
                self.check_valid(room, studs, strat.solve(room, studs, rule), rule)

    def test_needs_an_empty_seat(self):
        room = Room("A", 1, 5)
        studs = students(["A", "A", "A", "B"])
        for strat in (GreedyStrategy(), BacktrackingStrategy()):
            self.check_valid(room, studs, strat.solve(room, studs, HorizontalRule()), HorizontalRule())

    def test_greedy_fails_backtracking_recovers(self):
        room = Room("A", 3, 3, blocked=[(0, 0), (1, 0)])
        studs = students(["C1", "C1", "C1", "C1", "C2", "C2"])
        rule = FourWayRule()
        with self.assertRaises(InfeasibleArrangementError):
            GreedyStrategy().solve(room, studs, rule)
        self.check_valid(room, studs, BacktrackingStrategy().solve(room, studs, rule), rule)
        result = HybridStrategy().solve(room, studs, rule)
        self.assertIn("backtracking", result.strategy)
        self.check_valid(room, studs, result, rule)

    def test_impossible_is_reported(self):
        room = Room("A", 1, 3)
        studs = students(["A", "A", "A"])
        with self.assertRaises(InfeasibleArrangementError):
            BacktrackingStrategy().solve(room, studs, HorizontalRule())

    def test_too_many_students(self):
        with self.assertRaises(InsufficientCapacityError):
            GreedyStrategy().solve(Room("A", 1, 2), students(["A", "B", "C"]), HorizontalRule())

    def test_backtracking_agrees_with_brute_force(self):
        rng = random.Random(5)
        for _ in range(80):
            rows, cols = rng.randint(1, 3), rng.randint(2, 3)
            room = Room("T", rows, cols)
            n = rng.randint(1, room.capacity)
            studs = students([f"C{rng.randint(1, 3)}" for _ in range(n)])
            rule = rng.choice([HorizontalRule(), FourWayRule()])
            exists = self.brute_exists(room, studs, rule)
            try:
                BacktrackingStrategy().solve(room, studs, rule)
                found = True
            except InfeasibleArrangementError:
                found = False
            self.assertEqual(found, exists)

    @staticmethod
    def brute_exists(room, studs, rule):
        seats = room.usable_positions()
        courses = [s.course for s in studs]
        for chosen in itertools.permutations(range(len(seats)), len(courses)):
            at = {seats[i]: courses[k] for k, i in enumerate(chosen)}
            if all(at.get(q) != at[p] for p in at for q in rule.neighbors(p[0], p[1], room.rows, room.cols)):
                return True
        return False


class LowLevelTests(unittest.TestCase):
    def test_bitmask_equals_loop_equals_verifier(self):
        rng = random.Random(9)
        for _ in range(40):
            room = Room("T", rng.randint(2, 6), rng.randint(2, 8))
            for r in range(room.rows):
                for c in range(room.cols):
                    if rng.random() < 0.7:
                        room.place(r, c, Student(f"{r}{c}", "n", rng.choice("ABC")))
            for rule in (HorizontalRule(), FourWayRule()):
                a = bitops.conflicts_bitmask(room, rule)
                b = bitops.conflicts_loop(room, rule)
                c = len(find_conflicts(room, rule))
                self.assertEqual((a, b), (b, c))

    def test_seat_word_round_trip(self):
        word = seat_encoding.pack(3, 17, 42, seat_encoding.FLAG_OCCUPIED)
        self.assertEqual(word, 0x03112A02)
        self.assertEqual(tuple(seat_encoding.unpack(word)), (3, 17, 42, 2))
        self.assertTrue(seat_encoding.has_flag(word, seat_encoding.FLAG_OCCUPIED))
        self.assertFalse(seat_encoding.has_flag(seat_encoding.clear_flag(word, 2), 2))
        with self.assertRaises(ValueError):
            seat_encoding.pack(256, 0, 0)

    def test_popcount(self):
        self.assertEqual(bitops.popcount(0b101101), 4)


if __name__ == "__main__":
    unittest.main()
