"""Loading the real data (students, rooms, exam schedule) and exporting the plan.

Made to be forgiving so files straight from Excel work:
  * delimiter is detected (comma, semicolon, tab or pipe); Excel's UTF-8 BOM is handled
  * header names are matched loosely: "Roll No.", "roll_number", "ROLLNO" all work
  * course codes / roll numbers ignore case and inner spaces ("cs 201" == "CS201")
  * a column_map can force a mapping if a header is unusual
Row / seat numbers in files are 1-based (row 1 = front row).
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .errors import DataFormatError
from .models import ExamData, ExamSession, Position, Room, SessionPlan, Student, natural_key
from .seat_encoding import FLAG_OCCUPIED, seat_code

# canonical field -> (accepted header names, required?)
STUDENT_COLUMNS = {
    "roll_no": (["rollno", "roll", "rollnumber", "rollnum", "enrollmentno", "enrollment", "regno",
                 "registrationno", "registrationnumber", "studentid", "id"], True),
    "name": (["name", "studentname", "fullname", "student"], True),
    "course": (["course", "coursecode", "subject", "subjectcode", "paper", "papercode", "code"], True),
    "course_name": (["coursename", "subjectname", "papername", "title", "coursetitle"], False),
}
ROOM_COLUMNS = {
    "room_id": (["roomid", "room", "roomno", "roomnumber", "classroom", "hall", "id", "code", "roomname", "name"], True),
    "name": (["name", "roomname", "title"], False),
    "rows": (["rows", "numrows", "noofrows", "row", "nrows"], False),
    "cols": (["cols", "columns", "numcols", "noofcols", "col", "column", "ncols", "seatsperrow"], False),
    "blocked": (["blocked", "blockedseats", "unusable", "brokenseats", "disabled"], False),
    "layout": (["layout", "seatmap", "map", "grid"], False),
    "available": (["available", "active", "usable", "inuse", "enabled"], False),
}
SCHEDULE_COLUMNS = {
    "date": (["date", "examdate", "day"], True),
    "slot": (["slot", "session", "time", "shift", "timeslot", "sitting", "examtime"], False),
    "course": (["course", "coursecode", "subject", "subjectcode", "paper", "papercode", "code"], True),
    "course_name": (["coursename", "subjectname", "papername", "title", "coursetitle"], False),
    "group": (["group", "class", "cohort", "batch", "programme", "program"], False),
}


# --------------------------------------------------------------------------- helpers
def norm_header(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2212"), "-")   # en dash, em dash, minus...


def norm_code(text: str) -> str:
    """Course code / roll number: no inner spaces, upper case, any kind of dash becomes '-'
    ("DS6A \u2013 201" == "ds6a-201")."""
    return re.sub(r"\s+", "", text.translate(_DASHES)).upper()


def clean_name(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_table(path) -> Tuple[List[str], List[Dict[str, str]]]:
    """Read a delimited text file -> (headers, rows). Blank lines are skipped."""
    p = Path(path)
    if not p.exists():
        raise DataFormatError(f"File not found: {p}")
    text = p.read_text(encoding="utf-8-sig")
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        raise DataFormatError(f"{p.name} is empty")
    try:
        delimiter = csv.Sniffer().sniff(lines[0], delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ","
    reader = csv.reader(lines, delimiter=delimiter)
    headers = [h.strip() for h in next(reader)]
    rows = []
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        values = [v.strip() for v in values] + [""] * (len(headers) - len(values))
        rows.append(dict(zip(headers, values)))
    return headers, rows


def map_columns(
    headers: Sequence[str],
    spec: Dict[str, Tuple[List[str], bool]],
    file_label: str,
    column_map: Optional[Dict[str, str]] = None,
) -> Dict[str, Optional[str]]:
    """canonical field -> actual header text in the file (or None if optional and absent)."""
    by_norm = {norm_header(h): h for h in headers}
    claimed: set = set()
    mapping: Dict[str, Optional[str]] = {}
    column_map = column_map or {}
    for field, (aliases, required) in spec.items():
        found = None
        if field in column_map:
            if column_map[field] not in headers:
                raise DataFormatError(f"{file_label}: column '{column_map[field]}' not found. Headers: {list(headers)}")
            found = column_map[field]
        else:
            for alias in aliases:
                header = by_norm.get(alias)
                if header is not None and header not in claimed:
                    found = header
                    break
        if found is None and required:
            raise DataFormatError(
                f"{file_label}: could not find a '{field}' column. Headers seen: {list(headers)}. "
                f"Accepted names include: {', '.join(aliases[:5])}"
            )
        if found is not None:
            claimed.add(found)
        mapping[field] = found
    return mapping


def _get(row: Dict[str, str], mapping: Dict[str, Optional[str]], field: str) -> str:
    header = mapping.get(field)
    return row.get(header, "").strip() if header else ""


# --------------------------------------------------------------------------- students
def load_students(path, column_map=None) -> Tuple[List[Student], Dict[str, str], List[str]]:
    """One row = one student enrolled in one course. A student with 5 papers has 5 rows."""
    headers, rows = read_table(path)
    m = map_columns(headers, STUDENT_COLUMNS, "students file", column_map)
    students: List[Student] = []
    names: Dict[str, str] = {}
    warnings: List[str] = []
    seen = set()
    roll_names: Dict[str, str] = {}
    for i, row in enumerate(rows, start=2):
        roll = norm_code(_get(row, m, "roll_no"))
        name = clean_name(_get(row, m, "name"))
        course = norm_code(_get(row, m, "course"))
        if not (roll and name and course):
            warnings.append(f"students file line {i}: skipped (roll, name or paper is blank)")
            continue
        if (roll, course) in seen:
            warnings.append(f"students file line {i}: duplicate of roll {roll} in paper {course} - ignored")
            continue
        seen.add((roll, course))
        if roll in roll_names and roll_names[roll].lower() != name.lower():
            warnings.append(f"students file line {i}: roll {roll} appears with two names ('{roll_names[roll]}', '{name}')")
        roll_names.setdefault(roll, name)
        cname = clean_name(_get(row, m, "course_name"))
        if cname:
            names.setdefault(course, cname)
        students.append(Student(roll, name, course))
    if not students:
        raise DataFormatError("students file has no usable rows")
    return students, names, warnings


# --------------------------------------------------------------------------- rooms
_BLOCK_RC = re.compile(r"^(\d+)\s*[-:xX]\s*(\d+)$")
_BLOCK_RxCy = re.compile(r"^[rR](\d+)[cCsS](\d+)$")
_SEAT_CHARS = set("1.oOsS")
_GAP_CHARS = set("0xX#_-")


def parse_blocked(text: str, room_id: str) -> List[Position]:
    out: List[Position] = []
    for token in re.split(r"[;,|\s]+", text.strip()):
        if not token:
            continue
        match = _BLOCK_RC.match(token) or _BLOCK_RxCy.match(token)
        if not match:
            raise DataFormatError(f"Room {room_id}: cannot read blocked seat '{token}' (use row-col, e.g. 2-5)")
        r, c = int(match.group(1)), int(match.group(2))
        if r < 1 or c < 1:
            raise DataFormatError(f"Room {room_id}: seat numbers start at 1 (got '{token}')")
        out.append((r - 1, c - 1))
    return out


def parse_layout(text: str, room_id: str) -> Tuple[int, int, List[Position]]:
    """'11111/11011/11111' -> rows, cols, blocked. 1 . o s = seat;  0 x # _ - = no seat."""
    lines = [ln.strip() for ln in text.split("/") if ln.strip()]
    if not lines:
        raise DataFormatError(f"Room {room_id}: layout is empty")
    cols = max(len(ln) for ln in lines)
    blocked: List[Position] = []
    for r, line in enumerate(lines):
        for c in range(cols):
            ch = line[c] if c < len(line) else "0"
            if ch in _GAP_CHARS:
                blocked.append((r, c))
            elif ch not in _SEAT_CHARS:
                raise DataFormatError(f"Room {room_id}: unknown layout character '{ch}'")
    return len(lines), cols, blocked


