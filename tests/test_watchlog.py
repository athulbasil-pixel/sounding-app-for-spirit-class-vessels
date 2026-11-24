"""Phase 1 acceptance and rule tests (synthetic data only)."""
import pytest

from watchlog import create_app
from watchlog.logic import ReadingError, parse_reading
from watchlog.registry import load_registry

D = "2023-04-15"


# ------------------------------------------------------------ registry

def test_registry_matches_workbook_sections(reg):
    ids = [s.id for s in reg.sections]
    assert ids == ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M"]
    assert reg.fw_fields == ["aft_evap_loc_counter", "fwd_evap_loc_counter", "ro_ecr_counter"]
    assert reg.fields["dg1_cycles"].kind == "cycle_counter"
    assert reg.fields["sa_aft_operating_h"].kind == "hours_counter"
    assert reg.fields["sa_aft_loading_h"].kind == "hours_counter"     # loading kept separate
    assert reg.fields["m4_1"].unit is None                             # unit unconfirmed


def test_fw_slots_stored_once(reg):
    """s3/s6 reuse the 6h reading; only s1, s2, s4, s5 are typed."""
    typed = {w: sorted({i["slot"] for i in reg.entry_items(w) if i["series"] == "4h" and not i["linked"]})
             for w in ("w1", "w2", "w3", "w4")}
    assert typed == {"w1": ["s1"], "w2": ["s2"], "w3": ["s4"], "w4": ["s5"]}
    linked = {i["slot"] for w in ("w2", "w4") for i in reg.entry_items(w) if i["linked"]}
    assert linked == {"s3", "s6"}


# ------------------------------------------------------------ parsing

@pytest.mark.parametrize("raw,expected", [
    ("86635", (86635.0, None)), ("1 204", (1204.0, None)), ("0", (0.0, None)),
    ("21,2", (21.2, None)), ("74+", (74.0, "+")), ("", (None, None)), ("  ", (None, None)),
])
def test_parse_reading(raw, expected):
    assert parse_reading(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "12a", "1.2.3"])
def test_parse_reading_rejects_text(raw):
    with pytest.raises(ReadingError):
        parse_reading(raw)


# ------------------------------------------------------------ core workflow

def test_compressor_86631_to_86635_is_4_hours(api):
    api.start(D, "w1"); api.start(D, "w2")
    assert api.put(D, "w1", "sa_aft_operating_h", "86631").status_code == 200
    assert api.put(D, "w2", "sa_aft_operating_h", "86635").status_code == 200
    it = api.item(D, "w2", "sa_aft_operating_h")
    assert it["prev"] == 86631 and it["diff"] == 4 and it["diff_status"] == "ok"
    assert it["lamp"] == "green"


def test_loading_hours_separate_from_operating(api):
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "sa_aft_operating_h", "100"); api.put(D, "w2", "sa_aft_operating_h", "106")
    api.put(D, "w1", "sa_aft_loading_h", "50"); api.put(D, "w2", "sa_aft_loading_h", "52")
    assert api.item(D, "w2", "sa_aft_operating_h")["diff"] == 6
    assert api.item(D, "w2", "sa_aft_loading_h")["diff"] == 2


def test_two_consecutive_watches_persist_after_restart(tmp_path):
    app = create_app(tmp_path, testing=True)
    c = app.test_client()
    with c.session_transaction() as s:
        s["csrf"] = "t"
    for w, v in (("w1", "1000"), ("w2", "1012")):
        c.post(f"/watch/{D}/{w}/start", data={"csrf": "t"})
        c.put(f"/api/watch/{D}/{w}/reading", json={"field": "feeder_dg456_counter", "raw": v}, headers={"X-Watchlog": "1"})
    c.put(f"/api/watch/{D}/w2/remarks", json={"remarks": "Synthetic remark"}, headers={"X-Watchlog": "1"})

    # "restart": brand-new app object on the same data folder
    app2 = create_app(tmp_path, testing=True)
    st = app2.test_client().get(f"/api/watch/{D}/w2").get_json()
    it = next(i for i in st["items"] if i["field"] == "feeder_dg456_counter")
    assert it["value"] == 1012 and it["prev"] == 1000 and it["diff"] == 12
    assert st["log"]["remarks"] == "Synthetic remark"
    assert st["log"]["status"] == "draft" and st["log"]["saved_at"]


