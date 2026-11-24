"""Phase 4: backups/restore, demo data isolation, health, error pages (synthetic data)."""
import io
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

import pytest

from watchlog import backup, create_app, demo

D = "2023-04-15"


def test_backup_is_consistent_and_listed(api, app):
    api.start(D, "w1"); api.put(D, "w1", "m5", "120")
    p = backup.make_backup(app.config["DATA_DIR"], app.config["DATABASE"], "manual")
    info = backup.check_db_file(p)
    assert info["logs"] == 1 and info["first"] == D
    names = [b["name"] for b in backup.list_backups(app.config["DATA_DIR"])]
    assert p.name in names


def test_backup_now_button_and_download(client, app):
    r = client.post("/backups/new", data={"csrf": "test-token"})
    assert r.status_code == 302
    b = backup.list_backups(app.config["DATA_DIR"])[0]
    dl = client.get(f"/backups/file/{b['name']}")
    assert dl.status_code == 200 and dl.data[:15] == b"SQLite format 3"
    assert client.get("/backups/file/..%5Csecret.key").status_code == 404


def test_close_makes_automatic_backup(api, app):
    api.start(D, "w1")
    api.c.post(f"/watch/{D}/w1/close", data={"csrf": "test-token", "officer_new": "2/E Demo",
                                             "closed_at": f"{D} 06:00", "confirm_missing": "1"})
    assert any(b["reason"] == "close" for b in backup.list_backups(app.config["DATA_DIR"]))


def test_restore_round_trip_keeps_pre_restore_copy(api, app, client):
    data, dbp = app.config["DATA_DIR"], app.config["DATABASE"]
    api.start(D, "w1"); api.put(D, "w1", "m5", "120")
    snap = backup.make_backup(data, dbp, "manual")
    api.put(D, "w1", "m5", "999")                                   # later change
    r = client.post("/backups/restore", data={"csrf": "test-token", "name": snap.name, "confirm": "RESTORE"})
    assert r.status_code == 302
    assert api.item(D, "w1", "m5")["value"] == 120                  # back to the backup
    pre = [b for b in backup.list_backups(data) if b["reason"] == "pre-restore"]
    assert len(pre) == 1
    con = sqlite3.connect(Path(data) / "backups" / pre[0]["name"])
    v = con.execute("SELECT value_num FROM reading WHERE field_id='m5'").fetchone()[0]
    con.close()
    assert v == 999                                                 # the overwritten state is kept


def test_restore_requires_typed_confirmation(api, app, client):
    api.start(D, "w1"); api.put(D, "w1", "m5", "120")
    snap = backup.make_backup(app.config["DATA_DIR"], app.config["DATABASE"])
    api.put(D, "w1", "m5", "130")
    client.post("/backups/restore", data={"csrf": "test-token", "name": snap.name, "confirm": "yes"})
    assert api.item(D, "w1", "m5")["value"] == 130


