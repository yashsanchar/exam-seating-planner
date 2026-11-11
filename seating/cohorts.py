"""Cohort lists -> one student row per (student, paper).

A student list PDF only gives roll number and name for one batch ("cohort"), e.g. M.Tech sem 3.
The timetable says which papers each cohort writes (its Group column), so every student of a cohort
is enrolled in every paper listed for that cohort in the timetable. The two special cases (MBA BA does
not write DS5A-623; M.Tech sem 3 writes only Numerical Methods on DS6A-204) are handled by simply
not listing those papers in the timetable.
Standard library only.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from .io_csv import clean_name, norm_code
from .models import Student


def timetable_groups(rows: Sequence[Dict[str, str]]) -> List[str]:
    """Group names in the timetable, in order of first appearance."""
    out: List[str] = []
    for row in rows:
        g = clean_name(row.get("group", "") or "")
        if g and g not in out:
            out.append(g)
    return out


def papers_of_group(rows: Sequence[Dict[str, str]], group: str) -> List[str]:
    out: List[str] = []
    for row in rows:
        if clean_name(row.get("group", "") or "").lower() == group.lower():
            code = norm_code(row.get("course", "") or "")
            if code and code not in out:
                out.append(code)
    return out


def expand_cohorts(cohorts: Dict[str, List[Tuple[str, str, bool]]], timetable: Sequence[Dict[str, str]]
                   ) -> Tuple[List[Student], Dict[str, str], List[str]]:
    """cohorts: group name -> [(roll_no, name, is_placeholder)].  Returns (students, course names, warnings)
    in the same shape the CSV student loader returns, so the rest of the app does not care where they came from."""
    students: List[Student] = []
    names: Dict[str, str] = {}
    warnings: List[str] = []
    seen_roll: Dict[str, str] = {}
    for group, people in cohorts.items():
        papers = papers_of_group(timetable, group)
        if not papers:
            warnings.append(f"{group}: no papers are listed for this group in the timetable, so its "
                            f"{len(people)} students are not seated. Check the Group column on the Timetable tab.")
            continue
        for roll, name, _placeholder in people:
            roll = norm_code(roll)
            if roll in seen_roll:
                warnings.append(f"Roll {roll} appears in two lists ({seen_roll[roll]} and {group}) - kept in both")
            seen_roll.setdefault(roll, group)
            for paper in papers:
                students.append(Student(roll, clean_name(name), paper))
    for row in timetable:
        code, cname = norm_code(row.get("course", "") or ""), clean_name(row.get("course_name", "") or "")
        if code and cname:
            names.setdefault(code, cname)
    return students, names, warnings
