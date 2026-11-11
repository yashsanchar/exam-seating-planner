"""Timing experiments to show during the evaluation.   Run:  python main.py --benchmark

A. DAA  : solver running time and search steps as the room grows.
B. DAA  : feasibility check (Kuhn matching) running time.
C. CA   : bitmask conflict check vs plain nested loops.
D. CA   : memory layout - flat array vs list of lists, row-major vs column-major walk.

Python's interpreter adds its own overhead, so cache effects are smaller than in C/Java,
but the direction of the results is still visible. Say so honestly when presenting.
"""

from __future__ import annotations

import csv
import random
import time
from array import array
from pathlib import Path
from typing import Callable, List, Tuple

from . import bitops
from .errors import InfeasibleArrangementError
from .models import Room, Student
from .rules import FourWayRule, HorizontalRule
from .strategies import BacktrackingStrategy, GreedyStrategy, HybridStrategy


def best_of(fn: Callable[[], object], repeats: int = 3) -> float:
    """Smallest wall-clock time (seconds) over several runs - reduces noise."""
    best = float("inf")
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn()
        best = min(best, time.perf_counter() - t0)
    return best


def _students(n: int, k: int, seed: int = 1) -> List[Student]:
    rng = random.Random(seed)
    return [Student(f"{i:05d}", f"S{i}", f"C{rng.randint(1, k)}") for i in range(n)]


def _filled_room(n: int, seed: int = 2) -> Room:
    rng = random.Random(seed)
    room = Room("B", n, n)
    for r in range(n):
        for c in range(n):
            if rng.random() < 0.9:
                room.place(r, c, Student(f"{r}-{c}", "x", rng.choice("ABCD")))
    return room


# ------------------------------------------------------------------ A
def bench_solvers(sizes=(6, 10, 14, 20)) -> List[Tuple]:
    rows = []
    rule = FourWayRule()
    for n in sizes:
        room = Room("S", n, n)
        studs = _students(int(n * n * 0.8), 3)
        for strat in (GreedyStrategy(), BacktrackingStrategy(), HybridStrategy()):
            try:
                t0 = time.perf_counter()
                res = strat.solve(room, studs, rule)
                elapsed = time.perf_counter() - t0
                rows.append(("solver", f"{n}x{n}", len(studs), strat.name, f"{elapsed * 1000:.2f} ms", res.nodes))
            except InfeasibleArrangementError:
                rows.append(("solver", f"{n}x{n}", len(studs), strat.name, "no answer", "-"))
    return rows


# ------------------------------------------------------------------ B
def bench_feasibility(sizes=(8, 16, 24, 32)) -> List[Tuple]:
    rows = []
    for n in sizes:
        room = Room("F", n, n)
        t_h = best_of(lambda: HorizontalRule().independent_capacity(room))
        t_f = best_of(lambda: FourWayRule().independent_capacity(room), repeats=2)
        rows.append(("feasibility", f"{n}x{n}", n * n, "horizontal runs", f"{t_h * 1000:.3f} ms", "-"))
        rows.append(("feasibility", f"{n}x{n}", n * n, "bipartite matching", f"{t_f * 1000:.3f} ms", "-"))
    return rows


# ------------------------------------------------------------------ C
def bench_bitmask(sizes=(10, 30, 60)) -> List[Tuple]:
    """Building the masks costs one pass over the grid. After that (or when the masks are
    updated while seats are filled) a whole-row check is a couple of word operations."""
    rows = []
    rule = FourWayRule()
    for n in sizes:
        room = _filled_room(n)
        masks = bitops.course_row_masks(room)
        assert bitops.conflicts_from_masks(masks, rule) == bitops.conflicts_loop(room, rule)
        t_build = best_of(lambda: bitops.course_row_masks(room))
        t_check = best_of(lambda: bitops.conflicts_from_masks(masks, rule))
        t_loop = best_of(lambda: bitops.conflicts_loop(room, rule))
        rows.append(("bitmask", f"{n}x{n}", n * n, "nested loops (every seat)", f"{t_loop * 1000:.3f} ms", "-"))
        rows.append(("bitmask", f"{n}x{n}", n * n, "bitmask check (masks ready)", f"{t_check * 1000:.3f} ms",
                     f"{t_loop / t_check:.1f}x faster" if t_check else "-"))
        rows.append(("bitmask", f"{n}x{n}", n * n, "building the masks (one pass)", f"{t_build * 1000:.3f} ms", "-"))
    return rows


# ------------------------------------------------------------------ D
def bench_memory_layout(n: int = 1000) -> List[Tuple]:
    flat = array("i", range(n * n))
    nested = [[r * n + c for c in range(n)] for r in range(n)]

    def flat_row_major():
        total = 0
        for r in range(n):
            base = r * n
            for c in range(n):
                total += flat[base + c]
        return total

    def flat_col_major():
        total = 0
        for c in range(n):
            for r in range(n):
                total += flat[r * n + c]
        return total

    def nested_row_major():
        total = 0
        for r in range(n):
            row = nested[r]
            for c in range(n):
                total += row[c]
        return total

    def nested_col_major():
        total = 0
        for c in range(n):
            for r in range(n):
                total += nested[r][c]
        return total

    rows = []
    base = None
    for label, fn in (("flat array, row-major walk", flat_row_major),
                      ("flat array, column-major walk", flat_col_major),
                      ("list of lists, row-major walk", nested_row_major),
                      ("list of lists, column-major walk", nested_col_major)):
        t = best_of(fn, repeats=2)
        base = base or t
        rows.append(("memory", f"{n}x{n}", n * n, label, f"{t * 1000:.1f} ms", f"{t / base:.2f}x"))
    return rows


# ------------------------------------------------------------------ run
def run_all(out_dir="output") -> None:
    sections = [
        ("A. Solvers (four-way rule, 80% full rooms, 3 courses)", bench_solvers),
        ("B. Feasibility check", bench_feasibility),
        ("C. Bitmask vs loops (conflict count)", bench_bitmask),
        ("D. Memory layout and access order", bench_memory_layout),
    ]
    all_rows: List[Tuple] = []
    for title, fn in sections:
        print(f"\n{title}")
        print("-" * len(title))
        rows = fn()
        for row in rows:
            print(f"  {row[1]:>10}  n={row[2]:<8} {row[3]:<34} {row[4]:>12}  {row[5]}")
        all_rows.extend(rows)
    path = Path(out_dir) / "benchmarks.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["experiment", "size", "n", "variant", "time", "note"])
        w.writerows(all_rows)
    print(f"\nSaved to {path}")
