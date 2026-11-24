"""Phase 2: close, versions/corrections, history, PDF, LAN gate (synthetic data only)."""
import json
from pathlib import Path

from watchlog import create_app

D = "2023-04-15"
OFFICER = "2/E Demo Officer"


def close(api, d, w, officer=OFFICER, closed_at=None, confirm=True, remarks=None):
    data = {"csrf": "test-token", "officer_new": officer, "closed_at": closed_at or f"{d} 12:00"}
    if confirm:
        data["confirm_missing"] = "1"
    if remarks is not None:
        data["remarks"] = remarks
    return api.c.post(f"/watch/{d}/{w}/close", data=data)


def log_row(conn, d, w, version=1):
    return conn.execute("SELECT * FROM watch_log WHERE ship_date=? AND watch=? AND version=?", (d, w, version)).fetchone()


# ------------------------------------------------------------ close

def test_close_records_officer_time_and_pdf(api, conn, app):
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "sa_aft_operating_h", "86631")
    api.put(D, "w2", "sa_aft_operating_h", "86635")
    r = close(api, D, "w2", closed_at="2023-04-15 12:04", remarks="Synthetic remark")
    assert r.status_code == 302 and "/record/" in r.location
    row = log_row(conn, D, "w2")
    assert row["status"] == "closed" and row["officer_name"] == OFFICER
    assert row["closed_at"] == "2023-04-15T12:04" and row["closed_recorded_at"]
    assert row["remarks"] == "Synthetic remark" and row["missing_confirmed"] == 1
    pdf = conn.execute("SELECT * FROM pdf_file WHERE log_id=?", (row["id"],)).fetchone()
    assert pdf["filename"] == "2023-04-15_0600-1200_Watch_Log.pdf"
    p = Path(app.config["DATA_DIR"]) / pdf["rel_path"]
    assert p.exists() and p.read_bytes()[:5] == b"%PDF-"
    # data folder is outside the repo
    assert Path(__file__).resolve().parent.parent not in p.resolve().parents


def test_close_requires_officer(api, conn):
    api.start(D, "w1")
    close(api, D, "w1", officer="")
    assert log_row(conn, D, "w1")["status"] == "draft"


def test_close_with_missing_requires_confirmation(api, conn):
    api.start(D, "w1")
    api.put(D, "w1", "m5", "120")
    close(api, D, "w1", confirm=False)
    assert log_row(conn, D, "w1")["status"] == "draft"
    close(api, D, "w1", confirm=True)
    assert log_row(conn, D, "w1")["status"] == "closed"


def test_close_blocked_while_reading_under_review(api, conn):
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "aft_boiler_hfo_counter", "500"); api.put(D, "w2", "aft_boiler_hfo_counter", "400")
    close(api, D, "w2")
    assert log_row(conn, D, "w2")["status"] == "draft"
    api.put(D, "w2", "aft_boiler_hfo_counter", "510")
    close(api, D, "w2")
    assert log_row(conn, D, "w2")["status"] == "closed"


def test_closed_watch_is_read_only(api):
    api.start(D, "w1")
    close(api, D, "w1")
    assert api.put(D, "w1", "m5", "1").status_code == 400
    assert api.c.put(f"/api/watch/{D}/w1/remarks", json={"remarks": "x"}, headers={"X-Watchlog": "1"}).status_code == 400
    r = api.c.get(f"/watch/{D}/w1")
    assert r.status_code == 302 and "/record/" in r.location


def test_bad_closure_time_rejected(api, conn):
    api.start(D, "w1")
    close(api, D, "w1", closed_at="noon")
    assert log_row(conn, D, "w1")["status"] == "draft"


# ------------------------------------------------------------ acceptance: two watches, close, restart, reopen, PDF

