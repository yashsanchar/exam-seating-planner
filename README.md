# Exam Seating Arrangement - Backend

Python 3.8+. The `seating` package is standard library only; the API (`app.py`) needs FastAPI (see below).
Goal: seat students for each exam session so that no two students of the **same course** sit beside each other.

## Quick start

```
python main.py --demo                                  # run on the sample data in data/sample
python main.py --students S.csv --rooms R.csv --schedule X.csv --rule fourway --strategy hybrid
python main.py --demo --validate-only                  # only check that the files load
python main.py --benchmark                             # timing experiments (DAA + Computer Architecture)
python -m unittest discover -s tests -t .              # all tests (needs fastapi + httpx for the API tests); or: python -m pytest -q
```
Results go to `output/`: `seating_all.csv` (one row per seated student), `plan.json` (for the API/frontend later),
`grids.txt` (printable room grids), `benchmarks.csv`.

Options: `--rule horizontal` (only left/right count as "beside") or `fourway` (also front/back, default);
`--strategy greedy | backtracking | hybrid` (default hybrid).

## API (FastAPI)

```
pip install -r requirements.txt
uvicorn app:app --reload          # then open http://127.0.0.1:8000/docs  (interactive page, try every endpoint)
```
| Endpoint | Purpose |
|---|---|
| `GET /api/options` | rule and strategy names for dropdowns |
| `POST /api/data` | multipart upload: `students` is required; `rooms` and `schedule` are optional and replace the in-app tables; or form field `demo=true` |
| `POST /api/pdf/preview` | multipart `kind` (students/rooms/schedule) + `file` (PDF): reads it and returns what was found. **Loads nothing.** Scanned PDFs get a plain 400 message |
| `POST /api/students/confirm` | JSON `{group, rows:[{roll_no,name,include}]}`: loads one checked student list for one group (same group again replaces it) |
| `DELETE /api/students/{group}` | forget one loaded list |
| `POST /api/tables` | multipart `rooms` and/or `schedule` (CSV/Excel) without a student file |
| `GET /api/data` | summary of what is loaded (rooms, sessions, warnings) |
| `GET /api/rooms`, `PUT /api/rooms`, `POST /api/rooms/reset` | the room editor: list rooms (layout = one string of 1/0 per row), save the edited list, go back to the built-in rooms |
| `GET /api/timetable`, `PUT /api/timetable`, `POST /api/timetable/reset` | the timetable table: one row per paper (date, slot, course, course_name, group) |
| `POST /api/plan` | JSON `{"rule": "fourway", "strategy": "hybrid"}` -> seating for every session (`SessionPlan.to_dict()` + `conflicts` count from `verify.py`) |
| `GET /api/download/csv\|json\|txt` | latest plan as a file |
| `GET /api/compare?rule=fourway` | runs greedy, backtracking and hybrid on every session; CSV of search steps and time side by side (advanced mode) |
| `GET /api/benchmarks` | DAA + Computer Architecture experiments (run once, cached) |

Notes: state is kept in memory (one `AppState` object), so it resets when the server restarts. Uploads are capped at 5 MB per file.
If a `frontend/` folder exists, `app.py` serves it at `/`; otherwise `/` redirects to `/docs`.
Bad files return HTTP 400 with the backend's own readable message. Tests: `tests/test_api.py` (FastAPI `TestClient`).

## Rooms and timetable (in the app)

The app starts with built-in **rooms B-002 to B-005** and the **printed timetable** (12 exam days, 36 papers), so only the
student list has to be uploaded. Both are edited on their own tabs and saved with one button; saving drops the old
seating plan because it no longer matches.
* **Rooms tab**: click a seat to switch it on/off (drag to paint several, click a row/column number for a whole line),
  `+ Row` / `- Row` / `+ Column` / `- Column`, rename, "Use this room", add or delete rooms. Every built-in room is
  labelled **Provisional** (also on the seating plan and in the text download) until you tick "Layout checked against
  the real room". B-002 to B-004: 6 x 9, three blocks (benches of 2 / 3 / 2), aisles and the back row of the middle block
  have no seat, 39 seats. The earlier description (8 outer benches, 6 middle) differs - noted in each room's Notes box.
  B-005 is a guess (5 x 10, 38 seats: two rows of 2-seat benches plus single flip-table chairs).
