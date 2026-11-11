"""Seating strategies: how a single room gets filled.

OOP : Strategy pattern. Every strategy has the same solve() method, so the
      planner can swap them at runtime.
DAA : * GreedyStrategy       - max-heap, O(N log K), fast but can dead-end.
      * BacktrackingStrategy - complete search with pruning, exponential worst case.
      * HybridStrategy       - greedy first, backtracking only if greedy fails.

All strategies may leave a seat EMPTY when the room has spare seats
(example: 5 seats, courses A,A,A,B -> A B A _ A is the only valid answer).
Students of one course are handed out in roll-number order.
"""

from __future__ import annotations

import heapq
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Sequence, Tuple

from .errors import InfeasibleArrangementError, InsufficientCapacityError
from .models import Position, Room, Student, natural_key
from .rules import AdjacencyRule


@dataclass
class SolveResult:
    placement: Dict[Position, Student]
    strategy: str
    nodes: int = 0  # search steps (seats examined / recursive calls) - used in benchmarks


def _group_by_course(students: Sequence[Student]) -> Dict[str, Deque[Student]]:
    groups: Dict[str, List[Student]] = {}
    for s in students:
        groups.setdefault(s.course, []).append(s)
    return {
        code: deque(sorted(members, key=lambda s: natural_key(s.roll_no)))
        for code, members in groups.items()
    }


class SeatingStrategy(ABC):
    name = "strategy"

    @abstractmethod
    def solve(self, room: Room, students: Sequence[Student], rule: AdjacencyRule) -> SolveResult:
        """Return a placement or raise InfeasibleArrangementError."""

    @staticmethod
    def check_capacity(room: Room, students: Sequence[Student]) -> None:
        if len(students) > room.capacity:
            raise InsufficientCapacityError(
                f"Room {room.room_id}: {len(students)} students but only {room.capacity} usable seats"
            )

    def fill(self, room: Room, result: SolveResult) -> None:
        """Write a placement into the room."""
        room.clear()
        for (r, c), student in result.placement.items():
            room.place(r, c, student)


# --------------------------------------------------------------------------
class GreedyStrategy(SeatingStrategy):
    """Visit seats in row-major order; always take the course with the MOST
    students left that does not clash with the already-seated neighbours."""

    name = "greedy"

    def solve(self, room, students, rule) -> SolveResult:
        self.check_capacity(room, students)
        order = room.usable_positions()
        queues = _group_by_course(students)
        remaining_total = len(students)
        slack = len(order) - remaining_total  # seats we are allowed to leave empty

        heap: List[Tuple[int, str]] = [(-len(q), code) for code, q in queues.items()]
        heapq.heapify(heap)
        course_at: Dict[Position, str] = {}
        placement: Dict[Position, Student] = {}
        nodes = 0

        for pos in order:
            if remaining_total == 0:
                break
            nodes += 1
            forbidden = {course_at[p] for p in rule.earlier_neighbors(*pos) if p in course_at}
            skipped: List[Tuple[int, str]] = []
            chosen = None
            while heap:
                item = heapq.heappop(heap)
                if item[1] in forbidden:
                    skipped.append(item)
                else:
                    chosen = item
                    break
            for item in skipped:
                heapq.heappush(heap, item)

            if chosen is None:
                if slack > 0:  # leave this seat empty
                    slack -= 1
                    continue
                raise InfeasibleArrangementError(
                    f"Greedy got stuck at row {pos[0] + 1}, seat {pos[1] + 1} in room {room.room_id}"
                )

            neg_count, code = chosen
            placement[pos] = queues[code].popleft()
            course_at[pos] = code
            remaining_total -= 1
            if neg_count + 1 < 0:
                heapq.heappush(heap, (neg_count + 1, code))

        if remaining_total:
            raise InfeasibleArrangementError(
                f"Greedy ran out of seats in room {room.room_id} with {remaining_total} students left"
            )
        return SolveResult(placement, self.name, nodes)