def _yes(text: str, default: bool = True) -> bool:
    t = text.strip().lower()
    if not t:
        return default
    if t in {"yes", "y", "true", "1", "available", "open"}:
        return True
    if t in {"no", "n", "false", "0", "closed", "unavailable"}:
        return False
    raise DataFormatError(f"cannot read yes/no value '{text}'")


def load_rooms(path, column_map=None) -> List[Room]:
    headers, rows = read_table(path)
    m = map_columns(headers, ROOM_COLUMNS, "rooms file", column_map)
    rooms: List[Room] = []
    ids = set()
    for i, row in enumerate(rows, start=2):
        rid = clean_name(_get(row, m, "room_id"))
        if not rid:
            continue
        if rid.upper() in ids:
            raise DataFormatError(f"rooms file line {i}: room '{rid}' is listed twice")
        ids.add(rid.upper())
        layout = _get(row, m, "layout")
        blocked: List[Position] = []
        try:
            if layout:
                nrows, ncols, blocked = parse_layout(layout, rid)
            else:
                rows_txt, cols_txt = _get(row, m, "rows"), _get(row, m, "cols")
                if not (rows_txt.isdigit() and cols_txt.isdigit()):
                    raise DataFormatError(f"Room {rid}: needs numeric rows and cols (or a layout)")
                nrows, ncols = int(rows_txt), int(cols_txt)
                blocked = parse_blocked(_get(row, m, "blocked"), rid)
            available = _yes(_get(row, m, "available"))
        except DataFormatError as exc:
            raise DataFormatError(f"rooms file line {i}: {exc}")
        rooms.append(Room(rid, nrows, ncols, blocked, _get(row, m, "name"), available))
    if not rooms:
        raise DataFormatError("rooms file has no usable rows")
    return rooms


