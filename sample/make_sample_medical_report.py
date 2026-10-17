"""Generate sample/sample_medical_report.pdf.

A tiny, dependency-free PDF writer so the sample can be regenerated without
installing reportlab or fpdf. Run it from the project root:

    .\\.venv\\Scripts\\python.exe sample\\make_sample_medical_report.py

Everything in the report is invented: no real patient, hospital or clinician.
"""

from __future__ import annotations

from pathlib import Path

PAGE_W, PAGE_H = 612, 792  # US Letter, points
MARGIN = 54
BOTTOM = MARGIN

FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Courier"}

# --------------------------------------------------------------------------- #
# Report content
# --------------------------------------------------------------------------- #
HOSPITAL = "RIVERSIDE GENERAL HOSPITAL"
DEPARTMENT = "Department of Internal Medicine"
TITLE = "COMPREHENSIVE LABORATORY AND CLINICAL REPORT"

PATIENT = [
    ("Patient name", "Meera R. Sharma"),
    ("Medical record no.", "MRN-40918-227"),
    ("Age / sex", "54 years / Female"),
    ("Date of birth", "1971-03-18"),
    ("Ward / bed", "General Medicine / 4-West, Bed 12"),
    ("Attending physician", "Dr. Anil K. Verma, MD (Internal Medicine)"),
    ("Referring clinician", "Dr. Sneha Iyer, MBBS (City Family Clinic)"),
    ("Specimen collected", "2026-02-11, 07:15"),
    ("Report issued", "2026-02-12, 16:40"),
]

# label, value, unit, reference range, flag
VITALS = [
    ("Blood pressure", "148/92", "mmHg", "< 130/85", "HIGH"),
    ("Heart rate", "88", "bpm", "60-100", "normal"),
    ("Respiratory rate", "18", "/min", "12-20", "normal"),
    ("Temperature", "37.1", "deg C", "36.1-37.2", "normal"),
    ("SpO2 (room air)", "97", "%", "95-100", "normal"),
    ("Height / weight", "158 / 74.5", "cm / kg", "-", "BMI 29.8"),
]

LABS = [
    ("Haemoglobin", "11.2", "g/dL", "12.0-15.5", "LOW"),
    ("White blood cells", "9,400", "/uL", "4,000-11,000", "normal"),
    ("Platelet count", "2.62", "lakh/uL", "1.5-4.5", "normal"),
    ("Fasting plasma glucose", "138", "mg/dL", "70-100", "HIGH"),
    ("HbA1c", "7.4", "%", "< 5.7", "HIGH"),
    ("Total cholesterol", "214", "mg/dL", "< 200", "HIGH"),
    ("LDL cholesterol", "141", "mg/dL", "< 100", "HIGH"),
    ("HDL cholesterol", "44", "mg/dL", "> 50", "LOW"),
    ("Triglycerides", "186", "mg/dL", "< 150", "HIGH"),
    ("Serum creatinine", "0.9", "mg/dL", "0.6-1.1", "normal"),
    ("Blood urea nitrogen", "16", "mg/dL", "7-20", "normal"),
    ("AST (SGOT)", "31", "U/L", "10-40", "normal"),
    ("ALT (SGPT)", "38", "U/L", "7-56", "normal"),
    ("TSH", "2.8", "uIU/mL", "0.4-4.0", "normal"),
]

CHIEF = (
    "54-year-old woman with a known history of type 2 diabetes mellitus presents "
    "with fatigue, increased thirst and intermittent blurred vision over the past "
    "six weeks. No chest pain, no shortness of breath, no fever and no weight loss "
    "reported."
)

HISTORY = (
    "Diagnosed with type 2 diabetes mellitus eight years ago and on metformin "
    "since. Hypertension diagnosed three years ago, currently treated with "
    "amlodipine. Family history of ischaemic heart disease in a first-degree "
    "relative. Non-smoker, occasional social alcohol. No known drug allergies. "
    "Recent home glucose readings have been running high before meals."
)

ASSESSMENT = [
    ("1. Type 2 diabetes mellitus, poorly controlled.",
     "HbA1c of 7.4% is above the individualised target of below 7.0%, and fasting "
     "plasma glucose is 138 mg/dL. The blurred vision is consistent with osmotic "
     "lens swelling from hyperglycaemia and is expected to improve as glucose "
     "control improves."),
    ("2. Essential hypertension, uncontrolled.",
     "Blood pressure of 148/92 mmHg is above the target of below 130/85 mmHg for "
     "a patient with diabetes. Home monitoring twice daily has been advised."),
    ("3. Mixed dyslipidaemia.",
     "LDL cholesterol of 141 mg/dL and triglycerides of 186 mg/dL raise "
     "cardiovascular risk. Statin therapy has been discussed and is offered."),
    ("4. Overweight (BMI 29.8).",
     "Dietary counselling and a graded exercise plan of 30 minutes of brisk "
     "walking five days a week have been arranged."),
]

