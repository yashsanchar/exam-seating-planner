"""Exam seating arrangement backend (Python standard library only)."""

from .cohorts import expand_cohorts, papers_of_group, timetable_groups
from .compare import compare_strategies, export_comparison_csv
from .errors import (DataFormatError, InfeasibleArrangementError, InsufficientCapacityError,
                     SeatingError)
from .io_csv import (build_sessions, combine, export_csv, export_json, export_text, load_all, load_rooms,
                     load_schedule, load_schedule_rows, load_students)
from .models import ExamData, ExamSession, Room, RoomPlan, Seat, SessionPlan, Student
from .planner import ExamPlanner
from .presets import (default_rooms, default_timetable, room_to_spec, rooms_from_specs, rows_from_sessions,
                      timetable_rows_clean)
from .rules import AdjacencyRule, FourWayRule, HorizontalRule, get_rule, rule_names
from .strategies import (BacktrackingStrategy, GreedyStrategy, HybridStrategy, SeatingStrategy,
                         get_strategy, strategy_names)
from .verify import find_conflicts

__all__ = [
    "expand_cohorts", "papers_of_group", "timetable_groups",
    "AdjacencyRule", "BacktrackingStrategy", "build_sessions", "combine", "default_rooms", "default_timetable",
    "load_schedule_rows", "room_to_spec", "rooms_from_specs", "rows_from_sessions", "timetable_rows_clean", "compare_strategies", "export_comparison_csv", "DataFormatError", "ExamData", "ExamPlanner",
    "ExamSession", "FourWayRule", "GreedyStrategy", "HorizontalRule", "HybridStrategy",
    "InfeasibleArrangementError", "InsufficientCapacityError", "Room", "RoomPlan", "Seat",
    "SeatingError", "SeatingStrategy", "SessionPlan", "Student", "export_csv", "export_json",
    "export_text", "find_conflicts", "get_rule", "get_strategy", "load_all", "load_rooms",
    "load_schedule", "load_students", "rule_names", "strategy_names",
]
