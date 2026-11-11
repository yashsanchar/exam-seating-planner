"""Feasibility checks: "is this even possible?" before we search.

DAA ideas used here
-------------------
* Horizontal rule: in a run of L consecutive usable seats in a row, one course
  can take at most ceil(L / 2) of them (every other seat).
* Four-way rule: the seat grid is a BIPARTITE graph (colour a seat by
  (row XOR col) & 1; neighbours always have different colours).
  Largest set of seats with no two adjacent (maximum independent set)
  = V - (maximum matching)            -- Konig's theorem.
  We find the matching with Kuhn's augmenting-path algorithm, O(V * E).
* A course with more students than that limit can never be seated, so we
  report it immediately instead of letting a search run forever.
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Sequence, Tuple, TYPE_CHECKING

from .errors import InfeasibleArrangementError, InsufficientCapacityError
from .models import Position, Room

if TYPE_CHECKING:  # pragma: no cover
    from .rules import AdjacencyRule

sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))


def parity(r: int, c: int) -> int:
    """Checkerboard colour of a seat: one XOR gate on the low bits (Computer Architecture link)."""
    return (r ^ c) & 1


def horizontal_capacity(room: Room) -> int:
    """Max seats ONE course can take when only left/right neighbours matter."""
    total = 0
    for r in range(room.rows):
        run = 0
        for c in range(room.cols):
            if room.is_usable(r, c):
                run += 1
            else:
                total += (run + 1) // 2
                run = 0
        total += (run + 1) // 2
    return total


def max_matching(room: Room, neighbors: Callable[[int, int, int, int], List[Position]]) -> int:
    """Kuhn's algorithm on the seat graph (left side = parity 0, right side = parity 1)."""
    left = [p for p in room.usable_positions() if parity(*p) == 0]
    match_right: Dict[Position, Position] = {}

    def usable_neighbors(p: Position) -> List[Position]:
        return [q for q in neighbors(p[0], p[1], room.rows, room.cols) if room.is_usable(*q)]

    def try_augment(u: Position, seen: set) -> bool:
        for v in usable_neighbors(u):
            if v in seen:
                continue
            seen.add(v)
            if v not in match_right or try_augment(match_right[v], seen):
                match_right[v] = u
                return True
        return False

    return sum(1 for u in left if try_augment(u, set()))


def bipartite_capacity(room: Room, neighbors: Callable[[int, int, int, int], List[Position]]) -> int:
    """Max seats ONE course can take = usable seats - maximum matching (Konig)."""
    return room.capacity - max_matching(room, neighbors)


def check_room_feasible(
    room: Room, course_counts: Dict[str, int], rule: "AdjacencyRule"
) -> None:
    """Raise if this room can never hold these students under the rule."""
    total = sum(course_counts.values())
    if total > room.capacity:
        raise InsufficientCapacityError(
            f"Room {room.room_id}: {total} students but only {room.capacity} usable seats"
        )
    limit = rule.independent_capacity(room)
    for code, n in sorted(course_counts.items()):
        if n > limit:
            raise InfeasibleArrangementError(
                f"Room {room.room_id}: paper {code} has {n} students but at most {limit} "
                f"of them can sit in this room without being next to each other"
            )
