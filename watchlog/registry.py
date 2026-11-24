"""Load docs/field_registry.yaml and expose the entry layout and reading series.

Terminology
-----------
series "6h": one point per main watch (w1..w4) — slot "watch".
series "4h": fresh-water schedule s1..s6. s3 and s6 are not stored separately:
             they resolve to the w2 / w4 "watch" reading of the same field.
point: (ship_date, index) inside a series.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "docs" / "field_registry.yaml"

WATCHES = ["w1", "w2", "w3", "w4"]
WATCH_LABELS = {"w1": "0000-0600", "w2": "0600-1200", "w3": "1200-1800", "w4": "1800-2400"}
COUNTER_KINDS = {"counter", "hours_counter", "cycle_counter"}

# 4h slot index -> (watch whose log holds it, slot key used for storage)
FW_SLOTS = ["s1", "s2", "s3", "s4", "s5", "s6"]
FW_SLOT_STORAGE = {
    "s1": ("w1", "s1"),
    "s2": ("w2", "s2"),
    "s3": ("w2", "watch"),   # = 1200 watch reading
    "s4": ("w3", "s4"),
    "s5": ("w4", "s5"),
    "s6": ("w4", "watch"),   # = 2400 watch reading
}


@dataclass(frozen=True)
class Field:
    id: str
    section: str
    label: str
    kind: str
    unit: str | None
    unit_status: str
    group: str | None = None
    note: str | None = None
    derived_label: str | None = None
    derived_unit: str | None = None

    @property
    def is_counter(self) -> bool:
        return self.kind in COUNTER_KINDS

    @property
    def diff_unit(self) -> str:
        if self.derived_unit:
            return self.derived_unit
        return {"hours_counter": "h", "cycle_counter": "cycles"}.get(self.kind, self.unit or "")


@dataclass
class Section:
    id: str
    title: str
    tag: str
    fields: list[Field] = field(default_factory=list)
    groups: dict[str, str] = field(default_factory=dict)
    is_fw_schedule: bool = False
    calculated: list[dict] = field(default_factory=list)


@dataclass
class Registry:
    sections: list[Section]
    fields: dict[str, Field]
    fw_fields: list[str]
    slots: list[dict]

    def entry_items(self, watch: str) -> list[dict]:
        """Ordered (section, field, slot) items the crew types for a given watch."""
        items = []
        for sec in self.sections:
            if sec.is_fw_schedule:
                for slot in self.slots:
                    holder, key = FW_SLOT_STORAGE[slot["id"]]
                    if holder != watch:
                        continue
                    for fid in self.fw_fields:
                        items.append({"section": sec.id, "field": fid, "slot": slot["id"],
                                      "series": "4h", "linked": key == "watch"})
            else:
                for f in sec.fields:
                    items.append({"section": sec.id, "field": f.id, "slot": "watch",
                                  "series": "6h", "linked": False})
        return items


TAGS = {
    "A": "6h counters", "B": "6h counters", "C": "4h schedule", "D": "cleaning cycles",
    "E": "ECR / local levels", "F": "cleaning cycles", "G": "ECR / local levels",
    "H": "running hours", "J": "running hours", "K": "cycle counts", "L": "LOC. / DAM.",
    "M": "M4 · M5 · M8 · GS · LT · HT",
}

KIND_MAP = {"counter": "counter", "hours_counter": "hours_counter",
            "cycle_counter": "cycle_counter", "level": "level", "sounding": "sounding"}


@lru_cache(maxsize=1)
def load_registry(path: str | None = None) -> Registry:
    raw = yaml.safe_load(Path(path or REGISTRY_PATH).read_text(encoding="utf-8"))
    sections: list[Section] = []
    fields: dict[str, Field] = {}
    fw_fields: list[str] = []
    for s in raw["sections"]:
        sec = Section(id=s["id"], title=s["title"].replace(" - ", " — "), tag=TAGS.get(s["id"], ""),
                      groups={g["id"]: g["label"] for g in s.get("groups", [])},
                      is_fw_schedule=s.get("schedule") == "fresh_water_slots",
                      calculated=s.get("calculated", []))
        for f in s["fields"]:
            if sec.is_fw_schedule:
                # same physical meters as section B
                fw_fields.append(f["id"])
                continue
            derived = f.get("derived") or {}
            fld = Field(id=f["id"], section=sec.id, label=f["label"].replace(" - ", " — "),
                        kind=KIND_MAP[f["kind"]], unit=f.get("unit"),
                        unit_status=f.get("unit_status", "unconfirmed"), group=f.get("group"),
                        note=f.get("note"), derived_label=derived.get("label"),
                        derived_unit=derived.get("unit"))
            if fld.id in fields:
                raise ValueError(f"duplicate field id {fld.id}")
            fields[fld.id] = fld
            sec.fields.append(fld)
        sections.append(sec)
    for fid in fw_fields:
        if fid not in fields:
            raise ValueError(f"FW schedule field {fid} not defined in a 6h section")
    return Registry(sections=sections, fields=fields, fw_fields=fw_fields, slots=raw["fresh_water_slots"])
