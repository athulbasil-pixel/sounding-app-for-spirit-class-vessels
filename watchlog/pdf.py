"""A4 PDF of a saved watch record (built from the frozen closure snapshot)."""
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from .registry import WATCH_LABELS, Registry

LOGO = Path(__file__).resolve().parent / "static" / "brand" / "marinesense-logo.png"
NAVY = (3, 19, 49)
YELLOW = (246, 196, 0)
GREY = (90, 98, 112)
AMBER = (176, 106, 0)
RED = (178, 34, 34)
SLOT_AT = {"s1": "0400", "s2": "0800", "s3": "1200", "s4": "1600", "s5": "2000", "s6": "2400"}

_REPL = {"—": "-", "–": "-", "‒": "-", "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...",
         " ": " ", " ": " ", "↻": "", "↺": "", "→": "->", "▼": "v", "·": "·"}


def latin(s) -> str:
    """Core PDF fonts are Latin-1; keep m³ and ° but map other typography."""
    s = "" if s is None else str(s)
    for a, b in _REPL.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        v = round(float(v), 6)
        if v.is_integer():
            return f"{int(v):,}".replace(",", " ")
        i, d = f"{v}".split(".")
        return f"{int(i):,}".replace(",", " ") + "." + d
    return str(v)


def pdf_filename(log: dict) -> str:
    w = WATCH_LABELS[log["watch"]]
    suffix = f"_v{log['version']}" if log["version"] > 1 else ""
    return f"{log['ship_date']}_{w}_Watch_Log{suffix}.pdf"


class _Doc(FPDF):
    def __init__(self, title_line: str, sub_line: str, corrected: str | None):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.title_line, self.sub_line, self.corrected = title_line, sub_line, corrected
        self.generated = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(12, 12, 12)
        self.alias_nb_pages()

    def header(self):
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, 18, style="F")
        if LOGO.exists():
            self.image(str(LOGO), x=12, y=4.5, h=9)
        self.set_text_color(255, 255, 255)
        self.set_xy(80, 3.5)
        self.set_font("Helvetica", "B", 11)
        self.cell(118, 5, latin(self.title_line), align="R")
        self.set_xy(80, 9)
        self.set_font("Helvetica", "", 8.5)
        self.cell(118, 5, latin(self.sub_line), align="R")
        self.set_fill_color(*YELLOW)
        self.rect(0, 18, self.w, 0.8, style="F")
        self.set_text_color(0, 0, 0)
        if self.corrected:
            self.set_xy(12, 21)
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*AMBER)
            self.cell(0, 4, latin(self.corrected), align="L")
            self.set_text_color(0, 0, 0)
        self.set_y(27 if self.corrected else 23)

    def footer(self):
        self.set_y(-11)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*GREY)
        self.cell(0, 4, latin(f"Generated {self.generated} from the saved watch record · MarineSense Watch Log"), align="L")
        self.set_x(12)
        self.cell(0, 4, f"Page {self.page_no()}/{{nb}}", align="R")
        self.set_text_color(0, 0, 0)


def _status_text(it: dict) -> tuple[str, tuple | None]:
    if it.get("state") == "unavailable":
        return f"UNAVAILABLE: {it.get('reason') or ''}", AMBER
    if it.get("state") != "entered":
        return "", None                     # "MISSING" is already shown in red in the Current column
    ds = it.get("diff_status")
    if ds == "review":
        return "REVIEW: counter went backwards", RED
    if ds == "incomplete":
        return "Incomplete interval", AMBER
    if ds == "no_previous":
        return "No previous reading", AMBER
    note = it.get("diff_note") or (it.get("prev_note") if it.get("prev_note") == "opening balance" else "")
    return note or "", None