MEDICATIONS = [
    "Metformin 500 mg - one tablet twice daily after meals.",
    "Amlodipine 5 mg - one tablet once daily in the morning.",
    "Atorvastatin 20 mg - one tablet at bedtime (new, to be discussed at review).",
    "Aspirin 75 mg - once daily after food (to be reviewed at follow-up).",
]

FOLLOWUP = [
    "Review in the outpatient clinic after four weeks with a repeat HbA1c.",
    "Self-monitor fasting and post-meal glucose daily; bring the logbook.",
    "Dietary advice from the hospital dietitian, appointment already booked.",
    "Return earlier if there is chest pain, breathlessness, dizziness or "
    "fainting.",
]

CLOSING = (
    "This report is a fictional sample produced for a software demonstration. "
    "The patient, hospital, clinicians, values and dates are all invented."
)

SIGNATURE = [
    "Dr. Anil K. Verma, MD (Internal Medicine)",
    "Consultant Physician, Riverside General Hospital",
    "Electronically signed: 2026-02-12 16:40 IST",
]


# --------------------------------------------------------------------------- #
# Minimal PDF writer
# --------------------------------------------------------------------------- #
def esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class Page:
    """Collects text-showing operations for one page."""

    def __init__(self) -> None:
        self.y = PAGE_H - MARGIN
        self.ops: list[str] = []

    def text(self, x: float, font: str, size: float, value: str) -> None:
        self.ops.append(
            f"BT /{font} {size:g} Tf 1 0 0 1 {x:.2f} {self.y:.2f} Tm "
            f"({esc(value)}) Tj ET"
        )

    def rule(self, width: float = 0.6, gray: float = 0.75) -> None:
        self.ops.append(
            f"{gray:g} {gray:g} {gray:g} RG {width:g} w "
            f"{MARGIN} {self.y:.2f} m {MARGIN + width_page():.2f} {self.y:.2f} l S"
        )

    def stream(self) -> str:
        return "\n".join(self.ops)


def width_page() -> float:
    return PAGE_W - 2 * MARGIN


class Doc:
    """Breaks a list of positioned lines into pages."""

    def __init__(self) -> None:
        self.pages: list[Page] = [Page()]

    @property
    def page(self) -> Page:
        return self.pages[-1]

    def need(self, height: float) -> None:
        if self.page.y - height < BOTTOM:
            self.pages.append(Page())

    def line(
        self,
        text: str,
        font: str = "F1",
        size: float = 9.5,
        indent: float = 0.0,
        leading: float | None = None,
        before: float = 0.0,
        after: float = 2.0,
    ) -> None:
        leading = leading if leading is not None else size + 2.5
        self.need(leading)
        self.page.y -= before
        self.page.text(MARGIN + indent, font, size, text)
        self.page.y -= leading - before + after

    def blank(self, height: float = 8.0) -> None:
        self.page.y -= height

    def heading(self, text: str) -> None:
        self.blank(4)
        self.need(24)
        self.line(text, font="F2", size=10.5, leading=15, after=1)
        self.page.y -= 1
        self.page.rule(0.8, 0.35)
        self.page.y -= 9

    def wrapped(self, text: str, indent: float = 0.0, size: float = 9.5) -> None:
        chars = int((width_page() - indent) / (size * 0.5))
        words, current = text.split(), ""
        for word in words:
            trial = f"{current} {word}".strip()
            if len(trial) > chars:
                self.line(current, size=size, indent=indent, after=0)
                current = word
            else:
                current = trial
        if current:
            self.line(current, size=size, indent=indent)


