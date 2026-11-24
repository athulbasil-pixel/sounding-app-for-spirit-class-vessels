"""Phase 3: period totals checked against a hand-calculated synthetic month.

Synthetic April 2023, every watch logged (30 days x 4 watches = 120 intervals):

  sa_aft_operating_h   opening 1000, +6 h every watch            -> 720 h if complete
                       Apr 10 1200-1800 reading MISSING           -> Apr 10 w3 and w4 intervals are gaps (-12 h)
  sa_fwd_operating_h   opening 500, +2 h every watch              -> 240 h, complete
  sa_osmosis_operating_h opening 0, +1 h; Apr 20 w1 UNAVAILABLE   -> 118 h, 2 gaps
  feeder_dg123_counter opening 999 000, +300 Ltr per watch, wraps at 1 000 000 (rollover confirmed)
                                                                  -> 36 000 Ltr, complete
  aft_evap_ecr_counter not in use for the whole month             -> no expected intervals
  May 1 0000-0600: sa_aft_operating_h +6                          -> carried across month-end
"""
import time
from datetime import date, timedelta

import pytest

from watchlog import logic, reports
from watchlog.registry import WATCHES, load_registry

APRIL = [date(2023, 4, 1) + timedelta(days=i) for i in range(30)]


@pytest.fixture
def month(conn):
    reg = load_registry()
    logic.set_opening_balance(conn, "sa_aft_operating_h", "6h", 1000)
    logic.set_opening_balance(conn, "sa_fwd_operating_h", "6h", 500)
    logic.set_opening_balance(conn, "sa_osmosis_operating_h", "6h", 0)
    logic.set_opening_balance(conn, "feeder_dg123_counter", "6h", 999_000)
    logic.set_not_in_use(conn, "aft_evap_ecr_counter", "2023-04-01", True)
    conn.execute("BEGIN")
    k = 0
    for d in APRIL:
        for w in WATCHES:
            k += 1
            ds = d.isoformat()
            logic.get_or_create_log(conn, ds, w)
            if not (ds == "2023-04-10" and w == "w3"):
                logic.save_reading(conn, reg, ds, w, "sa_aft_operating_h", "watch", str(1000 + 6 * k))
            logic.save_reading(conn, reg, ds, w, "sa_fwd_operating_h", "watch", str(500 + 2 * k))
            if ds == "2023-04-20" and w == "w1":
                logic.save_reading(conn, reg, ds, w, "sa_osmosis_operating_h", "watch", None,
                                   status="unavailable", reason="Synthetic: meter fault")
            else:
                logic.save_reading(conn, reg, ds, w, "sa_osmosis_operating_h", "watch", str(k))
            raw = (999_000 + 300 * k) % 1_000_000
            logic.save_reading(conn, reg, ds, w, "feeder_dg123_counter", "watch", str(raw))
            if raw < (999_000 + 300 * (k - 1)) % 1_000_000:        # meter wrapped: officer confirmed rollover
                logic.set_point_event(conn, "feeder_dg123_counter", "6h", ds, w, "rollover")
    # last completed watch: 30 Apr 1200-1800 (closed), 1800-2400 still a draft
    conn.execute("UPDATE watch_log SET status='closed' WHERE ship_date='2023-04-30' AND watch='w3'")
    # month-end carry: 1 May 0000-0600
    logic.get_or_create_log(conn, "2023-05-01", "w1")
    logic.save_reading(conn, reg, "2023-05-01", "w1", "sa_aft_operating_h", "watch", str(1000 + 6 * 121))
    conn.execute("COMMIT")
    return reg


def cell(rep, fid, period):
    for g in rep["groups"]:
        for r in g["rows"]:
            if r["id"] == fid:
                return r["cells"][period]
    raise KeyError(fid)


def test_month_totals_match_hand_calculation(conn, month):
    rep = reports.report(conn, month, date(2023, 4, 10))

    m = cell(rep, "sa_aft_operating_h", "month")
    assert m["value"] == 720 - 12 and m["valid"] == 118 and m["expected"] == 120 and not m["complete"]
    assert [(g["ship_date"], g["watch"]) for g in m["gaps"]] == [("2023-04-10", "w3"), ("2023-04-10", "w4")]
    assert m["gaps"][0]["reason"] == "reading missing" and m["gaps"][1]["reason"] == "previous reading missing"

    fwd = cell(rep, "sa_fwd_operating_h", "month")
    assert fwd == {"value": 240, "valid": 120, "expected": 120, "complete": True, "gaps": []}

    osm = cell(rep, "sa_osmosis_operating_h", "month")
    assert osm["value"] == 118 and len(osm["gaps"]) == 2
    assert osm["gaps"][0]["reason"].startswith("unavailable")

    feeder = cell(rep, "feeder_dg123_counter", "month")
    assert feeder["value"] == 36_000 and feeder["complete"]       # rollover handled

    assert cell(rep, "aft_evap_ecr_counter", "month")["expected"] == 0   # not in use


