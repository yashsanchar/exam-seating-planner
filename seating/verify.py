"""Independent checker: re-reads a filled room and lists every rule violation."""

from __future__ import annotations

from typing import List, Tuple

from .models import Room
from .rules import AdjacencyRule


def find_conflicts(room: Room, rule: AdjacencyRule) -> List[Tuple[str, str, str]]:
    """Return (roll_a, roll_b, course) for every pair of touching same-course students."""
    found = []
    for r in range(room.rows):
        for c in range(room.cols):
            a = room.seat(r, c).student
            if a is None:
                continue
            for (rr, cc) in rule.neighbors(r, c, room.rows, room.cols):
                if (rr, cc) <= (r, c):  # look at each pair once
                    continue
                b = room.seat(rr, cc).student
                if b is not None and b.course == a.course:
                    found.append((a.roll_no, b.roll_no, a.course))
    return found