def build_pdf(state: dict, reg: Registry, vessel: str, out_path: Path, versions: list | None = None) -> str:
    log = state["log"]
    watch_lbl = WATCH_LABELS[log["watch"]]
    d = datetime.strptime(log["ship_date"], "%Y-%m-%d")
    corrected = None
    if log["version"] > 1:
        corrected = (f"CORRECTED RECORD - version {log['version']} · reason: {log.get('correction_reason') or ''}"
                     f" · correction started {(log.get('correction_created_at') or '').replace('T', ' ')[:16]}")
    doc = _Doc(f"Engine Room Watch Log · {d.strftime('%d %b %Y')} · {watch_lbl}",
               f"{vessel} · Spirit class · status {log['status'].upper()} · v{log['version']}", corrected)
    doc.add_page()

    # ---- summary block
    t = state["totals"]
    doc.set_font("Helvetica", "B", 14)
    doc.cell(0, 7, latin(f"Watch {watch_lbl} - ship date {d.strftime('%A %d %B %Y')}"), new_x="LMARGIN", new_y="NEXT")
    doc.set_font("Helvetica", "", 9)
    rows = [
        ("Status", f"{log['status'].upper()} (version {log['version']})"),
        ("Responsible officer", log.get("officer_name") or "-"),
        ("Closure time (ship)", (log.get("closed_at") or "-").replace("T", " ")),
        ("Recorded by PC at", (log.get("closed_recorded_at") or "-").replace("T", " ")[:16]),
        ("Readings", f"{t['entered']} entered · {t['missing']} missing · {t['unavailable']} unavailable · {t['review']} for review · {t['count']} expected"),
    ]
    if log.get("missing_confirmed"):
        rows.append(("Missing readings", "Closed with missing readings confirmed by the officer"))
    for k, v in rows:
        doc.set_font("Helvetica", "B", 9)
        doc.cell(42, 5, latin(k))
        doc.set_font("Helvetica", "", 9)
        doc.cell(0, 5, latin(v), new_x="LMARGIN", new_y="NEXT")
    if versions and len(versions) > 1:
        doc.ln(1)
        doc.set_font("Helvetica", "B", 9)
        doc.cell(0, 5, "Version history", new_x="LMARGIN", new_y="NEXT")
        doc.set_font("Helvetica", "", 8.5)
        for v in versions:
            line = (f"v{v['version']}: {v['status']}, closed {(v['closed_at'] or '-').replace('T', ' ')}"
                    f" by {v['officer_name'] or '-'}")
            if v["correction_reason"]:
                line += f" · correction reason: {v['correction_reason']}"
            doc.cell(0, 4.5, latin(line), new_x="LMARGIN", new_y="NEXT")
    doc.ln(2)

    items = state["items"]
    head_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=NAVY, size_pt=8)
    for sec in reg.sections:
        sec_items = [i for i in items if i["section"] == sec.id and not i.get("hidden")]
        if not sec_items:
            continue
        if doc.will_page_break(22):
            doc.add_page()
        doc.set_font("Helvetica", "B", 10)
        doc.set_fill_color(232, 236, 242)
        doc.cell(0, 6.5, latin(f"{sec.id} · {sec.title}"), fill=True, new_x="LMARGIN", new_y="NEXT")
        doc.set_font("Helvetica", "", 8)
        with doc.table(col_widths=(66, 14, 26, 26, 24, 30), text_align=("LEFT", "LEFT", "RIGHT", "RIGHT", "RIGHT", "LEFT"),
                       headings_style=head_style, repeat_headings=1, line_height=4.6, padding=1,
                       borders_layout="HORIZONTAL_LINES", first_row_as_headings=True) as table:
            hr = table.row()
            for h in ("Equipment", "Unit", "Previous", "Current", "Difference", "Status"):
                hr.cell(h)
            for it in sec_items:
                f = reg.fields[it["field"]]
                label = f.label
                if it["slot"] != "watch":
                    label = f"{label.split(' LOC')[0].split(' ECR')[0]} @ {SLOT_AT[it['slot']]}"
                    if it.get("linked"):
                        label += " (= 6h reading)"
                unit = f.unit or ("h" if f.kind == "hours_counter" else "cycles" if f.kind == "cycle_counter" else "unconf.")
                prev = fmt(it.get("prev")) if it.get("prev") is not None else "-"
                if it.get("state") == "entered":
                    cur = (it.get("raw") or fmt(it.get("value")))
                else:
                    cur = "MISSING" if it.get("state") != "unavailable" else "UNAVAIL."
                diff = ""
                if f.is_counter and it.get("diff") is not None:
                    diff = (("+" if it["diff"] >= 0 else "") + fmt(it["diff"]) + " " + f.diff_unit)
                status, color = _status_text(it)
                r = table.row()
                r.cell(latin(label))
                r.cell(latin(unit))
                r.cell(latin(prev))
                cur_style = FontFace(emphasis="BOLD", color=RED if cur == "MISSING" else AMBER) if it.get("state") != "entered" else None
                r.cell(latin(cur), style=cur_style)
                r.cell(latin(diff))
                r.cell(latin(status), style=FontFace(color=color) if color else None)
        calc = None
        if sec.id == "B":
            c = state["calcs"]["fw_total_production"]
            calc = ("Total production this watch (Aft LOC + Fwd LOC + RO)",
                    f"{fmt(c['value'])} m³" if c["status"] == "ok" else "INCOMPLETE")
        if sec.id == "M":
            c = state["calcs"]["m4_total"]
            calc = ("M4 TOTAL = M4.1 + M4.2 + M4.3", fmt(c["value"]) if c["status"] == "ok" else "INCOMPLETE")
        if calc:
            doc.set_font("Helvetica", "B", 8.5)
            if calc[1] == "INCOMPLETE":
                doc.set_text_color(*AMBER)
            doc.cell(0, 5.5, latin(f"{calc[0]}:  {calc[1]}"), align="R", new_x="LMARGIN", new_y="NEXT")
            doc.set_text_color(0, 0, 0)
        doc.ln(2.5)

    # ---- remarks + sign-off
    if doc.will_page_break(40):
        doc.add_page()
    doc.set_font("Helvetica", "B", 10)
    doc.set_fill_color(232, 236, 242)
    doc.cell(0, 6.5, "Remarks", fill=True, new_x="LMARGIN", new_y="NEXT")
    doc.set_font("Helvetica", "", 9)
    doc.multi_cell(0, 4.8, latin(log.get("remarks") or "-"), new_x="LMARGIN", new_y="NEXT")
    doc.ln(6)
    doc.set_font("Helvetica", "", 9)
    doc.cell(95, 5, latin(f"Responsible officer: {log.get('officer_name') or ''}"))
    doc.cell(0, 5, "Signature: ______________________________", new_x="LMARGIN", new_y="NEXT")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp")
    doc.output(str(tmp))
    data = tmp.read_bytes()
    tmp.replace(out_path)
    return hashlib.sha256(data).hexdigest()
