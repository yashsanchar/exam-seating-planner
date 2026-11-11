"""Run every seating strategy on the same data and put the results side by side.

DAA : shows the difference between greedy (fast, can dead-end), backtracking (complete, more
      work) and hybrid (greedy first, backtracking only when needed) on the real exam days.
      "Search steps" = seats examined / recursive calls, counted by each strategy.

Timing is wall-clock time of the whole session plan (room selection + solving). It is measured
`repeats` times and the fastest run is kept, which removes most one-off noise. Search steps do
not change between runs.
"""

from __future__ import annotations

import csv
import time
from pathlib import Path
from typing import Dict, List

from .models import ExamData
from .planner import ExamPlanner
from .rules import get_rule
from .strategies import get_strategy, strategy_names
from .verify import find_conflicts


def compare_strategies(data: ExamData, rule_name: str = "fourway", repeats: int = 3) -> List[dict]:
    """One row per exam session; for each strategy: search steps, time (ms) and result."""
    rule = get_rule(rule_name)
    planners = {name: ExamPlanner(data, rule, get_strategy(name)) for name in strategy_names()}
    rows: List[dict] = []
    for session in data.sessions:
        row: Dict[str, object] = {"date": session.date, "slot": session.slot}
        for name, planner in planners.items():
            best = None
            plan = None
            for _ in range(max(1, repeats)):
                start = time.perf_counter()
                plan = planner.plan_session(session)
                elapsed = (time.perf_counter() - start) * 1000
                best = elapsed if best is None else min(best, elapsed)
            assert plan is not None
            row["students"] = plan.student_count
            row[f"{name}_rooms"] = len(plan.room_plans)
            row[f"{name}_steps"] = sum(rp.nodes for rp in plan.room_plans)
            row[f"{name}_ms"] = round(best, 3)
            conflicts = sum(len(find_conflicts(rp.room, rule)) for rp in plan.room_plans)
            if not plan.ok:
                row[f"{name}_result"] = "could not seat"
            elif conflicts:
                row[f"{name}_result"] = f"{conflicts} conflicts"
            else:
                row[f"{name}_result"] = "ok"
        rows.append(row)
    return rows


def comparison_table(rows: List[dict], rule_name: str) -> List[List[object]]:
    """Header + one line per session + a TOTAL line, ready for csv.writer."""
    names = strategy_names()
    header: List[object] = ["Date", "Slot", "Students", "Rule"]
    for n in names:
        header += [f"{n} rooms", f"{n} search steps", f"{n} time (ms)", f"{n} result"]
    out: List[List[object]] = [header]
    totals = {n: [0, 0.0, 0] for n in names}       # steps, ms, sessions that worked
    for r in rows:
        line: List[object] = [r["date"], r["slot"], r.get("students", 0), rule_name]
        for n in names:
            line += [r[f"{n}_rooms"], r[f"{n}_steps"], r[f"{n}_ms"], r[f"{n}_result"]]
            totals[n][0] += r[f"{n}_steps"]
            totals[n][1] += r[f"{n}_ms"]
            totals[n][2] += 1 if r[f"{n}_result"] == "ok" else 0
        out.append(line)
    total_line: List[object] = ["TOTAL", "", sum(r.get("students", 0) for r in rows), rule_name]
    for n in names:
        steps, ms, ok = totals[n]
        total_line += ["", steps, round(ms, 3), f"{ok} of {len(rows)} sessions ok"]
    out.append(total_line)
    return out


def export_comparison_csv(data: ExamData, rule_name: str, path: Path, repeats: int = 3) -> List[List[object]]:
    table = comparison_table(compare_strategies(data, rule_name, repeats), rule_name)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:   # utf-8-sig: opens cleanly in Excel
        csv.writer(fh).writerows(table)
    return table
