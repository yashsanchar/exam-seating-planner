"""Adjacency rules. Each rule decides which seats count as "beside" a seat.

OOP: an abstract base class with two concrete subclasses. The solvers only
talk to the AdjacencyRule interface, so a new rule (say, 8-way) can be added
without touching any solver code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, List

from .errors import DataFormatError
from .feasibility import bipartite_capacity, horizontal_capacity
from .models import Position, Room


class AdjacencyRule(ABC):
    name: str = "rule"

    @abstractmethod
    def neighbors(self, r: int, c: int, rows: int, cols: int) -> List[Position]:
        """Every in-grid seat that touches (r, c) under this rule."""

    @abstractmethod
    def earlier_neighbors(self, r: int, c: int) -> List[Position]:
        """Neighbours already filled when seats are visited in row-major order."""

    @abstractmethod
    def independent_capacity(self, room: Room) -> int:
        """Max seats one single course could occupy in this room under the rule."""


class HorizontalRule(AdjacencyRule):
    """Only the seats on the left and right count as 'beside'."""

    name = "horizontal"

    def neighbors(self, r: int, c: int, rows: int, cols: int) -> List[Position]:
        return [(r, cc) for cc in (c - 1, c + 1) if 0 <= cc < cols]

    def earlier_neighbors(self, r: int, c: int) -> List[Position]:
        return [(r, c - 1)] if c > 0 else []

    def independent_capacity(self, room: Room) -> int:
        return horizontal_capacity(room)


class FourWayRule(AdjacencyRule):
    """Left, right, front and back all count as 'beside' (strictest practical rule)."""

    name = "fourway"

    def neighbors(self, r: int, c: int, rows: int, cols: int) -> List[Position]:
        out = []
        for rr, cc in ((r, c - 1), (r, c + 1), (r - 1, c), (r + 1, c)):
            if 0 <= rr < rows and 0 <= cc < cols:
                out.append((rr, cc))
        return out

    def earlier_neighbors(self, r: int, c: int) -> List[Position]:
        out = []
        if c > 0:
            out.append((r, c - 1))
        if r > 0:
            out.append((r - 1, c))
        return out

    def independent_capacity(self, room: Room) -> int:
        return bipartite_capacity(room, self.neighbors)


_RULES: Dict[str, type] = {"horizontal": HorizontalRule, "fourway": FourWayRule}


def get_rule(name: str) -> AdjacencyRule:
    """Factory: build a rule from its name."""
    key = name.strip().lower().replace("-", "").replace("_", "")
    if key not in _RULES:
        raise DataFormatError(f"Unknown rule '{name}'. Choose from: {', '.join(_RULES)}")
    return _RULES[key]()


def rule_names() -> List[str]:
    return list(_RULES)