def test_day_week_and_composites(conn, month):
    rep = reports.report(conn, month, date(2023, 4, 10))
    day = cell(rep, "sa_aft_operating_h", "day")
    assert day["value"] == 12 and day["expected"] == 4 and len(day["gaps"]) == 2
    week = cell(rep, "sa_aft_operating_h", "week")                 # Mon 10 – Sun 16 Apr
    assert week["value"] == 28 * 6 - 12 and week["expected"] == 28
    assert rep["periods"]["week"]["covered"] == "10 Apr 2023 0000 → 16 Apr 2023 2400"

    wb = cell(rep, "sa_workbook_operating", "month")               # Aft + Fwd
    assert wb["value"] == 708 + 240 and not wb["complete"]
    allm = cell(rep, "sa_all_operating", "month")                  # Aft + Fwd + Osmosis
    assert allm["value"] == 708 + 240 + 118 and len(allm["gaps"]) == 4


def test_last_completed_watch(conn, month):
    rep = reports.report(conn, month, date(2023, 4, 30))
    assert rep["periods"]["watch"]["note"].endswith("1200-1800")
    assert cell(rep, "sa_aft_operating_h", "watch")["value"] == 6
    assert cell(rep, "sa_fwd_operating_h", "watch")["value"] == 2


def test_month_end_carry_and_partial_month(conn, month):
    rep = reports.report(conn, month, date(2023, 5, 1))
    may = cell(rep, "sa_aft_operating_h", "month")
    # only 1 May 0000-0600 recorded so far; later intervals are "not yet recorded", not gaps
    assert may["value"] == 6 and may["expected"] == 1 and may["complete"]
    assert rep["periods"]["month"]["covered"] == "01 May 2023 0000 → 01 May 2023 0600"
    # fields not entered in May have a gap for that one watch
    assert cell(rep, "sa_fwd_operating_h", "month")["gaps"][0]["reason"] == "reading missing"


def test_loading_hours_separate(conn, month):
    rep = reports.report(conn, month, date(2023, 4, 10))
    # no loading hours were entered at all: they are reported separately, all gaps, never mixed with operating
    ld = cell(rep, "sa_aft_loading_h", "month")
    assert ld["value"] is None and ld["valid"] == 0 and ld["expected"] == 120


def test_unconfirmed_backwards_meter_is_a_gap(conn, month):
    logic.clear_point_event(conn, "feeder_dg123_counter", "6h", "2023-04-01", "w4")
    rep = reports.report(conn, month, date(2023, 4, 1))
    d = cell(rep, "feeder_dg123_counter", "day")
    assert not d["complete"] and d["gaps"][0]["reason"].startswith("meter went backwards")


def test_month_report_is_fast(conn, month):
    t = time.perf_counter()
    reports.report(conn, month, date(2023, 4, 15))
    assert time.perf_counter() - t < 5


# ------------------------------------------------------------ HTTP

def test_reports_page_and_csv(month, client):
    html = client.get("/reports?date=2023-04-10").get_data(as_text=True)
    assert "Compressor running hours" in html and "708" in html and "2 gaps" in html
    det = client.get("/reports/detail?field=sa_aft_operating_h&period=day&date=2023-04-10")
    assert det.status_code == 200 and "reading missing" in det.get_data(as_text=True)
    csv = client.get("/reports.csv?date=2023-04-10")
    assert csv.status_code == 200 and "attachment" in csv.headers["Content-Disposition"]
    text = csv.get_data(as_text=True)
    assert "sa_aft_operating_h,Aft — operating hours,h,Month,01 Apr 2023 0000 → 30 Apr 2023 2400,708,118,120,no" in text
    iv = client.get("/reports/intervals.csv?from=2023-04-10&to=2023-04-10").get_data(as_text=True)
    assert "2023-04-10,1200-1800,sa_aft_operating_h" in iv


def test_report_rejects_bad_input(client):
    assert client.get("/reports?date=2023-02-30").status_code == 400
    assert client.get("/reports/detail?field=m5&period=day").status_code == 404
    assert client.get("/reports/intervals.csv?from=2023-01-01&to=2024-12-31").status_code == 400