# --------------------------------------------------------------------------- schedule
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def build_sessions(entries: Sequence[Dict[str, str]], where: str = "schedule file line",
                   first_number: int = 2) -> Tuple[List[ExamSession], Dict[str, str], List[str]]:
    """entries: dicts with date, slot, course, course_name and (optional) group, one per paper.
    Entries with the same date + slot form one session. Shared by the CSV loader and the in-app
    timetable table. The same paper listed twice in one slot is merged; it is only reported when
    both entries come from the same group (two groups legitimately share a paper)."""
    grouped: Dict[Tuple[str, str], List[str]] = {}
    seen_groups: Dict[Tuple[Tuple[str, str], str], set] = {}
    names: Dict[str, str] = {}
    warnings: List[str] = []
    paper_slots: Dict[str, Tuple[str, str]] = {}
    for i, row in enumerate(entries, start=first_number):
        date = clean_name(row.get("date", ""))
        slot = clean_name(row.get("slot", "")) or "-"
        course = norm_code(row.get("course", ""))
        group = clean_name(row.get("group", ""))
        if not (date and course):
            warnings.append(f"{where} {i}: skipped (date or paper is blank)")
            continue
        key = (date, slot)
        if course in grouped.setdefault(key, []):
            groups = seen_groups.setdefault((key, course), set())
            if group in groups or not group:
                warnings.append(f"{where} {i}: {course} listed twice in {date} / {slot} - ignored")
            groups.add(group)
            continue
        if course in paper_slots and paper_slots[course] != key:
            warnings.append(f"{where} {i}: {course} is scheduled in more than one slot")
        paper_slots.setdefault(course, key)
        grouped[key].append(course)
        seen_groups.setdefault((key, course), set()).add(group)
        cname = clean_name(row.get("course_name", ""))
        if cname:
            names.setdefault(course, cname)
    if not grouped:
        raise DataFormatError("schedule has no usable rows")
    keys = list(grouped)
    if all(ISO_DATE.match(d) for d, _ in keys):
        keys.sort()                                   # real dates: show the days in order
    sessions = [ExamSession(d, sl, tuple(grouped[(d, sl)])) for (d, sl) in keys]
    return sessions, names, warnings


def load_schedule_rows(path, column_map=None) -> List[Dict[str, str]]:
    """Read a schedule file into timetable entries (date, slot, course, course_name, group)."""
    headers, rows = read_table(path)
    m = map_columns(headers, SCHEDULE_COLUMNS, "schedule file", column_map)
    return [{"date": clean_name(_get(row, m, "date")), "slot": clean_name(_get(row, m, "slot")),
             "course": norm_code(_get(row, m, "course")), "course_name": clean_name(_get(row, m, "course_name")),
             "group": clean_name(_get(row, m, "group"))} for row in rows]