* **Timetable tab**: editable table (date picker, time, paper code, paper name, group). Codes are cleaned on save
  (`ds6a - 201`, `DS6A – 201` -> `DS6A-201`). Papers are told apart by code; the same paper listed by two groups on the
  same day (DS6A-603) is one paper. Not listed on purpose: DS5A-623 (MBA does not write it) and Engineering Economics.
* Uploading a rooms or schedule file on the Data tab (optional) replaces the matching tab's table.
* `data/sample/students_placeholder.csv` is a test aid: 231 placeholder students for the six groups, each with the papers
  of their group (MBA without DS5A-623). Step 6 will generate these placeholders inside the app instead.

## Normal view and advanced mode

Open `http://127.0.0.1:8000` for the teacher view: load files, choose how students may sit next to each other,
generate, download. The strategy is always hybrid.
Open `http://127.0.0.1:8000/?advanced=1` for the evaluation view: strategy dropdown, "solved by ... (N search steps)"
per room, demo data, the Experiments tab and **Compare strategies (CSV)** (`strategy_comparison.csv`, one row per exam
session plus a TOTAL row; timing is the fastest of 3 runs). On easy data the three strategies are close; the gap shows
when rooms are tight.

## Input files (CSV; Excel exports work - delimiter, BOM and header spelling are detected)

Only the students file is needed; the other two are optional because rooms and the timetable live in the app.

**students.csv** - one row per (student, course they are enrolled in). A student with 5 papers has 5 rows.
`Roll No, Student Name, Course Code [, Course Name]`

**rooms.csv** - one row per room. Seat/row numbers are 1-based, row 1 = front.
`Room ID, Name, Rows, Cols, Blocked Seats, Layout, Available`
* `Blocked Seats`: `row-col` items separated by `;` e.g. `1-1;5-6` (broken desk, pillar, aisle)
* `Layout` (optional, replaces rows/cols/blocked): rows separated by `/`; `1` = seat, `0` or `X` = no seat.
  `11111/11011/11111` is a 3x5 room with the middle seat of row 2 missing. Short rows are padded with "no seat".
* `Available`: yes/no (rooms under repair can stay in the file)

**schedule.csv** - one row per paper. Rows with the same Date + Slot are written together.
`Date, Slot, Course Code [, Course Name] [, Group]`

If a header is unusual, pass `column_maps` to `load_all(...)`, e.g.
`{"students": {"roll_no": "ID Card", "course": "Paper"}}`.
Course codes and roll numbers ignore case and inner spaces (`cs 201` = `CS201`).
Problems are reported as warnings (duplicate rows, a student with two papers in one slot, courses missing from the
schedule...) instead of crashing; a session that cannot be seated is reported with the reason, and the rest still run.

## Where each subject lives

| Subject | Files | What to show |
|---|---|---|
| DAA | `strategies.py`, `feasibility.py`, `allocator.py` | Greedy with max-heap O(N log K); backtracking with pruning; hybrid; feasibility via bipartite matching (Konig); balanced room allocation; `benchmarks.py` A, B |
| OOP | `models.py`, `rules.py`, `strategies.py`, `errors.py`, `planner.py` | Strategy pattern (`SeatingStrategy`), polymorphic `AdjacencyRule`, factories `get_rule`/`get_strategy`, encapsulated `Room`/`Seat`, exception hierarchy |
| Computer Architecture | `seat_encoding.py`, `bitops.py`, `feasibility.parity`, `benchmarks.py` C, D | 32-bit packed seat word (shifts/masks); `mask & (mask << 1)` row check; `(row ^ col) & 1` checkerboard parity (XOR gate); flat vs nested memory layout and row/column-major traversal |

## Pipeline

load CSVs -> for each session: collect students -> pick rooms (largest first) -> spread students across rooms
-> feasibility check per room -> solve each room (greedy, else backtracking) -> verify -> export.
If the tightest set of rooms cannot be solved, one more room is added and it retries.

