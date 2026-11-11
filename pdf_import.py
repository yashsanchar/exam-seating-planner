"""Reading PDFs and Excel files for the Data tab (API layer only - the `seating` package never sees a PDF).

Everything here only PARSES and returns a preview. Nothing is loaded into the app until the teacher
checks the preview and confirms (that step lives in app.py).

  * student lists  -> parse_student_pdf(): finds every roll number (like DS6A-2501) in the text and takes the
                      name that follows it. Merged rows, split names, blank enrolment numbers, fee/category
                      columns and trailing "cancelled / transferred" rows are handled; anything doubtful is
                      flagged in the preview instead of being guessed silently.
  * rooms/schedule -> pdf_table_to_csv(): only for PDFs that have a text layer AND a real table. The table is
                      turned into CSV text and read by the existing CSV loaders.
  * Excel (.xlsx)  -> excel_to_csv(): first sheet becomes CSV text.
  * scanned PDFs   -> no text layer, no OCR in this project: PdfUnreadable with a plain-language message.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:                                   # API-layer dependency, listed in requirements.txt
    import pdfplumber
except ImportError:                    # pragma: no cover - only when requirements were not installed
    pdfplumber = None

try:
    import openpyxl
except ImportError:                    # pragma: no cover
    openpyxl = None

MIN_CHARS_PER_PAGE = 20                # fewer characters than this on average = scanned / no text layer

# Message shown for a PDF with no readable text, by kind of file.
UNREADABLE = {
    "students": "This PDF has no readable text (it looks like a scan or photo). Upload the student list as a CSV file instead.",
    "rooms": "This PDF has no readable text (it looks like a scan or photo). Use the Rooms tab to set up the rooms, or upload a CSV.",
    "schedule": "This PDF has no readable text (it looks like a scan or photo). Use the timetable table in the app or upload a CSV.",
}


class PdfProblem(Exception):
    """A PDF/Excel file that cannot be used. The message is written for the teacher and shown as is."""


# --------------------------------------------------------------------------- opening a PDF
def _pages_text(path: Path, kind: str) -> List[str]:
    if pdfplumber is None:
        raise PdfProblem("PDF support is not installed. Run: python -m pip install -r requirements.txt")
    try:
        with pdfplumber.open(str(path)) as pdf:
            texts = [(page.extract_text() or "") for page in pdf.pages]
    except Exception:                  # damaged file, password, not a PDF at all ...
        raise PdfProblem("This file could not be opened as a PDF. Check that it is not damaged or password-protected.")
    if not texts:
        raise PdfProblem("This PDF has no pages.")
    if sum(len(t.strip()) for t in texts) < MIN_CHARS_PER_PAGE * len(texts):
        raise PdfProblem(UNREADABLE.get(kind, UNREADABLE["students"]))
    return texts


# --------------------------------------------------------------------------- student lists
# roll number such as DS6A-2501 / DS5B-2511 (letters, digit, letter, dash, 4 digits). Dashes may be en/em dashes,
# spaces around them are allowed. The lookbehind lets "5DS6A-2525" (serial glued to the roll) still match.
ROLL = re.compile(r"(?<![A-Za-z])([A-Z]{2}\d[A-Z])\s*[-\u2010-\u2015\u2212]\s*(\d{4})(?!\d)")

# columns that sit between the roll number and the name in these lists and must not become part of the name
CATEGORY_WORDS = {"M", "F", "Y", "N", "UR", "URO", "URF", "OBC", "OBCO", "OBCF", "OBF", "OBO", "NCL", "SC", "SCO", "SCF",
                  "ST", "STO", "STF", "EWS", "EW", "PWD", "JKM", "GEN"}
CODE_LIKE = re.compile(r"^(?:\d+|[A-Z]{0,4}\d+[A-Z]*)$", re.I)   # fees, enrolment / application numbers: any token with digits
STATUS = re.compile(r"\b(CANCEL+ED|TFR|TRANSFER+ED|WITHDRAWN|LEFT)\b", re.I)
OLD_STUDENT = re.compile(r"\bOLD\s+STUDENT\b", re.I)

# roll prefix -> the timetable group it normally belongs to (the teacher can change it in the preview)
PREFIX_TO_GROUP = {"DS5A-25": "MBA BA sem 3", "DS5B-25": "MSc DSA sem 3", "DS6A-25": "M.Tech sem 3",
                   "DS6A-24": "M.Tech sem 5", "DS6A-23": "M.Tech sem 7", "DS6A-22": "M.Tech sem 9"}


@dataclass
class StudentPreview:
    rows: List[dict] = field(default_factory=list)       # {roll_no, name, include, note}
    ignored: List[str] = field(default_factory=list)     # text lines that had no roll number (not loaded)
    warnings: List[str] = field(default_factory=list)
    suggested_group: str = ""
    pages: int = 0

    def to_dict(self) -> dict:
        return {"kind": "students", "rows": self.rows, "ignored": self.ignored, "warnings": self.warnings,
                "suggested_group": self.suggested_group, "pages": self.pages,
                "included": sum(1 for r in self.rows if r["include"])}


def norm_roll(prefix: str, number: str) -> str:
    return f"{prefix.upper()}-{number}"


def clean_person_name(tokens: List[str]) -> str:
    """Drop the columns around the name (leading category/number columns, trailing digits and category words)."""
    toks = [t for t in tokens if t]
    while toks and (CODE_LIKE.match(toks[0]) or toks[0].upper() in CATEGORY_WORDS):
        toks.pop(0)
    while toks and (CODE_LIKE.match(toks[-1]) or toks[-1].upper() in CATEGORY_WORDS):
        toks.pop()
    name = " ".join(toks)
    name = re.sub(r"(?<=[A-Za-z])\d{1,3}$", "", name).strip()          # "SIRWANI18" -> next row's serial number glued on
    return re.sub(r"\s+", " ", name).upper()


def parse_student_text(pages: List[str]) -> StudentPreview:
    """Pure text -> preview. (Split from the PDF reading so it can be tested without a PDF.)"""
    prev = StudentPreview(pages=len(pages))
    # a roll number starts a record; the record runs to the next roll number
    first_line_seen = False
    for text in pages:
        for line in text.splitlines():
            if ROLL.search(line):
                first_line_seen = True
    if not first_line_seen:
        raise PdfProblem("No roll numbers like DS6A-2501 were found in this PDF. If your roll numbers look different, "
                         "upload the student list as a CSV file instead.")

    # work line by line, but a line can hold several records ("... SIRWANI18 DS6A-2418 ...") or a record can
    # continue on the next line (name wrapped), so join the whole document and split at roll numbers.
    full = "\n".join(pages)
    matches = list(ROLL.finditer(full))
    head = full[:matches[0].start()]
    seen: Dict[str, int] = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        tail = full[m.end():end]
        roll = norm_roll(m.group(1), m.group(2))
        # the rest of this line, plus following lines only while they look like a wrapped name. A line that starts
        # with a number is the next row (serial number) or a trailing cancelled/transferred row: stop there.
        tail_lines = tail.splitlines()
        keep = tail_lines[:1]
        for ln in tail_lines[1:]:
            if not ln.strip() or re.match(r"^\s*\d", ln):
                break
            keep.append(ln)
        record_text = " ".join(keep)
        status = STATUS.search(record_text)
        record_text = OLD_STUDENT.sub(" ", record_text)
        # a trailing "<digits>" belongs to the next row (serial) - removed by clean_person_name via CODE_LIKE
        tokens = re.split(r"\s+", record_text.strip())
        name = clean_person_name(tokens)
        note = ""
        include = True
        if status:
            include, note = False, f"marked '{status.group(0).upper()}' in the list - not included"
            name = clean_person_name([t for t in tokens if not STATUS.fullmatch(t)][: max(1, len(tokens))])
        if not name:
            note = (note + "; " if note else "") + "no name found - type it in"
        elif len(name.split()) > 1 and len(name.split()[-1]) <= 1:
            note = (note + "; " if note else "") + "check the name (ends with a single letter)"
        if roll in seen:
            note = (note + "; " if note else "") + f"roll number repeated (also row {seen[roll]})"
            include = False
        seen[roll] = len(prev.rows) + 1
        prev.rows.append({"roll_no": roll, "name": name, "include": include, "note": note})

    # lines before the first roll are the title; lines in the text with no roll number are reported as not loaded
    roll_lines = set()
    for text in pages:
        for line in text.splitlines():
            if not ROLL.search(line):
                s = line.strip()
                if s:
                    roll_lines.add(s)
    # only report lines that look like data rows (start with a serial number) - titles and headers are not data
    prev.ignored = [s for s in sorted(roll_lines, key=lambda s: full.find(s)) if re.match(r"^\d{1,3}\s+\S", s)]
    prev.ignored = [(s if len(s) <= 90 else s[:87] + "...") for s in prev.ignored]

    # whole-list checks
    included = [r for r in prev.rows if r["include"]]
    if prev.ignored:
        prev.warnings.append(f"{len(prev.ignored)} line(s) without a roll number were not loaded (listed below). "
                             "These are usually cancelled or transferred students.")
    nums = sorted(int(r["roll_no"][-4:]) for r in included)
    if nums:
        gaps = [n for n in range(nums[0], nums[-1] + 1) if n not in set(nums)]
        if gaps:
            prev.warnings.append("Roll numbers missing from the sequence: " + ", ".join(str(g) for g in gaps[:10]) +
                                 ". Check that no student is missing.")
    prefixes = {r["roll_no"][:7] for r in included}
    if len(prefixes) > 1:
        prev.warnings.append("This list mixes roll numbers from different batches (" + ", ".join(sorted(prefixes)) + ").")
    elif prefixes:
        prev.suggested_group = PREFIX_TO_GROUP.get(next(iter(prefixes)), "")
    _ = head
    return prev


def parse_student_pdf(path) -> StudentPreview:
    return parse_student_text(_pages_text(Path(path), "students"))


# --------------------------------------------------------------------------- rooms / schedule tables in a PDF
_DATE_DMY = re.compile(r"^(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{4})$")


def _to_iso(text: str) -> str:
    m = _DATE_DMY.match(text.strip())
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else text.strip()


def _cell(x) -> str:
    return re.sub(r"\s+", " ", (x or "")).strip()


def pdf_table_to_csv(path, kind: str) -> str:
    """Text-layer PDF with a real table -> CSV text for load_rooms / load_schedule_rows.
    kind is 'rooms' or 'schedule'. Dates like 23-11-2026 are turned into 2026-11-23 and blank date/time cells
    (merged cells) are filled from the row above."""
    _pages_text(Path(path), kind)                                  # raises the 'no readable text' message for scans
    rows: List[List[str]] = []
    try:
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    for raw in table:
                        row = [_cell(c) for c in raw]
                        if any(row):
                            rows.append(row)
    except Exception:
        raise PdfProblem("This file could not be opened as a PDF. Check that it is not damaged or password-protected.")
    if len(rows) < 2:
        raise PdfProblem("No table was found in this PDF. Upload a CSV file instead"
                         + (", or use the Rooms tab." if kind == "rooms" else ", or use the Timetable tab."))
    header, body = rows[0], [r for r in rows[1:] if r != rows[0]]   # repeated header rows on later pages are dropped
    heads = [re.sub(r"[^a-z0-9]", "", h.lower()) for h in header]
    if kind == "schedule":
        # the printed timetable calls the paper name "SUBJECT"; the loader wants a name column for it
        if "subject" in heads and any(h in heads for h in ("coursecode", "papercode", "code")):
            header[heads.index("subject")] = "Course Name"
        date_i = next((i for i, h in enumerate(heads) if h in ("date", "examdate")), None)
        fill = [i for i, h in enumerate(heads) if h in ("date", "examdate", "day", "time", "slot", "timeslot")]
        last: Dict[int, str] = {}
        for r in body:
            r += [""] * (len(header) - len(r))
            for i in fill:
                if r[i]:
                    last[i] = r[i]
                elif i in last:
                    r[i] = last[i]
            if date_i is not None:
                r[date_i] = _to_iso(r[date_i])
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    for r in body:
        w.writerow(r[:len(header)] + [""] * (len(header) - len(r)))
    return out.getvalue()


# --------------------------------------------------------------------------- Excel
def excel_to_csv(path) -> str:
    """First sheet of an .xlsx file as CSV text."""
    if openpyxl is None:
        raise PdfProblem("Excel support is not installed. Run: python -m pip install -r requirements.txt, "
                         "or save the sheet as CSV.")
    try:
        wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        out = io.StringIO()
        w = csv.writer(out)
        for row in ws.iter_rows(values_only=True):
            cells = ["" if c is None else (c.strftime("%Y-%m-%d") if hasattr(c, "strftime") else str(c)) for c in row]
            if any(c.strip() for c in cells):
                w.writerow(cells)
        wb.close()
    except Exception:
        raise PdfProblem("This Excel file could not be read. Save it as .xlsx or CSV and try again.")
    text = out.getvalue()
    if not text.strip():
        raise PdfProblem("The first sheet of this Excel file is empty.")
    return text