def test_restore_upload_rejects_non_database(client, api):
    api.start(D, "w1"); api.put(D, "w1", "m5", "120")
    r = client.post("/backups/restore", data={"csrf": "test-token", "confirm": "RESTORE",
                                              "file": (io.BytesIO(b"not a database" * 20), "x.sqlite3")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Not restored" in r.get_data(as_text=True)
    assert api.item(D, "w1", "m5")["value"] == 120


def test_restore_upload_of_valid_file(tmp_path, client, api, app):
    other = create_app(tmp_path / "other", testing=True)
    oc = other.test_client()
    with oc.session_transaction() as s:
        s["csrf"] = "t"
    oc.post(f"/watch/{D}/w2/start", data={"csrf": "t"})
    snap = backup.make_backup(other.config["DATA_DIR"], other.config["DATABASE"])
    with open(snap, "rb") as fh:
        r = client.post("/backups/restore", data={"csrf": "test-token", "confirm": "RESTORE",
                                                  "file": (fh, "watchlog.sqlite3")},
                        content_type="multipart/form-data", follow_redirects=True)
    assert "Restored (1 watch logs" in r.get_data(as_text=True)
    assert api.state(D, "w2")["log"] is not None


def test_full_zip_contains_db_and_pdfs(api, app, client):
    api.start(D, "w1")
    api.c.post(f"/watch/{D}/w1/close", data={"csrf": "test-token", "officer_new": "2/E Demo",
                                             "closed_at": f"{D} 06:00", "confirm_missing": "1"})
    r = client.get("/backups/full.zip")
    z = zipfile.ZipFile(io.BytesIO(r.data))
    names = z.namelist()
    assert "watchlog.sqlite3" in names and any(n.endswith("_Watch_Log.pdf") for n in names)


def test_copy_to_folder(app, client, tmp_path):
    client.post("/backups/new", data={"csrf": "test-token"})
    usb = tmp_path / "usb"; usb.mkdir()
    client.post("/backups/copy", data={"csrf": "test-token", "folder": str(usb)})
    assert list(usb.glob("watchlog_*.sqlite3"))
    r = client.post("/backups/copy", data={"csrf": "test-token", "folder": "Z:\\no\\such"}, follow_redirects=True)
    assert "Not copied" in r.get_data(as_text=True)


def test_prune_keeps_manual(app):
    data, dbp = app.config["DATA_DIR"], app.config["DATABASE"]
    backup.make_backup(data, dbp, "manual")
    for _ in range(5):
        backup.make_backup(data, dbp, "close")
    backup.prune(data, keep=2)
    kinds = [b["reason"] for b in backup.list_backups(data)]
    assert kinds.count("close") == 2 and kinds.count("manual") == 1


def test_backups_refused_from_tablet(tmp_path):
    app = create_app(tmp_path, testing=True, lan=True)
    c = app.test_client()
    with c.session_transaction() as s:
        s["csrf"] = "u"; s["lan_ok"] = True
    remote = {"REMOTE_ADDR": "192.168.1.50"}
    assert c.get("/backups", environ_base=remote).status_code == 403
    assert c.post("/backups/restore", data={"csrf": "u", "confirm": "RESTORE", "name": "x"},
                  environ_base=remote).status_code == 403


# ------------------------------------------------------------ demo / training data

def test_demo_refuses_unmarked_folder(tmp_path):
    with pytest.raises(RuntimeError):
        demo.generate(tmp_path, date(2023, 4, 1), days=1)


def test_demo_generates_closed_synthetic_watches(tmp_path):
    d = tmp_path / "WatchLog-DEMO"
    demo.mark_demo_dir(d)
    r = demo.generate(d, date(2023, 4, 1), days=3)
    assert r["watches"] == 12
    app = create_app(d, testing=True)
    assert app.config["DEMO"] is True
    c = app.test_client()
    html = c.get("/day/2023-04-03").get_data(as_text=True)
    assert "TRAINING MODE" in html and "Resume draft" in html          # last watch left open
    rep = c.get("/reports?date=2023-04-02").get_data(as_text=True)
    assert "Compressor running hours" in rep
    assert demo.generate(d, date(2023, 4, 1), days=3)["skipped"]      # never duplicates


def test_real_app_has_no_training_banner(client):
    assert "TRAINING MODE" not in client.get("/day/2023-04-15").get_data(as_text=True)


# ------------------------------------------------------------ health / errors / a11y

def test_health_and_error_pages(client):
    h = client.get("/health").get_json()
    assert h["ok"] is True and h["version"] == "1.0.0"
    r = client.get("/no-such-page")
    assert r.status_code == 404 and "Go to the Watch board" in r.get_data(as_text=True)


def test_pages_have_skip_link_and_main_landmark(api, client):
    api.start(D, "w1")
    for url in ("/day/2023-04-15", f"/watch/{D}/w1", "/history", "/reports", "/settings", "/backups"):
        html = client.get(url).get_data(as_text=True)
        assert 'href="#main"' in html and 'id="main"' in html, url
