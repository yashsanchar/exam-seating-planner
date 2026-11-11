"""Splits one session's students across rooms.

DAA: a greedy "balanced fill". Rooms are picked largest-first until they can hold
everybody; then each student goes to the room with the most free space left (as a
fraction of its size) that still has room for another student of that course.
Cost: O(N * R) for N students and R rooms.
"""

from __future__ import annotations

from typing import Dict, List, Sequence

from .errors import InsufficientCapacityError
from .models import Room, Student, natural_key
from .rules import AdjacencyRule


def select_rooms(
    rooms: Sequence[Room],
    course_counts: Dict[str, int],
    rule: AdjacencyRule,
    extra: int = 0,
) -> List[Room]:
    """Smallest set of rooms (largest first) that can hold everyone, plus `extra` more rooms.

    Needs BOTH: enough total seats, and for every course enough 'non-touching' seats."""
    usable = sorted(
        (r for r in rooms if r.available and r.capacity > 0),
        key=lambda r: (-r.capacity, natural_key(r.room_id)),
    )
    total = sum(course_counts.values())
    limits = {r.room_id: rule.independent_capacity(r) for r in usable}

    chosen: List[Room] = []
    seats = 0
    course_room = {code: 0 for code in course_counts}
    for room in usable:
        done = seats >= total and all(course_room[c] >= n for c, n in course_counts.items())
        if done:
            break
        chosen.append(room)
        seats += room.capacity
        for code in course_room:
            course_room[code] += limits[room.room_id]
    else:
        done = seats >= total and all(course_room[c] >= n for c, n in course_counts.items())
        if not done:
            raise InsufficientCapacityError(
                f"Not enough room: {total} students, but the available rooms give {seats} usable seats "
                f"and room for at most {min(course_room.values()) if course_room else 0} "
                f"students of the biggest paper who can sit apart"
            )

    # Extra rooms (used by the planner when the tightest fit could not be solved).
    for room in usable:
        if extra <= 0:
            break
        if room not in chosen:
            chosen.append(room)
            extra -= 1
    return chosen


def distribute(
    students: Sequence[Student], rooms: Sequence[Room], rule: AdjacencyRule
) -> Dict[str, List[Student]]:
    """Assign every student to a room. Big courses are placed first and spread out."""
    by_course: Dict[str, List[Student]] = {}
    for s in students:
        by_course.setdefault(s.course, []).append(s)

    limit = {r.room_id: rule.independent_capacity(r) for r in rooms}
    free = {r.room_id: r.capacity for r in rooms}
    used: Dict[str, Dict[str, int]] = {r.room_id: {} for r in rooms}
    result: Dict[str, List[Student]] = {r.room_id: [] for r in rooms}

    for code in sorted(by_course, key=lambda c: (-len(by_course[c]), c)):
        for student in sorted(by_course[code], key=lambda s: natural_key(s.roll_no)):
            best = None
            best_score = -1.0
            for room in rooms:
                rid = room.room_id
                if free[rid] <= 0 or used[rid].get(code, 0) >= limit[rid]:
                    continue
                score = free[rid] / room.capacity
                if score > best_score:
                    best, best_score = room, score
            if best is None:
                raise InsufficientCapacityError(
                    f"Could not find a room for roll {student.roll_no} (paper {code}) "
                    f"without sitting next to a student of the same paper"
                )
            rid = best.room_id
            result[rid].append(student)
            free[rid] -= 1
            used[rid][code] = used[rid].get(code, 0) + 1
    return result
