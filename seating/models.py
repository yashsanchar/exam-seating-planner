"""Domain classes: Student, ExamSession, Seat, Room and the plan/result holders.

Coordinates are 0-based inside the code (row 0, col 0 is the front-left seat).
CSV files and printed output use 1-based numbers because that is how people
count benches and rows in a real classroom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from .errors import DataFormatError

Position = Tuple[int, int]


def natural_key(text: str) -> List[Any]:
    """Sort key so that 'CS2' < 'CS10' (digits compared as numbers)."""
    return [int(p) if p.isdigit() else p.lower() for p in re.split(r"(\d+)", text)]


@dataclass(frozen=True)
class Student:
    """One student sitting ONE exam paper (course)."""

    roll_no: str
    name: str
    course: str


@dataclass(frozen=True)
class ExamSession:
    """All papers written together at one date + time slot."""

    date: str
    slot: str
    courses: Tuple[str, ...]

    @property
    def key(self) -> str:
        return f"{self.date} | {self.slot}"


class Seat:
    """A single seat in a room. Uses __slots__ to stay small in memory."""

    __slots__ = ("row", "col", "blocked", "student")

    def __init__(self, row: int, col: int, blocked: bool = False) -> None:
        self.row = row
        self.col = col
        self.blocked = blocked
        self.student: Optional[Student] = None

    @property
    def is_free(self) -> bool:
        return not self.blocked and self.student is None

    @property
    def course(self) -> Optional[str]:
        return self.student.course if self.student else None


class Room:
    """A rectangular grid of seats. Some seats may be blocked (not usable).

    Seats are stored in ONE flat list in row-major order, so seat (r, c) lives
    at index r * cols + c. (Computer Architecture: contiguous memory layout.)
    """

    def __init__(
        self,
        room_id: str,
        rows: int,
        cols: int,
        blocked: Iterable[Position] = (),
        name: str = "",
        available: bool = True,
        provisional: bool = False,
        note: str = "",
    ) -> None:
        if rows < 1 or cols < 1:
            raise DataFormatError(f"Room {room_id}: rows and cols must be at least 1")
        self.room_id = room_id
        self.name = name or room_id
        self.rows = rows
        self.cols = cols
        self.available = available
        self.provisional = provisional      # layout is a guess, not yet checked against the real room
        self.note = note
        self.blocked: Set[Position] = set(blocked)
        for (r, c) in self.blocked:
            if not (0 <= r < rows and 0 <= c < cols):
                raise DataFormatError(
                    f"Room {room_id}: blocked seat (row {r + 1}, col {c + 1}) is outside the {rows}x{cols} grid"
                )
        self._seats: List[Seat] = [
            Seat(r, c, (r, c) in self.blocked) for r in range(rows) for c in range(cols)
        ]

    # ---- access -------------------------------------------------------
    def in_bounds(self, r: int, c: int) -> bool:
        return 0 <= r < self.rows and 0 <= c < self.cols

    def seat(self, r: int, c: int) -> Seat:
        return self._seats[r * self.cols + c]

    def is_usable(self, r: int, c: int) -> bool:
        return self.in_bounds(r, c) and not self.seat(r, c).blocked

    def usable_positions(self) -> List[Position]:
        """Usable seats in row-major (front-left to back-right) order."""
        return [(s.row, s.col) for s in self._seats if not s.blocked]

    @property
    def capacity(self) -> int:
        return self.rows * self.cols - len(self.blocked)

    # ---- changing state -----------------------------------------------
    def place(self, r: int, c: int, student: Student) -> None:
        if not self.in_bounds(r, c):
            raise ValueError(f"Seat ({r}, {c}) is outside room {self.room_id}")
        seat = self.seat(r, c)
        if seat.blocked:
            raise ValueError(f"Seat ({r + 1}, {c + 1}) in {self.room_id} is blocked")
        if seat.student is not None:
            raise ValueError(f"Seat ({r + 1}, {c + 1}) in {self.room_id} is already taken")
        seat.student = student

    def clear(self) -> None:
        for s in self._seats:
            s.student = None

    def clone_empty(self) -> "Room":
        """A fresh copy with the same layout and no students (rooms are reused per session)."""
        return Room(self.room_id, self.rows, self.cols, self.blocked, self.name, self.available,
                    self.provisional, self.note)

    # ---- reading state ------------------------------------------------
    def students(self) -> List[Student]:
        return [s.student for s in self._seats if s.student is not None]

    @property
    def occupied(self) -> int:
        return sum(1 for s in self._seats if s.student is not None)

    def course_grid(self) -> List[List[Optional[str]]]:
        """2D list of course codes. None = empty usable seat, '#' = blocked seat."""
        grid: List[List[Optional[str]]] = []
        for r in range(self.rows):
            row: List[Optional[str]] = []
            for c in range(self.cols):
                seat = self.seat(r, c)
                row.append("#" if seat.blocked else seat.course)
            grid.append(row)
        return grid

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"Room({self.room_id!r}, {self.rows}x{self.cols}, capacity={self.capacity})"


@dataclass
class RoomPlan:
    """A room filled for one session, plus how it was solved."""

    room: Room
    strategy: str
    nodes: int = 0


@dataclass
class SessionPlan:
    """Seating result for one exam session (date + slot)."""

    session: ExamSession
    room_plans: List[RoomPlan] = field(default_factory=list)
    student_count: int = 0
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-friendly form (the API layer will return exactly this)."""
        rooms = []
        for rp in self.room_plans:
            seats = []
            for r in range(rp.room.rows):
                for c in range(rp.room.cols):
                    seat = rp.room.seat(r, c)
                    if seat.blocked:
                        seats.append({"row": r + 1, "col": c + 1, "blocked": True})
                    elif seat.student:
                        st = seat.student
                        seats.append(
                            {
                                "row": r + 1,
                                "col": c + 1,
                                "blocked": False,
                                "roll_no": st.roll_no,
                                "name": st.name,
                                "course": st.course,
                            }
                        )
                    else:
                        seats.append({"row": r + 1, "col": c + 1, "blocked": False, "empty": True})
            rooms.append(
                {
                    "room_id": rp.room.room_id,
                    "name": rp.room.name,
                    "rows": rp.room.rows,
                    "cols": rp.room.cols,
                    "provisional": rp.room.provisional,
                    "strategy": rp.strategy,
                    "search_nodes": rp.nodes,
                    "students": rp.room.occupied,
                    "seats": seats,
                }
            )
        return {
            "date": self.session.date,
            "slot": self.session.slot,
            "courses": list(self.session.courses),
            "ok": self.ok,
            "error": self.error,
            "warnings": self.warnings,
            "student_count": self.student_count,
            "rooms": rooms,
        }


@dataclass
class ExamData:
    """Everything loaded from the user's files."""

    students: List[Student]
    rooms: List[Room]
    sessions: List[ExamSession]
    course_names: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
