"""Phase 3 routes: reports page, per-field interval detail, CSV exports."""
from __future__ import annotations

import csv
import io
from datetime import date

from flask import Response, abort, render_template, request

from . import logic, reports
from .db import get_db
from .views import bp, reg


def _ref_date() -> date:
    raw = request.args.get("date")
    if raw:
        try:
            return date.fromisoformat(logic.check_date(raw))
        except logic.ReadingError:
            abort(400)
    d, _ = logic.suggested_ship_date(get_db())
    return date.fromisoformat(d)


@bp.get("/reports")
def reports_page():
    ref = _ref_date()
    rep = reports.report(get_db(), reg(), ref)
    return render_template("reports.html", rep=rep, ref=ref, periods=reports.PERIODS)


@bp.get("/reports/detail")
def report_detail():
    r = reg()
    fid = request.args.get("field", "")
    kind = request.args.get("period", "day")
    if fid not in r.fields or not r.fields[fid].is_counter or kind not in reports.PERIODS:
        abort(404)
    ref = _ref_date()
    conn = get_db()
    with logic.read_cache():
        p = reports.make_period(conn, kind, ref)
        total, rows = reports.field_total(conn, r, fid, p, with_intervals=True)
    return render_template("report_detail.html", f=r.fields[fid], period=p, kind=kind, total=total.as_dict(),
                           rows=rows, ref=ref, period_label=reports.PERIOD_LABELS[kind])


def _csv(rows: list[list], filename: str) -> Response:
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    # BOM so Excel opens UTF-8 (m³) correctly
    return Response("﻿" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@bp.get("/reports.csv")
def reports_csv():
    ref = _ref_date()
    rep = reports.report(get_db(), reg(), ref)
    rows = [["group", "id", "equipment", "unit", "period", "covered", "total", "intervals_valid",
             "intervals_expected", "complete", "gaps"]]
    for g in rep["groups"]:
        for row in g["rows"]:
            for k in reports.PERIODS:
                c = row["cells"][k]
                gaps = "; ".join(f'{x["ship_date"]} {x["watch"]}: {x["reason"]}' for x in c["gaps"])
                rows.append([g["title"], row["id"], row["label"], row["unit"], rep["periods"][k]["label"],
                             rep["periods"][k]["covered"], "" if c["value"] is None else c["value"],
                             c["valid"], c["expected"], "yes" if c["complete"] else "no", gaps])
    return _csv(rows, f"{ref.isoformat()}_Watch_Log_Report.csv")


@bp.get("/reports/intervals.csv")
def intervals_csv():
    try:
        d0 = date.fromisoformat(logic.check_date(request.args.get("from", "")))
        d1 = date.fromisoformat(logic.check_date(request.args.get("to", "")))
    except logic.ReadingError:
        abort(400)
    if (d1 - d0).days > 400 or d1 < d0:
        abort(400)
    rows = [["ship_date", "watch", "field", "equipment", "unit", "previous", "reading", "difference", "status", "note"]]
    for r in reports.intervals(get_db(), reg(), d0, d1):
        rows.append([r["ship_date"], logic.WATCH_LABELS[r["watch"]], r["field"], r["label"], r["unit"],
                     "" if r["prev"] is None else r["prev"], r["raw"] or ("" if r["value"] is None else r["value"]),
                     "" if r["diff"] is None else r["diff"], r["diff_status"],
                     r.get("diff_note") or r.get("reason") or ""])
    return _csv(rows, f"{d0.isoformat()}_to_{d1.isoformat()}_Watch_Intervals.csv")
