"""Computer Architecture: conflict checking with bit-vectors.

For every course we keep one integer per row. Bit c of that integer is 1 when
a student of the course sits in column c.

    two students of the same course side by side in a row   <=>   mask & (mask << 1) != 0
    two students of the same course front/back              <=>   row_mask[r] & row_mask[r+1] != 0

One AND plus one shift checks an entire row at once, instead of looping over seats.
"""

from __future__ import annotations

from typing import Dict, List

from .models import Room
from .rules import AdjacencyRule


def popcount(x: int) -> int:
    """Number of 1 bits (works on every Python version)."""
    return bin(x).count("1")


def course_row_masks(room: Room) -> Dict[str, List[int]]:
    """course code -> list with one bitmask per row."""
    masks: Dict[str, List[int]] = {}
    for r in range(room.rows):
        for c in range(room.cols):
            course = room.seat(r, c).course
            if course is not None:
                masks.setdefault(course, [0] * room.rows)[r] |= 1 << c
    return masks


def horizontal_conflicts_bitmask(room: Room) -> int:
    total = 0
    for rows in course_row_masks(room).values():
        for mask in rows:
            total += popcount(mask & (mask << 1))
    return total


def vertical_conflicts_bitmask(room: Room) -> int:
    total = 0
    for rows in course_row_masks(room).values():
        for r in range(len(rows) - 1):
            total += popcount(rows[r] & rows[r + 1])
    return total


def conflicts_from_masks(masks: Dict[str, List[int]], rule: AdjacencyRule) -> int:
    """The check itself: only AND, shift and popcount on ready-made masks."""
    total = 0
    for rows in masks.values():
        for mask in rows:
            total += popcount(mask & (mask << 1))
        if rule.name == "fourway":
            for r in range(len(rows) - 1):
                total += popcount(rows[r] & rows[r + 1])
    return total


def conflicts_bitmask(room: Room, rule: AdjacencyRule) -> int:
    """Build the masks, then count touching same-course pairs with bit operations."""
    return conflicts_from_masks(course_row_masks(room), rule)


def conflicts_loop(room: Room, rule: AdjacencyRule) -> int:
    """Same answer with plain nested loops (the slow baseline used in benchmarks)."""
    total = 0
    for r in range(room.rows):
        for c in range(room.cols):
            a = room.seat(r, c).course
            if a is None:
                continue
            if c + 1 < room.cols and room.seat(r, c + 1).course == a:
                total += 1
            if rule.name == "fourway" and r + 1 < room.rows and room.seat(r + 1, c).course == a:
                total += 1
    return total