def build() -> Doc:
    d = Doc()

    # ---- letterhead -------------------------------------------------------
    d.line(HOSPITAL, font="F2", size=15, indent=0, leading=19, after=0)
    d.line(DEPARTMENT, font="F1", size=10, leading=14, after=1)
    d.line(TITLE, font="F2", size=10.5, leading=14, after=2)
    d.page.rule(1.0, 0.2)
    d.page.y -= 10

    # ---- patient demographics --------------------------------------------
    d.heading("PATIENT AND SPECIMEN DETAILS")
    col = width_page() * 0.46
    for i in range(0, len(PATIENT), 2):
        d.need(14)
        left = PATIENT[i]
        right = PATIENT[i + 1] if i + 1 < len(PATIENT) else None
        d.page.y -= 13
        d.page.text(MARGIN, "F2", 8.5, f"{left[0]}:")
        d.page.text(MARGIN + 100, "F1", 9.5, left[1])
        if right:
            d.page.text(MARGIN + col, "F2", 8.5, f"{right[0]}:")
            d.page.text(MARGIN + col + 100, "F1", 9.5, right[1])
    d.page.y -= 6

    # ---- vitals ----------------------------------------------------------
    d.heading("VITAL SIGNS ON ADMISSION")
    header = f"{'Parameter':<24}{'Value':>12}{'Unit':>10}{'Reference':>18}{'Flag':>10}"
    d.line(header, font="F3", size=8.5, leading=12, after=1)
    d.page.rule(0.5, 0.8)
    d.page.y -= 6
    for name, value, unit, ref, flag in VITALS:
        row = f"{name:<24}{value:>12}{unit:>10}{ref:>18}{flag:>10}"
        d.line(row, font="F3", size=8.5, leading=11.5, after=0)
    d.blank(6)

    # ---- laboratory results ----------------------------------------------
    d.heading("LABORATORY RESULTS")
    d.line(header, font="F3", size=8.5, leading=12, after=1)
    d.page.rule(0.5, 0.8)
    d.page.y -= 6
    for name, value, unit, ref, flag in LABS:
        row = f"{name:<24}{value:>12}{unit:>10}{ref:>18}{flag:>10}"
        d.line(row, font="F3", size=8.5, leading=11.5, after=0)
    d.blank(4)
    d.line(
        "Flags: HIGH above the reference range, LOW below the reference range.",
        font="F3",
        size=8,
        leading=11,
    )

    # ---- clinical narrative ----------------------------------------------
    d.heading("CHIEF COMPLAINT")
    d.wrapped(CHIEF)

    d.heading("HISTORY OF PRESENT ILLNESS")
    d.wrapped(HISTORY)

    d.heading("ASSESSMENT AND PLAN")
    for headline, detail in ASSESSMENT:
        d.need(28)
        d.line(headline, font="F2", size=9.5, leading=13, after=0)
        d.wrapped(detail, indent=12)
        d.blank(3)

    d.heading("MEDICATIONS AT DISCHARGE")
    for item in MEDICATIONS:
        d.need(14)
        d.wrapped(item, indent=12)
        d.blank(1)

    d.heading("FOLLOW-UP INSTRUCTIONS")
    for i, item in enumerate(FOLLOWUP, start=1):
        d.need(14)
        d.wrapped(f"{i}. {item}", indent=12)
        d.blank(1)

    d.heading("CLOSING NOTE")
    d.wrapped(CLOSING)

    d.blank(14)
    d.page.rule(0.6, 0.6)
    d.page.y -= 12
    for i, row in enumerate(SIGNATURE):
        d.line(row, font="F2" if i == 0 else "F1", size=9.5, leading=13, after=0)

    return d


def write_pdf(doc: Doc, path: Path) -> None:
    objects: list[bytes] = []

    def add(payload: str) -> int:
        objects.append(payload.encode("latin-1"))
        return len(objects)  # 1-based object number

    n_pages = len(doc.pages)
    # Object 1 = catalog, 2 = pages, then per page: page + content,
    # then the shared font objects at the end.
    font_ids = {}
    first_font = 3 + 2 * n_pages
    for i, (key, base) in enumerate(FONTS.items()):
        font_ids[key] = first_font + i

    page_ids = []
    kids_placeholder = add("")  # object 1, patched below
    pages_id = kids_placeholder

    for page in doc.pages:
        content_id = add(
            "<< /Length %d >>\nstream\n%s\nendstream"
            % (len(page.stream().encode("latin-1")), page.stream())
        )
        font_res = " ".join(
            f"/{k} {font_ids[k]} 0 R" for k in FONTS
        )
        page_id = add(
            "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] "
            "/Resources << /Font << %s >> >> /Contents %d 0 R >>"
            % (pages_id, PAGE_W, PAGE_H, font_res, content_id)
        )
        page_ids.append(page_id)

    objects[kids_placeholder - 1] = (
        "<< /Type /Pages /Count %d /Kids [%s] >>"
        % (n_pages, " ".join(f"{pid} 0 R" for pid in page_ids))
    ).encode("latin-1")

    catalog_id = add("<< /Type /Catalog /Pages %d 0 R >>" % pages_id)

    for key, base in FONTS.items():
        add(
            "<< /Type /Font /Subtype /Type1 /BaseFont /%s "
            "/Encoding /WinAnsiEncoding >>" % base
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0] * (len(objects) + 1)
    for num, payload in enumerate(objects, start=1):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + payload + b"\nendobj\n"

    xref_at = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for num in range(1, len(objects) + 1):
        out += b"%010d 00000 n \n" % offsets[num]
    out += (
        b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, catalog_id, xref_at)
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(out))


def main() -> None:
    target = Path(__file__).resolve().parent / "sample_medical_report.pdf"
    write_pdf(build(), target)
    print(f"wrote {target} ({target.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
