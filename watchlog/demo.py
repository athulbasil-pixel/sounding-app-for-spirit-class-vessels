"""Synthetic training data. NEVER used on the real database (refuses unless the
target folder is a demo folder). Numbers are invented and do not come from
any vessel record."""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from . import logic
from .db import connect
from .registry import WATCHES, load_registry

DEMO_MARKER = "DEMO_DATA_ONLY.txt"

# field -> (opening value, typical increase per 6-hour watch)
COUNTERS = {
    "feeder_dg123_counter": (996_000, 1500), "feeder_dg456_counter": (41_000, 60),
    "aft_boiler_hfo_counter": (512_000, 8), "fwd_boiler_hfo_counter": (77_000, 0),
    "aft_evap_loc_counter": (31_000, 85), "fwd_evap_loc_counter": (140_000, 80), "ro_ecr_counter": (690_000, 88),
    "hfo_purifier_1_cycles": (8_400, 6), "hfo_purifier_2_cycles": (7_990, 6), "hfo_filtration_1_cycles": (12_000, 4),
    "feeder_dg123_cycles": (3_100, 4), "hfo_purifier_3_cycles": (6_600, 6), "hfo_purifier_4_cycles": (5_520, 5),
    "hfo_filtrator_2_cycles": (10_870, 4), "feeder_dg456_cycles": (2_950, 3),
    "sa_aft_operating_h": (86_000, 5), "sa_aft_loading_h": (40_000, 2), "sa_fwd_operating_h": (42_000, 2),
    "sa_fwd_loading_h": (18_000, 1), "sa_osmosis_operating_h": (35_000, 6), "sa_osmosis_loading_h": (19_000, 3),
    "ca_comp3_operating_h": (23_000, 4), "start_air_1_h": (9_100, 1), "start_air_2_h": (6_000, 0),
    "start_air_3_h": (1_400, 0),
    **{f"dg{n}_cycles": (90_000 + n * 1311, 6) for n in range(1, 7)},
}
LEVELS = {"hfo_service_aft_ecr": 128, "hfo_service_aft_local": 129, "hfo_settling_aft_local": 6,
          "do_service_aft_local": 18, "hfo_service_fwd_ecr": 71, "hfo_service_fwd_local": 72,
          "hfo_settling_fwd_local": 13, "do_service_fwd_local": 20,
          **{f"dg{n}_sump_loc": 70 for n in range(1, 7)},
          "m4_1": 21.0, "m4_2": 48.0, "m4_3": 7.5, "m5": 120, "m8": 0, "gs": 805,
          "aft_lt": 790, "fwd_lt": 760, "aft_ht": 1150, "fwd_ht": 1200}
FW_SLOT_FIELDS = ("aft_evap_loc_counter", "fwd_evap_loc_counter", "ro_ecr_counter")
OFFICERS = ("2/E Demo Officer", "3/E Sample Officer", "C/E Training Officer")


def is_demo_dir(path: str | Path) -> bool:
    return (Path(path) / DEMO_MARKER).exists()


def mark_demo_dir(path: str | Path) -> None:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    (p / DEMO_MARKER).write_text("This folder holds SYNTHETIC training data only.\n", encoding="utf-8")


def generate(data_dir: str | Path, start: date, days: int = 14, seed: int = 7) -> dict:
    """Fill a demo folder with `days` of synthetic watches (last watch left as a draft)."""
    if not is_demo_dir(data_dir):
        raise RuntimeError("Refusing to write demo data: folder is not marked as a demo folder")
    from . import create_app
    app = create_app(data_dir, testing=True)
    reg = load_registry()
    rnd = random.Random(seed)
    conn = connect(app.config["DATABASE"])
    try:
        if conn.execute("SELECT COUNT(*) FROM watch_log").fetchone()[0]:
            return {"skipped": True}
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('vessel_name','MV Demo Spirit (training)')")
        for fid in ("aft_evap_ecr_counter", "fwd_evap_ecr_counter"):
            logic.set_not_in_use(conn, fid, start.isoformat(), True)
        val = {}
        for fid, (opening, _) in COUNTERS.items():
            logic.set_opening_balance(conn, fid, "6h", opening)
            val[fid] = opening
        fw_val = {f: COUNTERS[f][0] for f in FW_SLOT_FIELDS}
        for f in FW_SLOT_FIELDS:
            logic.set_opening_balance(conn, f, "4h", fw_val[f])
        level = dict(LEVELS)
        conn.execute("BEGIN")
        total = days * 4
        n = 0
        for i in range(days):
            ds = (start + timedelta(days=i)).isoformat()
            for w in WATCHES:
                n += 1
                logic.get_or_create_log(conn, ds, w)
                # fresh-water 4h slots typed in this watch (half-step), then the 6h reading
                slot = {"w1": "s1", "w2": "s2", "w3": "s4", "w4": "s5"}[w]
                for f in FW_SLOT_FIELDS:
                    fw_val[f] = val[f] + COUNTERS[f][1] // 2 + rnd.randint(-3, 3)
                    logic.save_reading(conn, reg, ds, w, f, slot, str(fw_val[f]))
                for fid, (_, step) in COUNTERS.items():
                    inc = max(0, step + (rnd.randint(-1, 1) if step > 3 else 0))
                    prev = val[fid]
                    val[fid] = prev + inc
                    raw = val[fid] % 1_000_000 if fid == "feeder_dg123_counter" else val[fid]
                    if fid == "sa_osmosis_loading_h" and i == 3 and w == "w2":
                        logic.save_reading(conn, reg, ds, w, fid, "watch", None, status="unavailable",
                                           reason="Meter fault (training example)")
                        continue
                    if fid == "hfo_filtration_1_cycles" and i == 5 and w == "w3":
                        continue                                    # a missing reading (training example)
                    logic.save_reading(conn, reg, ds, w, fid, "watch", str(int(raw)))
                    if fid == "feeder_dg123_counter" and raw < prev % 1_000_000:
                        logic.set_point_event(conn, fid, "6h", ds, w, "rollover", reason="Counter rolled over")
                for fid in LEVELS:
                    level[fid] = round(max(0, level[fid] + rnd.uniform(-0.8, 0.6)), 1) if isinstance(level[fid], float) \
                        else max(0, level[fid] + rnd.randint(-2, 2)) if fid not in ("m8",) else 0
                    logic.save_reading(conn, reg, ds, w, fid, "watch", str(level[fid]))
                if n < total:                              # leave the very last watch open as a draft
                    end = {"w1": "06:00", "w2": "12:00", "w3": "18:00", "w4": "23:59"}[w]
                    logic.close_log(conn, reg, ds, w, OFFICERS[n % len(OFFICERS)], f"{ds} {end}",
                                    "Synthetic training record." if n % 9 == 0 else None, confirm_missing=True)
        conn.execute("COMMIT")
        return {"skipped": False, "watches": total, "from": start.isoformat(),
                "to": (start + timedelta(days=days - 1)).isoformat()}
    finally:
        conn.close()