## Notes for the viva

* Greedy is O(N log K) but can dead-end; backtracking is complete but exponential in the worst case, so it is only the fallback.
* A room can hold at most `capacity - max matching` students of one course under the four-way rule (grid graph is bipartite).
* Seats may be left empty when the room has spare seats - sometimes that is the only valid arrangement.
* Python hides most cache effects; the memory-layout benchmark shows the direction, not C-level numbers.

## PDF and Excel input (step 5)

The Data tab accepts **PDF, CSV or Excel** and routes by file type. `pdf_import.py` (API layer only, uses `pdfplumber` and
`openpyxl`; `seating/` is still standard library only) only *reads*; nothing is loaded until the teacher confirms.

* **Student lists (PDF, one per batch, several can be chosen at once).** The parser finds every roll number
  (`DS6A-2501` style) and takes the name after it. Handled: merged rows, glued serial numbers, wrapped names,
  blank enrolment numbers, fee/category/gender columns, `OLD STUDENT`. Lines with no roll number (cancelled /
  transferred rows) are not loaded and are listed in the preview; a row marked CANCELLED/TFR or a repeated roll
  number arrives unticked. The preview table lets the teacher fix names/rolls, untick rows and choose the group
  (suggested from the roll prefix: DS5A-25 MBA BA sem 3, DS5B-25 MSc DSA sem 3, DS6A-25 M.Tech sem 3, DS6A-24 M.Tech sem 5).
  Names are display only. The parser reads only the four real lists reliably; a new layout may need fixing in the preview.
* **Cohort rule** (`seating/cohorts.py`): every student of a group writes every paper the timetable lists for that
  group. The two exceptions (MBA BA: not DS5A-623; M.Tech sem 3: only Numerical Methods) hold because those papers are
  not in the timetable. Editing the timetable changes the students' papers automatically.
* **Rooms / schedule PDFs**: only if the PDF has a text layer and a real table (header row such as `Room ID, Rows, Cols`
  or `DATE, TIME, COURSE CODE, SUBJECT`). Dates `23-11-2026` become `2026-11-23`; blank merged date/time cells are filled
  from the row above. They also go through a preview; confirming uses the normal Rooms / Timetable tabs, where they can be fixed.
* **Scanned PDFs** (no text layer; no OCR here) are refused with: "This PDF has no readable text ... Use the timetable
  table in the app or upload a CSV." (wording differs slightly for students and rooms).
* **Excel**: `.xlsx` (first sheet) is converted to CSV text. A PDF sent straight to `POST /api/data` is refused.
* Student source is either CSV/Excel rows or PDF lists: uploading a CSV drops PDF lists, confirming a PDF list drops a CSV.
* Sem 7 and sem 9 have no lists yet: their papers show "no students" warnings and those days are empty until step 6
  adds marked placeholders.
* Sample files for tests: `data/pdf_samples/` (the four lists, the scanned timetable, two small text-PDF tables).

## Light / dark theme (step 7)
* The toggle is at the top right of the top bar. Default is dark; the choice is kept in the browser (localStorage) and applied by a tiny script in `<head>` before the page paints.
* All colours are CSS variables in `frontend/styles.css`: the dark values are in `:root`, the light values in `:root[data-theme="light"]`. `--accent` is the fill colour (buttons, active tab); `--accent-text` is the darker amber used for text and small details in the light theme.

## Dummy student lists (M.Tech sem 7 and sem 9)
* `data/pdf_samples/DUMMY_MTECH_AIDS_2023-2028_7TH_SEM.pdf` (55 students, DS6A-2301...) and `DUMMY_MTECH_AIDS_2022-2027_9TH_SEM.pdf` (45 students, DS6A-2201...) are **made-up names**, not real students. Load them on the Data tab like any PDF (they are suggested as "M.Tech sem 7" / "M.Tech sem 9").
* `make_dummy_lists.py` makes them again (needs `pip install reportlab`; seeded, so the result is the same each time). Change `count` there for another batch size.
* To use the real lists later: on the Data tab remove the dummy list with the x on its "Student lists loaded" chip, then load the real PDF for that group.

