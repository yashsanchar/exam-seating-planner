"""Command-line runner for the exam seating backend.

Examples
--------
  python main.py --demo                       # run on the bundled sample data
  python main.py --students data/students.csv --rooms data/rooms.csv --schedule data/schedule.csv
  python main.py --demo --rule horizontal --strategy greedy --out output
  python main.py --demo --validate-only       # just check the files and print a summary
  python main.py --benchmark                  # DAA + Computer Architecture experiments
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from seating import (ExamPlanner, SeatingError, export_csv, export_json, export_text,
                     find_conflicts, get_rule, get_strategy, load_all, rule_names, strategy_names)

SAMPLE = Path(__file__).parent / "data" / "sample"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Exam seating arrangement (no two same-course students side by side)")
    p.add_argument("--students", help="students CSV (roll, name, course)")
    p.add_argument("--rooms", help="rooms CSV (room, rows, cols, blocked / layout)")
    p.add_argument("--schedule", help="exam schedule CSV (date, slot, course)")
    p.add_argument("--demo", action="store_true", help="use the sample data in data/sample")
    p.add_argument("--rule", default="fourway", choices=rule_names(), help="what counts as 'beside' (default fourway)")
    p.add_argument("--strategy", default="hybrid", choices=strategy_names(), help="solver (default hybrid)")
    p.add_argument("--out", default="output", help="folder for result files (default: output)")
    p.add_argument("--validate-only", action="store_true", help="load and check the files, then stop")
    p.add_argument("--benchmark", action="store_true", help="run the timing experiments and exit")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.benchmark:
        from seating import benchmarks
        benchmarks.run_all(args.out)
        return 0

    if args.demo:
        paths = (SAMPLE / "students.csv", SAMPLE / "rooms.csv", SAMPLE / "schedule.csv")
    elif args.students and args.rooms and args.schedule:
        paths = (args.students, args.rooms, args.schedule)
    else:
        print("Give --students, --rooms and --schedule (or use --demo).")
        return 2

    try:
        data = load_all(*paths)
    except SeatingError as exc:
        print(f"Data problem: {exc}")
        return 1

    print(f"Loaded {len(data.students)} enrolment rows, {len(data.rooms)} rooms "
          f"({sum(1 for r in data.rooms if r.available)} available), {len(data.sessions)} sessions")
    for w in data.warnings:
        print(f"  warning: {w}")
    if args.validate_only:
        return 0

    planner = ExamPlanner(data, get_rule(args.rule), get_strategy(args.strategy))
    plans = planner.plan_all()

    failed = 0
    for plan in plans:
        label = f"{plan.session.date} | {plan.session.slot}"
        if not plan.ok:
            failed += 1
            print(f"[FAILED] {label}: {plan.error}")
            continue
        conflicts = sum(len(find_conflicts(rp.room, planner.rule)) for rp in plan.room_plans)
        rooms = ", ".join(f"{rp.room.room_id}({rp.room.occupied})" for rp in plan.room_plans)
        print(f"[ok]     {label}: {plan.student_count} students -> {rooms}; conflicts={conflicts}")
        for w in plan.warnings:
            print(f"           warning: {w}")

    out = Path(args.out)
    rows = export_csv(plans, data, out / "seating_all.csv")
    export_json(plans, data, out / "plan.json")
    export_text(plans, out / "grids.txt")
    print(f"\nWrote {rows} seat assignments to {out}/ (seating_all.csv, plan.json, grids.txt)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
