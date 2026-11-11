"""Makes the two DUMMY student-list PDFs (M.Tech AI&DS sem 7 and sem 9) in data/pdf_samples/.

Why: the real lists for these two batches are not available yet, so the app used placeholder students
("Student 1" ...). These PDFs have realistic made-up names and roll numbers, in the same layout as the real
lists, so they go through the normal "Check the student list" screen like any real PDF.

How it works (simple version):
  1. Take pools of common Indian first names and surnames.
  2. A SEEDED random generator picks names (same seed = the same list every time you run this).
  3. Names that already exist in the real lists (the other PDFs in data/pdf_samples) are skipped,
     so no dummy student is a real student.
  4. The names are sorted A-Z (like the real lists) and numbered DS6A-2301, DS6A-2302 ... (sem 7)
     and DS6A-2201, DS6A-2202 ... (sem 9). The roll prefix is what the app uses to suggest the group.
  5. The PDF copies only the LAYOUT of the real lists. Enrolment, fee and paid columns are left empty on purpose:
     no fee, phone, e-mail or any other real detail is ever written.

Run (only needed to make the files again; the PDFs are already in the project):
    python -m pip install reportlab
    python make_dummy_lists.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

import pdf_import

BASE = Path(__file__).parent
OUT = BASE / "data" / "pdf_samples"

# One entry per dummy list. COUNT is the batch size: change it here to get a bigger or smaller list.
BATCHES = [
    {"file": "DUMMY_MTECH_AIDS_2023-2028_7TH_SEM.pdf", "years": "2023-2028", "sem": 7, "prefix": "DS6A-23", "count": 55, "seed": 2023},
    {"file": "DUMMY_MTECH_AIDS_2022-2027_9TH_SEM.pdf", "years": "2022-2027", "sem": 9, "prefix": "DS6A-22", "count": 45, "seed": 2022},
]

# ---------------------------------------------------------------- name pools (common Indian names)
MALE = """AARAV ADITYA AKASH AMAN AMIT ANIKET ANKIT ANKUSH ARNAV ARYAN ASHISH ATHARV AYUSH BHAVYA CHIRAG DAKSH DEEPAK DEV DHRUV DIVYANSH
FAIZAN GAURAV HARSH HARSHIT HRITHIK ISHAAN JAY KARAN KARTIK KUSHAL LAKSHYA MANAN MAYANK MOHIT NAKUL NIKHIL NITESH ONKAR PARTH PIYUSH PRANAV
PRATEEK RAGHAV RAHUL RAJAT RAJEEV REHAN RISHABH ROHAN SAHIL SAMARTH SANDEEP SHIVAM SIDDHARTH SOURABH SUMIT SURYA TANMAY TUSHAR UDAY
UTKARSH VAIBHAV VANSH VEDANT VIKAS VIKRAM VINAY VIPUL YASH YUVRAJ ZAID DANISH IMRAN KABIR MANISH NAMAN PRAKHAR SAURABH""".split()
FEMALE = """AANYA AARUSHI ADITI AISHWARYA AKANKSHA ANANYA ANJALI ANUSHKA ARPITA AVNI BHAVNA CHARVI DIKSHA DIVYA GARIMA GAYATRI HARSHITA ISHITA
JAHNAVI JIYA KAJAL KAVYA KHUSHI KIRTI KOMAL KRITI LAVANYA MAHI MANYA MEGHA MITALI MUSKAN NAMRATA NANDINI NEHA NIDHI NISHA PALAK POOJA PRACHI
PRIYA RADHIKA RASHI RIDHI RIYA RUCHI SAKSHI SANA SANYA SAPNA SHREYA SHRUTI SIMRAN SMRITI SNEHA SONAL SRISHTI SURBHI TANVI TANYA TRISHA UMA
VAIDEHI VANI VEDIKA VIDHI YASHIKA ZOYA AALIYA SARA NAZIA RUKSAR""".split()
SURNAMES = """SHARMA VERMA GUPTA JAIN JOSHI MISHRA TIWARI PANDEY DUBEY YADAV AGRAWAL SAXENA KULKARNI DESHMUKH IYER NAIR REDDY RAO SINGH THAKUR
MEHTA SHAH BHATT TRIVEDI PATHAK SHUKLA DWIVEDI CHATURVEDI KUSHWAHA PARMAR RAJPUT BHARGAVA VYAS SISODIYA GEHLOT NAGAR SEN DAS BANERJEE
CHATTERJEE MUKHERJEE ROY GHOSH BOSE KAPOOR MALHOTRA KHANNA ARORA BANSAL GOYAL MITTAL GARG SETHI BHATIA GILL SANDHU CHOUDHARY CHOUHAN
SOLANKI MALVIYA RATHORE TOMAR JADHAV PAWAR SHINDE GAIKWAD KALE MORE NAIK PATIL RAUT BHOSALE KHAN ANSARI QURESHI SHEIKH SIDDIQUI PATHAN
SOMANI BAGHEL DHAKAD SONI SAHU TIWARY SHRIVASTAV UPADHYAY AWASTHI SINHA JHA CHOWDHARY PILLAI MENON KURUP HEGDE SHETTY PRABHU""".split()
MIDDLE_M, MIDDLE_F = "KUMAR", "KUMARI"          # "ARJUN KUMAR PATEL" style, as in the real lists
# words the PDF reader treats as list columns or status words: never used as a name part
RESERVED = {"M", "F", "Y", "N", "UR", "OBC", "SC", "ST", "EWS", "PWD", "GEN", "LEFT", "TFR", "CANCELLED"}


def real_names() -> tuple[set[str], set[tuple[str, str]]]:
    """Every student name in the REAL lists (all other student PDFs in data/pdf_samples) - the dummy names must avoid them."""
    full, pairs = set(), set()
    for pdf in sorted(OUT.glob("*.pdf")):
        if pdf.name.startswith("DUMMY"):
            continue
        try:
            preview = pdf_import.parse_student_pdf(pdf)
        except pdf_import.PdfProblem:        # rooms / timetable PDFs have no roll numbers: skip them
            continue
        for row in preview.rows:
            parts = row["name"].split()
            if parts:
                full.add(row["name"])
                pairs.add((parts[0], parts[-1]))
    return full, pairs


def make_names(count: int, seed: int, taken_full: set, taken_pairs: set) -> list[str]:
    """`count` different made-up names, sorted A-Z. Updates the taken sets so the next list cannot repeat them."""
    rng = random.Random(seed)                 # seeded: the same seed always gives the same names
    names: list[str] = []
    while len(names) < count:
        female = rng.random() < 0.45
        first = rng.choice(FEMALE if female else MALE)
        last = rng.choice(SURNAMES)
        middle = ""
        if rng.random() < (0.12 if female else 0.25):
            middle = MIDDLE_F if female else MIDDLE_M
        if {first, last} & RESERVED or first == last:
            continue
        name = " ".join(p for p in (first, middle, last) if p)
        if name in taken_full or (first, last) in taken_pairs:
            continue
        taken_full.add(name)
        taken_pairs.add((first, last))
        names.append(name)
    return sorted(names)


# ---------------------------------------------------------------- the PDF (same layout as the real lists)
PAGE = landscape(letter)                       # 792 x 612 pt, like the real lists
COLS = [29, 81, 109, 253, 84, 131]             # S.NO | ROLL NO | Enroll_no | total_fee | paid_status | Name (same proportions)
HEADER = ["S.NO.", "ROLL NO.", "Enroll_no", "total_fee", "paid_status", "Name"]
LEFT, TOP, ROW_H = 17.5, 62.5, 18
FIRST_PAGE_ROWS, NEXT_PAGE_ROWS = 24, 26       # the real list fits 24 students under the title on page 1, then 26 per page


def draw_table(c: canvas.Canvas, data: list, title_row: bool) -> None:
    style = [("GRID", (0, 0), (-1, -1), 0.7, colors.black), ("FONTNAME", (0, 0), (-1, -1), "Helvetica"), ("FONTSIZE", (0, 0), (-1, -1), 6.5),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "LEFT"), ("ALIGN", (1, 0), (1, -1), "CENTER")]
    if title_row:                              # merged title row, then the header row, like the real list
        style += [("SPAN", (0, 0), (-1, 0)), ("ALIGN", (0, 0), (-1, 1), "CENTER"), ("FONTNAME", (0, 0), (-1, 1), "Helvetica-Bold")]
    table = Table(data, colWidths=COLS, rowHeights=ROW_H)
    table.setStyle(TableStyle(style))
    _w, h = table.wrap(0, 0)
    table.drawOn(c, LEFT, PAGE[1] - TOP - h)


def write_pdf(path: Path, title: str, rolls: list[str], names: list[str]) -> None:
    rows = [["%d" % (i + 1), roll, "", "", "", name] for i, (roll, name) in enumerate(zip(rolls, names))]   # empty enrolment / fee / paid cells
    pages = [rows[:FIRST_PAGE_ROWS]]
    rest = rows[FIRST_PAGE_ROWS:]
    pages += [rest[i:i + NEXT_PAGE_ROWS] for i in range(0, len(rest), NEXT_PAGE_ROWS)]
    c = canvas.Canvas(str(path), pagesize=PAGE)
    c.setTitle(title)
    c.setAuthor("Exam Seating Planner (dummy data generator)")
    for n, chunk in enumerate(pages):
        if n == 0:
            draw_table(c, [[title] + [""] * 5, HEADER] + chunk, title_row=True)
        else:
            draw_table(c, chunk, title_row=False)
        c.showPage()
    c.save()


def main() -> int:
    taken_full, taken_pairs = real_names()
    if not taken_full:
        print("Warning: no real lists found in data/pdf_samples, so the 'no real names' check could not be done.")
    for b in BATCHES:
        names = make_names(b["count"], b["seed"], taken_full, taken_pairs)
        rolls = ["%s%02d" % (b["prefix"], i + 1) for i in range(len(names))]
        title = ("SCHOOL OF DATA SCIENCE & FORECASTING LIST OF M.TECH AI&DS %s %d SEMESTER (DUMMY DATA - NOT REAL STUDENTS)" % (b["years"], b["sem"]))
        write_pdf(OUT / b["file"], title, rolls, names)
        print("Wrote %s: %d students, %s ... %s" % (b["file"], len(names), rolls[0], rolls[-1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