def test_no_duplicate_log_for_same_date_and_watch(api, conn):
    api.start(D, "w2"); api.start(D, "w2"); api.start(D, "w2")
    n = conn.execute("SELECT COUNT(*) FROM watch_log WHERE ship_date=? AND watch='w2'", (D,)).fetchone()[0]
    assert n == 1


def test_draft_resumes_with_saved_values(api):
    api.start(D, "w3")
    api.put(D, "w3", "m5", "118")
    api.start(D, "w3")                      # "Start" again = resume, not reset
    assert api.item(D, "w3", "m5")["value"] == 118


# ------------------------------------------------------------ carry-forward

def test_midnight_carry_forward(api):
    api.start("2023-04-15", "w4"); api.start("2023-04-16", "w1")
    api.put("2023-04-15", "w4", "aft_boiler_hfo_counter", "500100")
    api.put("2023-04-16", "w1", "aft_boiler_hfo_counter", "500130")
    it = api.item("2023-04-16", "w1", "aft_boiler_hfo_counter")
    assert it["prev"] == 500100 and it["diff"] == 30


def test_month_end_carry_forward(api):
    api.start("2023-04-30", "w4"); api.start("2023-05-01", "w1")
    api.put("2023-04-30", "w4", "dg3_cycles", "97000")
    api.put("2023-05-01", "w1", "dg3_cycles", "97006")
    it = api.item("2023-05-01", "w1", "dg3_cycles")
    assert it["prev"] == 97000 and it["diff"] == 6


def test_year_end_carry_forward(api):
    api.start("2023-12-31", "w4"); api.start("2024-01-01", "w1")
    api.put("2023-12-31", "w4", "start_air_1_h", "9120")
    api.put("2024-01-01", "w1", "start_air_1_h", "9121")
    assert api.item("2024-01-01", "w1", "start_air_1_h")["diff"] == 1


def test_fw_4h_schedule_chain(api):
    """0400 slot carries from previous day's 2400 (= w4 watch reading); 1200 slot = w2 reading."""
    api.start("2023-04-14", "w4"); api.start(D, "w1"); api.start(D, "w2")
    api.put("2023-04-14", "w4", "ro_ecr_counter", "690000")           # 2400 reading
    api.put(D, "w1", "ro_ecr_counter", "690029", slot="s1")           # 0400
    api.put(D, "w2", "ro_ecr_counter", "690060", slot="s2")           # 0800
    api.put(D, "w2", "ro_ecr_counter", "690090")                      # 1200 (6h reading)
    s1 = api.item(D, "w1", "ro_ecr_counter", "s1")
    assert s1["prev"] == 690000 and s1["diff"] == 29
    s3 = api.item(D, "w2", "ro_ecr_counter", "s3")
    assert s3["linked"] and s3["value"] == 690090 and s3["prev"] == 690060 and s3["diff"] == 30


def test_linked_fw_slot_cannot_be_typed_separately(api):
    api.start(D, "w2")
    r = api.put(D, "w2", "ro_ecr_counter", "1", slot="s3")
    assert r.status_code == 400


# ------------------------------------------------------------ missing / zero / unavailable

def test_missing_m4_component_leaves_total_incomplete(api):
    api.start(D, "w1")
    api.put(D, "w1", "m4_1", "21.0"); api.put(D, "w1", "m4_3", "7.5")
    st = api.state(D, "w1")
    assert st["calcs"]["m4_total"] == {"value": None, "status": "incomplete"}
    api.put(D, "w1", "m4_2", "48.4")
    assert api.state(D, "w1")["calcs"]["m4_total"] == {"value": 76.9, "status": "ok"}