def test_two_watches_close_restart_reopen_pdf(tmp_path):
    app = create_app(tmp_path, testing=True)
    c = app.test_client()
    with c.session_transaction() as s:
        s["csrf"] = "t"
    H = {"X-Watchlog": "1"}
    for w, v in (("w1", "86631"), ("w2", "86635")):
        c.post(f"/watch/{D}/{w}/start", data={"csrf": "t"})
        c.put(f"/api/watch/{D}/{w}/reading", json={"field": "sa_aft_operating_h", "raw": v}, headers=H)
    c.put(f"/api/watch/{D}/w2/reading", json={"field": "m4_1", "raw": "21"}, headers=H)
    r = c.post(f"/watch/{D}/w2/close", data={"csrf": "t", "officer_new": OFFICER, "closed_at": f"{D} 12:00",
                                             "confirm_missing": "1"})
    log_id = int(r.location.rsplit("/", 1)[1])

    app2 = create_app(tmp_path, testing=True)          # restart
    c2 = app2.test_client()
    page = c2.get(f"/record/{log_id}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert OFFICER in html and "86635" in html and "+4 h" in html and "INCOMPLETE" in html
    pdf = c2.get(f"/pdf/{log_id}")
    assert pdf.status_code == 200 and pdf.data[:5] == b"%PDF-" and pdf.mimetype == "application/pdf"
    dl = c2.get(f"/pdf/{log_id}?download=1")
    assert "attachment" in dl.headers["Content-Disposition"]
    assert "2023-04-15_0600-1200_Watch_Log.pdf" in dl.headers["Content-Disposition"]
    hist = c2.get(f"/history?from={D}&to={D}").get_data(as_text=True)
    assert f"/record/{log_id}" in hist


# ------------------------------------------------------------ corrections

def test_correction_preserves_original(api, conn):
    api.start(D, "w1")
    api.put(D, "w1", "m5", "181")
    close(api, D, "w1")
    v1 = log_row(conn, D, "w1")
    snap_before = v1["snapshot_json"]

    r = api.c.post(f"/watch/{D}/w1/correct", data={"csrf": "test-token", "reason": "M5 mis-typed"})
    assert r.status_code == 302
    api.put(D, "w1", "m5", "118")
    # while the correction is a draft, the effective record is still v1
    assert api.c.get(f"/record/{v1['id']}").status_code == 200
    close(api, D, "w1", officer="3/E Sample Officer")

    v1_after = log_row(conn, D, "w1", 1)
    v2 = log_row(conn, D, "w1", 2)
    assert v1_after["status"] == "closed" and v1_after["snapshot_json"] == snap_before
    assert v1_after["officer_name"] == OFFICER
    r1 = conn.execute("SELECT value_num FROM reading WHERE log_id=? AND field_id='m5'", (v1["id"],)).fetchone()
    assert r1["value_num"] == 181                                     # original reading untouched
    assert v2["status"] == "closed" and v2["supersedes_id"] == v1["id"]
    assert v2["correction_reason"] == "M5 mis-typed"
    m5 = next(i for i in json.loads(v2["snapshot_json"])["items"] if i["field"] == "m5")
    assert m5["value"] == 118
    pdf = conn.execute("SELECT filename FROM pdf_file WHERE log_id=?", (v2["id"],)).fetchone()
    assert pdf["filename"] == "2023-04-15_0000-0600_Watch_Log_v2.pdf"
    # both versions listed on the record page; v1 marked superseded
    html = api.c.get(f"/record/{v1['id']}").get_data(as_text=True)
    assert "superseded" in html and "M5 mis-typed" in html


def test_correction_needs_reason_and_closed_record(api, conn):
    api.start(D, "w1")
    api.c.post(f"/watch/{D}/w1/correct", data={"csrf": "test-token", "reason": "x"})
    assert log_row(conn, D, "w1", 2) is None                          # not closed yet
    close(api, D, "w1")
    api.c.post(f"/watch/{D}/w1/correct", data={"csrf": "test-token", "reason": ""})
    assert log_row(conn, D, "w1", 2) is None


def test_next_watch_carries_from_effective_version(api):
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "dg1_cycles", "100")
    close(api, D, "w1")
    api.put(D, "w2", "dg1_cycles", "110")
    assert api.item(D, "w2", "dg1_cycles")["diff"] == 10
    api.c.post(f"/watch/{D}/w1/correct", data={"csrf": "test-token", "reason": "typo"})
    api.put(D, "w1", "dg1_cycles", "104")
    assert api.item(D, "w2", "dg1_cycles")["diff"] == 10              # draft correction not yet effective
    close(api, D, "w1")
    assert api.item(D, "w2", "dg1_cycles")["diff"] == 6


