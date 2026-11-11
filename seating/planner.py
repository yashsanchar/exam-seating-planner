"""ExamPlanner: turns loaded data into a seating plan for every exam session."""

from __future__ import annotations

from typing import Dict, List, Optional

from .allocator import distribute, select_rooms
from .errors import InfeasibleArrangementError, InsufficientCapacityError, SeatingError
from .feasibility import check_room_feasible
from .models import ExamData, ExamSession, RoomPlan, SessionPlan, Student, natural_key
from .rules import AdjacencyRule
from .strategies import SeatingStrategy


class ExamPlanner:
    def __init__(self, data: ExamData, rule: AdjacencyRule, strategy: SeatingStrategy) -> None:
        self.data = data
        self.rule = rule
        self.strategy = strategy
        self._by_course: Dict[str, List[Student]] = {}
        for s in data.students:
            self._by_course.setdefault(s.course, []).append(s)

    # ------------------------------------------------------------------
    def students_for(self, session: ExamSession) -> tuple:
        """Students writing in this session (one seat each) and a list of warnings."""
        seen: Dict[str, Student] = {}
        warnings: List[str] = []
        for code in session.courses:
            members = self._by_course.get(code, [])
            if not members:
                warnings.append(f"No students found for paper {code}")
            for s in members:
                if s.roll_no in seen:
                    warnings.append(
                        f"Clash: roll {s.roll_no} ({s.name}) has both {seen[s.roll_no].course} and "
                        f"{s.course} in this slot - seated for {seen[s.roll_no].course} only"
                    )
                else:
                    seen[s.roll_no] = s
        ordered = sorted(seen.values(), key=lambda s: natural_key(s.roll_no))
        return ordered, warnings

    # ------------------------------------------------------------------
    def plan_session(self, session: ExamSession) -> SessionPlan:
        students, warnings = self.students_for(session)
        plan = SessionPlan(session=session, student_count=len(students), warnings=warnings)
        if not students:
            return plan

        counts: Dict[str, int] = {}
        for s in students:
            counts[s.course] = counts.get(s.course, 0) + 1

        last_error: Optional[SeatingError] = None
        previous_count = -1
        # Try the tightest set of rooms first; if that cannot be solved, add one more room and retry.
        for extra in range(len(self.data.rooms) + 1):
            try:
                rooms = select_rooms(self.data.rooms, counts, self.rule, extra)
            except InsufficientCapacityError as exc:
                last_error = last_error or exc
                break
            if len(rooms) == previous_count:
                break  # no more rooms left to add
            previous_count = len(rooms)
            try:
                room_plans = self._solve_rooms(rooms, students)
            except (InfeasibleArrangementError, InsufficientCapacityError) as exc:
                last_error = exc
                continue
            plan.room_plans = room_plans
            return plan

        plan.error = str(last_error) if last_error else "Could not build an arrangement"
        return plan

    def _solve_rooms(self, rooms, students) -> List[RoomPlan]:
        assignment = distribute(students, rooms, self.rule)
        plans: List[RoomPlan] = []
        for room in rooms:
            members = assignment[room.room_id]
            if not members:
                continue
            counts: Dict[str, int] = {}
            for s in members:
                counts[s.course] = counts.get(s.course, 0) + 1
            check_room_feasible(room, counts, self.rule)
            fresh = room.clone_empty()
            result = self.strategy.solve(fresh, members, self.rule)
            self.strategy.fill(fresh, result)
            plans.append(RoomPlan(fresh, result.strategy, result.nodes))
        return plans

    # ------------------------------------------------------------------
    def plan_all(self) -> List[SessionPlan]:
        return [self.plan_session(s) for s in self.data.sessions]