# --------------------------------------------------------------------------
def suffix_run_bound(order: Sequence[Position]) -> List[int]:
    """bound[i] = most seats ONE course could still take among order[i:], looking only at
    left/right runs (a relaxation, so it is valid for every rule). Used for pruning."""
    n = len(order)
    f = [0] * (n + 1)
    run = [0] * (n + 1)
    for i in range(n - 1, -1, -1):
        r, c = order[i]
        if i + 1 < n and order[i + 1] == (r, c + 1):
            length = run[i + 1] + 1
            base = f[i + 1] - (run[i + 1] + 1) // 2
        else:
            length = 1
            base = f[i + 1]
        run[i] = length
        f[i] = base + (length + 1) // 2
    return f


class _SearchLimit(Exception):
    pass


class BacktrackingStrategy(SeatingStrategy):
    """Seat-by-seat depth-first search. Tries the biggest course first, undoes a choice when
    it leads nowhere. Pruned with two cheap bounds (see _search)."""

    name = "backtracking"

    def __init__(self, node_limit: int = 200_000) -> None:
        self.node_limit = node_limit

    def solve(self, room, students, rule) -> SolveResult:
        self.check_capacity(room, students)
        order = room.usable_positions()
        queues = _group_by_course(students)
        counts = {code: len(q) for code, q in queues.items()}
        bound = suffix_run_bound(order)
        n = len(order)
        course_at: Dict[Position, str] = {}
        state = {"remaining": len(students), "nodes": 0}

        def search(i: int) -> bool:
            state["nodes"] += 1
            if state["nodes"] > self.node_limit:
                raise _SearchLimit()
            if state["remaining"] == 0:
                return True
            if i == n:
                return False
            # Prune 1: not enough seats left for the students left.
            if state["remaining"] > n - i:
                return False
            # Prune 2: the biggest remaining course cannot fit in the seats that are left.
            if max(counts.values()) > bound[i]:
                return False

            pos = order[i]
            forbidden = {course_at[p] for p in rule.earlier_neighbors(*pos) if p in course_at}
            options = sorted(
                (code for code, k in counts.items() if k > 0 and code not in forbidden),
                key=lambda code: (-counts[code], code),
            )
            for code in options:
                counts[code] -= 1
                state["remaining"] -= 1
                course_at[pos] = code
                if search(i + 1):
                    return True
                del course_at[pos]
                counts[code] += 1
                state["remaining"] += 1
            # Last option: leave this seat empty (only if a spare seat exists).
            if n - i - 1 >= state["remaining"]:
                return search(i + 1)
            return False

        try:
            found = search(0)
        except _SearchLimit:
            raise InfeasibleArrangementError(
                f"Room {room.room_id}: search stopped after {self.node_limit} steps without an answer"
            )
        if not found:
            raise InfeasibleArrangementError(
                f"Room {room.room_id}: no arrangement exists that keeps same-course students apart"
            )

        placement: Dict[Position, Student] = {}
        for pos in order:
            if pos in course_at:
                placement[pos] = queues[course_at[pos]].popleft()
        return SolveResult(placement, self.name, state["nodes"])


# --------------------------------------------------------------------------
class HybridStrategy(SeatingStrategy):
    """Greedy first (fast). If greedy dead-ends, fall back to backtracking (complete)."""

    name = "hybrid"

    def __init__(self, node_limit: int = 200_000) -> None:
        self._greedy = GreedyStrategy()
        self._backtracking = BacktrackingStrategy(node_limit)

    def solve(self, room, students, rule) -> SolveResult:
        try:
            return self._greedy.solve(room, students, rule)
        except InfeasibleArrangementError:
            result = self._backtracking.solve(room, students, rule)
            result.strategy = "backtracking (greedy failed)"
            return result


_STRATEGIES = {"greedy": GreedyStrategy, "backtracking": BacktrackingStrategy, "hybrid": HybridStrategy}


def get_strategy(name: str) -> SeatingStrategy:
    key = name.strip().lower()
    if key not in _STRATEGIES:
        raise ValueError(f"Unknown strategy '{name}'. Choose from: {', '.join(_STRATEGIES)}")
    return _STRATEGIES[key]()


def strategy_names() -> List[str]:
    return list(_STRATEGIES)