def load_schedule(path, column_map=None) -> Tuple[List[ExamSession], Dict[str, str], List[str]]:
    """One row = one paper in one slot. Rows with the same date+slot form one session."""
    try:
        return build_sessions(load_schedule_rows(path, column_map))
    except DataFormatError as exc:
        raise DataFormatError(str(exc).replace("schedule has no", "schedule file has no"))


# --------------------------------------------------------------------------- everything
def combine(students: List[Student], s_names: Dict[str, str], s_warnings: List[str],
            rooms: List[Room], sessions: List[ExamSession], c_names: Dict[str, str],
            c_warnings: List[str]) -> ExamData:
    """Join the three parts and add the cross-checks (papers with no students, and the reverse)."""
    warnings = list(s_warnings) + list(c_warnings)
    known = {s.course for s in students}
    scheduled = {c for sess in sessions for c in sess.courses}
    unknown = sorted(scheduled - known)
    if unknown:
        warnings.append(f"Papers in the schedule with no students: {', '.join(unknown)}")
    unscheduled = sorted(known - scheduled)
    if unscheduled:
        warnings.append(f"Papers in the student file that are not in the schedule: {', '.join(unscheduled)}")
    names = dict(s_names)
    names.update(c_names)
    return ExamData(students, rooms, sessions, names, warnings)


def load_all(students_path, rooms_path, schedule_path, column_maps: Optional[Dict[str, Dict[str, str]]] = None) -> ExamData:
    column_maps = column_maps or {}
    students, s_names, w1 = load_students(students_path, column_maps.get("students"))
    rooms = load_rooms(rooms_path, column_maps.get("rooms"))
    sessions, c_names, w2 = load_schedule(schedule_path, column_maps.get("schedule"))
    return combine(students, s_names, w1, rooms, sessions, c_names, w2)


# --------------------------------------------------------------------------- export
def export_csv(plans: Iterable[SessionPlan], data: ExamData, path) -> int:
    """One row per seated student. Returns the number of rows written."""
    index = {r.room_id: i for i, r in enumerate(data.rooms)}
    count = 0
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "slot", "room", "row", "seat", "seat_code", "roll_no", "name", "course"])
        for plan in plans:
            for rp in plan.room_plans:
                room = rp.room
                for r in range(room.rows):
                    for c in range(room.cols):
                        st = room.seat(r, c).student
                        if st is None:
                            continue
                        code = seat_code(index.get(room.room_id, 0), r, c, FLAG_OCCUPIED)
                        w.writerow([plan.session.date, plan.session.slot, room.room_id, r + 1, c + 1,
                                    code, st.roll_no, st.name, st.course])
                        count += 1
    return count


def export_json(plans: Iterable[SessionPlan], data: ExamData, path) -> None:
    payload = {
        "sessions": [p.to_dict() for p in plans],
        "course_names": data.course_names,
        "data_warnings": data.warnings,
    }
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_room_text(room: Room) -> str:
    """ASCII grid of course codes. ## = blocked seat, -- = empty seat. Row 1 is the front."""
    grid = room.course_grid()
    width = max([len(x) for row in grid for x in row if x] + [2])
    lines = []
    for r, row in enumerate(grid):
        cells = [("--" if x is None else x).center(width) for x in row]
        lines.append(f"R{r + 1:<2} " + " ".join(cells))
    return "\n".join(lines)


def export_text(plans: Iterable[SessionPlan], path) -> None:
    out: List[str] = []
    for plan in plans:
        out.append("=" * 72)
        out.append(f"{plan.session.date} | {plan.session.slot} | courses: {', '.join(plan.session.courses)}")
        out.append(f"students: {plan.student_count}")
        for w in plan.warnings:
            out.append(f"  warning: {w}")
        if plan.error:
            out.append(f"  FAILED: {plan.error}")
        for rp in plan.room_plans:
            out.append("")
            tag = "  [PROVISIONAL LAYOUT - check the room]" if rp.room.provisional else ""
            out.append(f"Room {rp.room.room_id} ({rp.room.rows}x{rp.room.cols}) - {rp.room.occupied} students - {rp.strategy}{tag}")
            out.append(render_room_text(rp.room))
        out.append("")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(out), encoding="utf-8")
