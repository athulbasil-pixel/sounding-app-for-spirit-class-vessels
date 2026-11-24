"""Reviewer feedback notes (synthetic)."""


def test_feedback_note_from_any_screen_and_export(client):
    r = client.post("/api/feedback", json={"page": "/watch/2023-04-15/w2", "page_title": "2023-04-15 0600-1200",
                                           "category": "missing", "text": "Add bilge well soundings"},
                    headers={"X-Watchlog": "1"})
    assert r.status_code == 200 and r.get_json()["count"] == 1
    client.post("/feedback", data={"csrf": "test-token", "action": "reviewer", "name": "", "reviewer": "2/E Reviewer"})
    client.post("/feedback", data={"csrf": "test-token", "action": "add", "category": "good", "text": "Keyboard entry is fast"})
    page = client.get("/feedback").get_data(as_text=True)
    assert "Add bilge well soundings" in page and "Keyboard entry is fast" in page
    exp = client.get("/feedback/export.txt")
    assert "attachment" in exp.headers["Content-Disposition"]
    txt = exp.get_data(as_text=True)
    assert "Reviewer:  2/E Reviewer" in txt and "Missing field or equipment - 2023-04-15 0600-1200" in txt
    assert "Notes:     2" in txt


def test_feedback_needs_text_and_header(client):
    assert client.post("/api/feedback", json={"text": "  "}, headers={"X-Watchlog": "1"}).status_code == 400
    assert client.post("/api/feedback", json={"text": "x"}).status_code == 403


def test_feedback_edit_and_delete(client, app):
    import sqlite3
    conn = sqlite3.connect(app.config["FEEDBACK_DB"], isolation_level=None)
    client.post("/api/feedback", json={"text": "first"}, headers={"X-Watchlog": "1"})
    fid = conn.execute("SELECT id FROM feedback").fetchone()[0]
    client.post("/feedback", data={"csrf": "test-token", "action": "edit", "id": fid, "category": "problem", "text": "edited"})
    assert tuple(conn.execute("SELECT text, category FROM feedback").fetchone()) == ("edited", "problem")
    client.post("/feedback", data={"csrf": "test-token", "action": "delete", "id": fid})
    assert conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0] == 0


def test_feedback_button_on_pages(client):
    html = client.get("/day/2023-04-15").get_data(as_text=True)
    assert "data-fb-open" in html and 'id="fb-dialog"' in html


def test_notes_from_training_and_normal_mode_share_one_file(tmp_path):
    from watchlog import create_app, demo
    shared = tmp_path / "real" / "feedback.sqlite3"
    real = create_app(tmp_path / "real", testing=True, feedback_db=shared)
    demo.mark_demo_dir(tmp_path / "demo")
    train = create_app(tmp_path / "demo", testing=True, feedback_db=shared)
    H = {"X-Watchlog": "1"}
    real.test_client().post("/api/feedback", json={"text": "from normal mode"}, headers=H)
    train.test_client().post("/api/feedback", json={"text": "from training mode"}, headers=H)
    txt = real.test_client().get("/feedback/export.txt").get_data(as_text=True)
    assert "from normal mode" in txt and "from training mode" in txt and "[training]" in txt
