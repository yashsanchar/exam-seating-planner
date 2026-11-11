"""FastAPI layer for the exam seating backend.

Run:   uvicorn app:app --reload          (or:  python app.py)
Docs:  http://127.0.0.1:8000/docs        (FastAPI builds an interactive page automatically)

Flow the frontend follows (PDF student lists: POST /api/pdf/preview -> teacher checks -> POST /api/students/confirm;
rooms/schedule PDFs: preview, then the existing PUT /api/rooms or PUT /api/timetable):
  1. GET  /api/options            -> rule + strategy names for the dropdowns
  2. POST /api/data               -> upload the student list (rooms and schedule files are optional) -> summary
     GET/PUT/POST-reset /api/rooms and /api/timetable -> the in-app room editor and timetable table
  3. POST /api/plan               -> {"rule": ..., "strategy": ...} -> seating for every session
  4. GET  /api/download/csv|json|txt
  5. GET  /api/compare?rule=...   -> side-by-side CSV of all 3 strategies (advanced)
  6. GET  /api/benchmarks         -> DAA + Computer Architecture experiment results (optional)

The routes are thin: all real work is done by the `seating` package.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from seating import (ExamData, ExamPlanner, SeatingError, SessionPlan, build_sessions, combine,
                     default_rooms, default_timetable, expand_cohorts, export_comparison_csv, export_csv, export_json,
                     export_text, find_conflicts, get_rule, get_strategy, load_rooms, load_schedule_rows,
                     load_students, room_to_spec, rooms_from_specs, rows_from_sessions, rule_names, strategy_names,
                     timetable_groups, timetable_rows_clean)
from seating import benchmarks
import pdf_import
from pdf_import import PdfProblem

BASE = Path(__file__).parent
SAMPLE = BASE / "data" / "sample"
FRONTEND = BASE / "frontend"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB per file is far more than a college needs


# --------------------------------------------------------------------------- state (OOP)
class AppState:
    """Holds what is currently loaded and the latest plan (in memory, one teacher at a time).

    Students come from an upload. Rooms and the timetable always exist: they start with the built-in
    (provisional) rooms and the printed timetable and are changed in the app or replaced by an upload.
    """

    def __init__(self) -> None:
        self.students: Optional[tuple] = None        # (students, course_names, warnings) from a CSV/Excel upload
        # student lists confirmed from PDFs: group name -> [(roll_no, name, is_placeholder)]. A student here is
        # enrolled in every paper the timetable lists for the group, so editing the timetable updates them too.
        self.cohorts: Dict[str, List[tuple]] = {}
        self.rooms = default_rooms()
        self.timetable: List[Dict[str, str]] = default_timetable()
        self.plans: List[SessionPlan] = []
        self.rule_name: str = ""
        self.strategy_name: str = ""
        self.benchmark_rows: Optional[List[dict]] = None

    @property
    def data(self) -> Optional[ExamData]:
        """Everything the planner needs, joined fresh from the three parts. None until students are loaded."""
        if self.students is None and not self.cohorts:
            return None
        if self.students is not None:
            students, s_names, s_warnings = self.students
        else:
            students, s_names, s_warnings = expand_cohorts(self.cohorts, self.timetable)
        sessions, c_names, c_warnings = build_sessions(self.timetable, "timetable row", 1)
        return combine(students, s_names, s_warnings, self.rooms, sessions, c_names, c_warnings)

    def invalidate_plan(self) -> None:
        self.plans = []          # an old plan no longer matches the changed data
        self.rule_name = self.strategy_name = ""

    def require_data(self) -> ExamData:
        data = self.data
        if data is None:
            raise HTTPException(409, "No student list loaded yet. Load it on the Data tab first.")
        return data

    def require_plan(self) -> ExamData:
        data = self.require_data()
        if not self.plans:
            raise HTTPException(409, "No plan yet. Generate one with POST /api/plan first.")
        return data


state = AppState()
app = FastAPI(title="Exam Seating Arrangement API",
              description="No two students of the same course sit beside each other.")


class RoomsBody(BaseModel):
    rooms: List[Dict[str, Any]]


class TimetableBody(BaseModel):
    rows: List[Dict[str, Any]]


class ConfirmStudentsBody(BaseModel):
    group: str
    rows: List[Dict[str, Any]]          # [{roll_no, name, include}] as checked/fixed in the preview screen


class PlanRequest(BaseModel):
    rule: str = "fourway"       # horizontal | fourway
    strategy: str = "hybrid"    # greedy | backtracking | hybrid


# --------------------------------------------------------------------------- helpers
def _save_upload(upload: UploadFile, folder: Path, name: str) -> Path:
    """The backend loaders read file paths, so uploads are written to a temp folder first.
    CSV/text files are used as they are, Excel (.xlsx) is converted to CSV. A PDF is never loaded here:
    PDFs must go through the preview screen (POST /api/pdf/preview) so nothing is loaded from a messy parse."""
    content = upload.file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{name} file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    if not content.strip():
        raise HTTPException(400, f"The {name} file is empty")
    kind = _file_kind(upload.filename or "", content)
    if kind == "pdf":
        raise HTTPException(400, f"The {name} file is a PDF. Choose it on the Data tab so it can be checked in the "
                                 "preview screen before it is loaded.")
    path = folder / f"{name}.csv"
    if kind == "excel":
        src = folder / f"{name}.xlsx"
        src.write_bytes(content)
        try:
            path.write_text(pdf_import.excel_to_csv(src), encoding="utf-8")
        except PdfProblem as exc:
            raise HTTPException(400, str(exc))
    else:
        path.write_bytes(content)
    return path


def _file_kind(filename: str, content: bytes) -> str:
    """pdf | excel | csv - decided by the extension, and by the first bytes when the extension is misleading."""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or content[:5] == b"%PDF-":
        return "pdf"
    if ext in (".xlsx", ".xlsm") or content[:2] == b"PK":
        return "excel"
    return "csv"


def _given(upload: Optional[UploadFile]) -> bool:
    """True when the browser really sent a file (an untouched file box arrives with an empty name)."""
    return upload is not None and bool(upload.filename)


def _summary(data: ExamData) -> dict:
    return {
        "enrolment_rows": len(data.students),
        "students": len({s.roll_no for s in data.students}),
        "rooms": [
            {"room_id": r.room_id, "name": r.name, "rows": r.rows, "cols": r.cols,
             "capacity": r.capacity, "available": r.available, "provisional": r.provisional}
            for r in data.rooms
        ],
        "sessions": [
            {"date": s.date, "slot": s.slot, "courses": list(s.courses)} for s in data.sessions
        ],
        "course_names": data.course_names,
        "warnings": data.warnings,
        "cohorts": [{"group": g, "students": len(p)} for g, p in state.cohorts.items()],
    }


# --------------------------------------------------------------------------- endpoints
@app.get("/api/options")
def options() -> dict:
    return {"rules": rule_names(), "strategies": strategy_names()}


@app.post("/api/data")
def upload_data(
    students: Optional[UploadFile] = File(None),
    rooms: Optional[UploadFile] = File(None),
    schedule: Optional[UploadFile] = File(None),
    demo: bool = Form(False),
) -> dict:
    """Load the student list (multipart form). Rooms and schedule files are optional: without them the rooms
    and timetable already in the app are used. demo=true loads the sample data (all three parts)."""
    try:
        if demo:
            new_students = load_students(SAMPLE / "students.csv")
            new_rooms = load_rooms(SAMPLE / "rooms.csv")
            new_rows = load_schedule_rows(SAMPLE / "schedule.csv")
        else:
            if not _given(students):
                raise HTTPException(400, "Missing the student list. Choose a students file (or send demo=true)")
            with tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp)
                new_students = load_students(_save_upload(students, folder, "students"))
                new_rooms = load_rooms(_save_upload(rooms, folder, "rooms")) if _given(rooms) else None
                new_rows = load_schedule_rows(_save_upload(schedule, folder, "schedule")) if _given(schedule) else None
        if new_rows is not None:
            build_sessions(new_rows)           # raises if the schedule has no usable row, before anything changes
    except SeatingError as exc:       # bad file contents -> readable message, not a crash
        raise HTTPException(400, str(exc))
    state.students = new_students
    state.cohorts = {}                    # a CSV/Excel student file replaces any lists confirmed from PDFs
    if new_rooms is not None:
        state.rooms = new_rooms
    if new_rows is not None:
        state.timetable = new_rows
    state.invalidate_plan()
    return _summary(state.require_data())


@app.get("/api/data")
def get_data() -> dict:
    return _summary(state.require_data())


@app.post("/api/tables")
def upload_tables(
    rooms: Optional[UploadFile] = File(None),
    schedule: Optional[UploadFile] = File(None),
) -> dict:
    """Replace only the rooms and/or the timetable from CSV/Excel files (used when the student lists come
    from PDFs). Nothing changes if any file is bad."""
    if not _given(rooms) and not _given(schedule):
        raise HTTPException(400, "Choose a rooms file or an exam schedule file.")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            new_rooms = load_rooms(_save_upload(rooms, folder, "rooms")) if _given(rooms) else None
            new_rows = load_schedule_rows(_save_upload(schedule, folder, "schedule")) if _given(schedule) else None
        if new_rows is not None:
            build_sessions(new_rows)
    except SeatingError as exc:
        raise HTTPException(400, str(exc))
    if new_rooms is not None:
        state.rooms = new_rooms
    if new_rows is not None:
        state.timetable = new_rows
    state.invalidate_plan()
    return {"rooms": len(state.rooms), "timetable_rows": len(state.timetable)}


@app.post("/api/pdf/preview")
def pdf_preview(kind: str = Form(...), file: UploadFile = File(...)) -> dict:
    """Read a PDF and return what was found. NOTHING is loaded here: the browser shows the result, the teacher
    fixes it and confirms (students: POST /api/students/confirm, rooms: PUT /api/rooms, schedule: PUT /api/timetable)."""
    if kind not in ("students", "rooms", "schedule"):
        raise HTTPException(400, "kind must be students, rooms or schedule")
    try:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            content = file.file.read(MAX_UPLOAD_BYTES + 1)
            if len(content) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"This file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
            if _file_kind(file.filename or "", content) != "pdf":
                raise HTTPException(400, "This is not a PDF file.")
            path = folder / "upload.pdf"
            path.write_bytes(content)
            if kind == "students":
                out = pdf_import.parse_student_pdf(path).to_dict()
                out["groups"] = timetable_groups(state.timetable)
                out["already_loaded"] = sorted(state.cohorts)
            else:
                csv_path = folder / "table.csv"
                csv_path.write_text(pdf_import.pdf_table_to_csv(path, kind), encoding="utf-8")
                if kind == "rooms":
                    out = {"kind": "rooms", "rooms": [room_to_spec(r) for r in load_rooms(csv_path)], "warnings": []}
                else:
                    rows = load_schedule_rows(csv_path)
                    _sessions, _names, warnings = build_sessions(rows, "row", 1)
                    out = {"kind": "schedule", "rows": rows, "warnings": warnings}
    except (PdfProblem, SeatingError) as exc:
        raise HTTPException(400, str(exc))
    out["filename"] = file.filename or ""
    return out


@app.post("/api/students/confirm")
def confirm_students(body: ConfirmStudentsBody) -> dict:
    """Load one checked student list (from the PDF preview) for one group. Loading the same group again replaces it;
    other groups already loaded stay. Each student is enrolled in the papers the timetable lists for that group."""
    group = body.group.strip()
    if not group:
        raise HTTPException(400, "Choose which group this list belongs to (for example M.Tech sem 3).")
    if group not in timetable_groups(state.timetable):
        raise HTTPException(400, f"The timetable has no group called '{group}'. Pick one from the list, or add the "
                                 "group name to the Group column on the Timetable tab first.")
    people: List[tuple] = []
    seen = set()
    for i, row in enumerate(body.rows, start=1):
        if not row.get("include", True):
            continue
        roll = " ".join(str(row.get("roll_no", "")).split()).upper()
        name = " ".join(str(row.get("name", "")).split())
        if not roll or not name:
            raise HTTPException(400, f"Row {i}: the roll number and the name must both be filled in (or untick the row).")
        if roll in seen:
            raise HTTPException(400, f"Row {i}: roll number {roll} is listed twice.")
        seen.add(roll)
        people.append((roll, name, False))
    if not people:
        raise HTTPException(400, "No students are ticked. Tick the students to load.")
    state.cohorts[group] = people
    state.students = None                 # lists from PDFs replace any CSV student file
    state.invalidate_plan()
    return _summary(state.require_data())


@app.delete("/api/students/{group}")
def remove_group(group: str) -> dict:
    """Forget one loaded student list (so it can be loaded again or left out)."""
    if group not in state.cohorts:
        raise HTTPException(404, f"No list loaded for '{group}'.")
    del state.cohorts[group]
    state.invalidate_plan()
    if not state.cohorts:
        return {"students": 0, "cohorts": []}
    return _summary(state.require_data())


@app.get("/api/rooms")
def get_rooms() -> dict:
    return {"rooms": [room_to_spec(r) for r in state.rooms]}


@app.put("/api/rooms")
def save_rooms(body: RoomsBody) -> dict:
    """Replace all rooms with the edited list from the room editor (validated; old plan is dropped)."""
    try:
        rooms = rooms_from_specs(body.rooms)
    except SeatingError as exc:
        raise HTTPException(400, str(exc))
    state.rooms = rooms
    state.invalidate_plan()
    return get_rooms()


@app.post("/api/rooms/reset")
def reset_rooms() -> dict:
    state.rooms = default_rooms()
    state.invalidate_plan()
    return get_rooms()


def _timetable_view() -> dict:
    sessions, _names, warnings = build_sessions(state.timetable, "timetable row", 1)
    return {"rows": state.timetable, "days": len({s.date for s in sessions}), "sessions": len(sessions),
            "warnings": warnings}


@app.get("/api/timetable")
def get_timetable() -> dict:
    return _timetable_view()


@app.put("/api/timetable")
def save_timetable(body: TimetableBody) -> dict:
    """Replace the timetable with the edited table (validated; old plan is dropped)."""
    try:
        rows = timetable_rows_clean(body.rows)
        build_sessions(rows, "timetable row", 1)
    except SeatingError as exc:
        raise HTTPException(400, str(exc))
    state.timetable = rows
    state.invalidate_plan()
    return _timetable_view()


@app.post("/api/timetable/reset")
def reset_timetable() -> dict:
    state.timetable = default_timetable()
    state.invalidate_plan()
    return _timetable_view()


@app.post("/api/plan")
def make_plan(req: PlanRequest) -> dict:
    data = state.require_data()
    if req.rule not in rule_names():
        raise HTTPException(400, f"Unknown rule '{req.rule}'. Choose from: {', '.join(rule_names())}")
    if req.strategy not in strategy_names():
        raise HTTPException(400, f"Unknown strategy '{req.strategy}'. Choose from: {', '.join(strategy_names())}")

    rule = get_rule(req.rule)
    planner = ExamPlanner(data, rule, get_strategy(req.strategy))
    plans = planner.plan_all()
    state.plans, state.rule_name, state.strategy_name = plans, req.rule, req.strategy

    sessions = []
    total_conflicts = 0
    for plan in plans:
        item = plan.to_dict()
        # independent checker (verify.py) re-inspects every filled room
        item["conflicts"] = sum(len(find_conflicts(rp.room, rule)) for rp in plan.room_plans)
        total_conflicts += item["conflicts"]
        sessions.append(item)
    return {
        "rule": req.rule,
        "strategy": req.strategy,
        "sessions": sessions,
        "failed_sessions": sum(1 for p in plans if not p.ok),
        "total_conflicts": total_conflicts,
        "course_names": data.course_names,
        "data_warnings": data.warnings,
    }


@app.get("/api/download/{fmt}")
def download(fmt: str) -> Response:
    """fmt = csv | json | txt  -> the latest plan as a file."""
    data = state.require_plan()
    writers = {
        "csv": (lambda p: export_csv(state.plans, data, p), "text/csv", "seating_all.csv"),
        "json": (lambda p: export_json(state.plans, data, p), "application/json", "plan.json"),
        "txt": (lambda p: export_text(state.plans, p), "text/plain", "grids.txt"),
    }
    if fmt not in writers:
        raise HTTPException(404, "Format must be csv, json or txt")
    write, media_type, filename = writers[fmt]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / filename
        write(path)
        content = path.read_bytes()
    return Response(content, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/compare")
def compare_download(rule: str = "fourway") -> Response:
    """Runs greedy, backtracking and hybrid on every session and returns a side-by-side CSV
    (search steps and time). For the report/PPT; the normal screen does not show it."""
    data = state.require_data()
    if rule not in rule_names():
        raise HTTPException(400, f"Unknown rule '{rule}'. Choose from: {', '.join(rule_names())}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "strategy_comparison.csv"
        export_comparison_csv(data, rule, path)
        content = path.read_bytes()
    return Response(content, media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="strategy_comparison.csv"'})


@app.get("/api/benchmarks")
def get_benchmarks() -> dict:
    """Run the timing experiments once (a few seconds), then serve the cached result."""
    if state.benchmark_rows is None:
        rows: List[dict] = []
        for fn in (benchmarks.bench_solvers, benchmarks.bench_feasibility,
                   benchmarks.bench_bitmask, benchmarks.bench_memory_layout):
            for experiment, size, n, variant, time_text, note in fn():
                rows.append({"experiment": experiment, "size": size, "n": n,
                             "variant": variant, "time": time_text, "note": note})
        state.benchmark_rows = rows
    return {
        "rows": state.benchmark_rows,
        "note": "Python's interpreter overhead hides most cache effects; the direction of the "
                "results is visible but the gaps are smaller than they would be in C or Java.",
    }


# --------------------------------------------------------------------------- frontend
if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
else:
    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/docs")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)