def test_discard_correction(api, conn):
    api.start(D, "w1")
    close(api, D, "w1")
    api.c.post(f"/watch/{D}/w1/correct", data={"csrf": "test-token", "reason": "test"})
    assert log_row(conn, D, "w1", 2) is not None
    api.c.post(f"/watch/{D}/w1/discard", data={"csrf": "test-token"})
    assert log_row(conn, D, "w1", 2) is None and log_row(conn, D, "w1", 1)["status"] == "closed"


# ------------------------------------------------------------ history

def test_history_filters(api):
    for d in ("2023-04-14", "2023-04-15"):
        for w in ("w1", "w2"):
            api.start(d, w)
    close(api, "2023-04-14", "w1")
    h = lambda q: api.c.get(f"/history?{q}").get_data(as_text=True)
    allrows = h("from=2023-04-14&to=2023-04-15")
    assert allrows.count("/record/") >= 4
    closed = h("from=2023-04-14&to=2023-04-15&status=closed")
    assert closed.count('<a href="/record/') == 1
    only_w2 = h("from=2023-04-14&to=2023-04-15&watch=w2")
    assert "0000–0600" not in only_w2


# ------------------------------------------------------------ PDF content

def test_pdf_marks_missing_and_correction(api, conn, app):
    from pypdf import PdfReader  # noqa: optional, skip if unavailable
    api.start(D, "w1")
    api.put(D, "w1", "m4_1", "21")
    close(api, D, "w1")
    api.c.post(f"/watch/{D}/w1/correct", data={"csrf": "test-token", "reason": "Synthetic fix"})
    close(api, D, "w1")
    v2 = log_row(conn, D, "w1", 2)
    rel = conn.execute("SELECT rel_path FROM pdf_file WHERE log_id=?", (v2["id"],)).fetchone()["rel_path"]
    reader = PdfReader(str(Path(app.config["DATA_DIR"]) / rel))
    text = "\n".join(p.extract_text() for p in reader.pages)
    assert "MISSING" in text and "CORRECTED RECORD" in text and "Synthetic fix" in text
    assert len(reader.pages) >= 2
    # table headings repeat on every page that continues a table
    assert sum("Equipment" in p.extract_text() for p in reader.pages) >= len(reader.pages) - 1
    w, h = reader.pages[0].mediabox.width, reader.pages[0].mediabox.height
    assert round(float(w)) == 595 and round(float(h)) == 842          # A4 in points


# ------------------------------------------------------------ LAN gate

def test_remote_clients_refused_without_lan_mode(client):
    r = client.get("/", environ_base={"REMOTE_ADDR": "192.168.1.50"})
    assert r.status_code == 403


def test_lan_mode_requires_pin(tmp_path):
    app = create_app(tmp_path, testing=True, lan=True)
    local = app.test_client()
    with local.session_transaction() as s:
        s["csrf"] = "t"
    local.post("/settings", data={"csrf": "t", "action": "lan_pin", "pin": "4321"})

    tab = app.test_client()
    remote = {"REMOTE_ADDR": "192.168.1.50"}
    r = tab.get("/", environ_base=remote)
    assert r.status_code == 302 and "/unlock" in r.location
    with tab.session_transaction() as s:
        s["csrf"] = "u"
    tab.post("/unlock", data={"csrf": "u", "pin": "0000"}, environ_base=remote)
    assert tab.get("/", environ_base=remote).status_code == 302          # still locked
    tab.post("/unlock", data={"csrf": "u", "pin": "4321"}, environ_base=remote)
    r = tab.get("/", environ_base=remote)
    assert r.status_code == 302 and "/day/" in r.location                # unlocked → normal redirect
    # PIN cannot be changed from a tablet
    r = tab.post("/settings", data={"csrf": "u", "action": "lan_pin", "pin": "1111"}, environ_base=remote)
    assert r.status_code == 403