def test_explicit_zero_is_kept_and_counts(api):
    api.start(D, "w1")
    api.put(D, "w1", "m4_1", "0"); api.put(D, "w1", "m4_2", "0"); api.put(D, "w1", "m4_3", "0")
    api.put(D, "w1", "m8", "0")
    st = api.state(D, "w1")
    assert st["calcs"]["m4_total"] == {"value": 0, "status": "ok"}
    m8 = next(i for i in st["items"] if i["field"] == "m8")
    assert m8["state"] == "entered" and m8["value"] == 0


def test_clearing_a_value_makes_it_missing(api):
    api.start(D, "w1")
    api.put(D, "w1", "m5", "120"); api.put(D, "w1", "m5", "")
    assert api.item(D, "w1", "m5")["state"] == "missing"


def test_missing_previous_reading_makes_interval_incomplete(api):
    api.start(D, "w1"); api.start(D, "w2"); api.start(D, "w3")
    api.put(D, "w1", "hfo_purifier_1_cycles", "8400")
    # w2 left blank
    api.put(D, "w3", "hfo_purifier_1_cycles", "8412")
    it = api.item(D, "w3", "hfo_purifier_1_cycles")
    assert it["diff"] is None and it["diff_status"] == "incomplete"
    assert it["prev_last_valid"]["value"] == 8400 and it["prev_last_valid"]["point"] == "w1"
    assert api.item(D, "w2", "hfo_purifier_1_cycles")["diff_status"] == "incomplete"


def test_skipped_watch_is_a_gap_not_a_carry(api):
    api.start(D, "w1"); api.start(D, "w3")            # w2 never started
    api.put(D, "w1", "dg1_cycles", "100"); api.put(D, "w3", "dg1_cycles", "112")
    assert api.item(D, "w3", "dg1_cycles")["diff_status"] == "incomplete"


def test_unavailable_requires_reason(api):
    api.start(D, "w1")
    assert api.put(D, "w1", "fwd_boiler_hfo_counter", None, status="unavailable").status_code == 400
    r = api.put(D, "w1", "fwd_boiler_hfo_counter", None, status="unavailable", reason="Boiler off")
    assert r.status_code == 200
    it = api.item(D, "w1", "fwd_boiler_hfo_counter")
    assert it["state"] == "unavailable" and it["reason"] == "Boiler off" and it["lamp"] == "amber"
    assert api.state(D, "w1")["totals"]["unavailable"] == 1


def test_qualifier_is_preserved(api):
    api.start(D, "w1")
    api.put(D, "w1", "dg2_sump_loc", "74+")
    it = api.item(D, "w1", "dg2_sump_loc")
    assert it["value"] == 74 and it["qualifier"] == "+" and it["raw"] == "74+"


def test_bad_number_rejected(api):
    api.start(D, "w1")
    assert api.put(D, "w1", "m5", "abc").status_code == 400


# ------------------------------------------------------------ opening balance / backwards / rollover

def test_first_watch_uses_opening_balance(api):
    api.start(D, "w1")
    api.put(D, "w1", "feeder_dg123_counter", "5000")
    assert api.item(D, "w1", "feeder_dg123_counter")["diff_status"] == "no_previous"
    api.settings(action="opening", **{"ob__feeder_dg123_counter__6h": "4970"})
    it = api.item(D, "w1", "feeder_dg123_counter")
    assert it["prev"] == 4970 and it["prev_note"] == "opening balance" and it["diff"] == 30


def test_opening_balance_only_before_first_record(api):
    api.settings(action="opening", **{"ob__dg1_cycles__6h": "1"})
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "dg1_cycles", "10"); api.put(D, "w2", "dg1_cycles", "15")
    assert api.item(D, "w2", "dg1_cycles")["prev"] == 10


def test_backwards_meter_flagged_for_review(api):
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "aft_boiler_hfo_counter", "512330")
    api.put(D, "w2", "aft_boiler_hfo_counter", "512300")
    it = api.item(D, "w2", "aft_boiler_hfo_counter")
    assert it["diff_status"] == "review" and it["lamp"] == "red"
    assert api.state(D, "w2")["totals"]["review"] == 1


def test_confirmed_rollover_gives_positive_difference(api):
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "feeder_dg123_counter", "999812")
    api.put(D, "w2", "feeder_dg123_counter", "1204")
    assert api.event(D, "w2", "feeder_dg123_counter", "rollover").status_code == 200
    it = api.item(D, "w2", "feeder_dg123_counter")
    assert it["diff"] == 1392 and it["diff_status"] == "ok"      # (1 000 000 - 999 812) + 1 204
    api.event(D, "w2", "feeder_dg123_counter", None, method="DELETE")
    assert api.item(D, "w2", "feeder_dg123_counter")["diff_status"] == "review"


def test_rollover_uses_per_meter_limit(api):
    api.settings(action="field", field_id="aft_boiler_hfo_counter", effective_from=D, not_in_use="0",
                 rollover_limit="100000")
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "aft_boiler_hfo_counter", "99990")
    api.put(D, "w2", "aft_boiler_hfo_counter", "15")
    api.event(D, "w2", "aft_boiler_hfo_counter", "rollover")
    assert api.item(D, "w2", "aft_boiler_hfo_counter")["diff"] == 25


def test_meter_replaced(api):
    api.start(D, "w1"); api.start(D, "w2")
    api.put(D, "w1", "start_air_2_h", "6002")
    api.put(D, "w2", "start_air_2_h", "3")
    r = api.event(D, "w2", "start_air_2_h", "meter_replaced", value="0")
    assert r.status_code == 200
    assert api.item(D, "w2", "start_air_2_h")["diff"] == 3


# ------------------------------------------------------------ not in use

def test_not_in_use_hidden_and_not_missing_from_effective_date(api):
    api.start("2023-04-14", "w1"); api.start(D, "w1")
    api.settings(action="field", field_id="aft_evap_ecr_counter", effective_from=D, not_in_use="1")
    today = api.state(D, "w1")
    earlier = api.state("2023-04-14", "w1")
    assert next(i for i in today["items"] if i["field"] == "aft_evap_ecr_counter")["hidden"] is True
    assert next(i for i in earlier["items"] if i["field"] == "aft_evap_ecr_counter")["hidden"] is False
    assert today["totals"]["count"] == earlier["totals"]["count"] - 1


# ------------------------------------------------------------ fresh-water total

def test_fw_total_production(api):
    api.start(D, "w1"); api.start(D, "w2")
    for f, a, b in (("aft_evap_loc_counter", 100, 186), ("fwd_evap_loc_counter", 200, 281), ("ro_ecr_counter", 300, 387)):
        api.put(D, "w1", f, str(a)); api.put(D, "w2", f, str(b))
    assert api.state(D, "w2")["calcs"]["fw_total_production"]["value"] == 254


# ------------------------------------------------------------ security / misc

def test_api_write_requires_header(client):
    client.post(f"/watch/{D}/w1/start", data={"csrf": "test-token"})
    r = client.put(f"/api/watch/{D}/w1/reading", json={"field": "m5", "raw": "1"})
    assert r.status_code == 403


def test_form_post_requires_csrf(client):
    assert client.post(f"/watch/{D}/w1/start", data={}).status_code == 403


def test_bad_date_and_watch_rejected(client):
    assert client.get("/day/2023-02-30").status_code == 404
    assert client.get("/api/watch/2023-04-15/w9").status_code == 400


def test_home_never_needs_the_clock_when_draft_exists(api, client):
    api.start("2023-04-15", "w2")
    r = client.get("/")
    assert r.location.endswith("/day/2023-04-15")
