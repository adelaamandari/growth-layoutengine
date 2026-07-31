"""
catalog.py
Real per-unit-type footprint, height, and now per-ROOM geometry, sourced
from Adela's Rhino exports (export_unit_wall_infills.py output).

Two tiers of data quality, by design:
  - Studio_A, Studio_B, 1Bed_A, 1Bed_B, 2Bed_A, 2Bed_B have real
    per-room bounding boxes (unit.rooms is populated) -- these come
    from the JSON files bundled in unit_exports/.
  - 3Bed_A, 3Bed_B, 4Bed_A, 4Bed_B do not have per-room exports yet
    (unit.rooms is empty) -- they fall back to the overall bounding
    box only, same as before. Check unit.has_real_rooms before relying
    on unit.rooms.

Drop new exports into unit_exports/ and they load automatically at
import time, overriding the placeholder for that unit name -- no code
changes needed to add real data for 3Bed/4Bed once you export them.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import json
from pathlib import Path

M_TO_CM = 100
_EXPORTS_DIR = Path(__file__).parent / "unit_exports"


@dataclass(frozen=True)
class RoomComponent:
    """One real room inside a unit, in LOCAL coordinates (cm) relative
    to the unit's own origin -- i.e. (0,0,0) is the unit's position_min
    corner, same corner growth.py treats as edge_start when it places
    the unit against the corridor. x runs along the corridor frontage
    (matches unit.width_cm), y runs into the unit depth (matches
    unit.depth_cm), z_min is the room's floor level within the unit --
    0 for ground-floor rooms, ~300cm for rooms on the second floor of
    a duplex (3Bed/4Bed), letting multi-storey units stack correctly
    once real per-room data exists for them."""
    name: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    z_min: float
    height_cm: float

    @property
    def width_cm(self) -> float:
        return self.x_max - self.x_min

    @property
    def depth_cm(self) -> float:
        return self.y_max - self.y_min

    @property
    def area_m2(self) -> float:
        return (self.width_cm / 100) * (self.depth_cm / 100)


@dataclass(frozen=True)
class UnitType:
    name: str
    width_cm: float
    depth_cm: float
    height_cm: float
    object_count: int
    rooms: tuple[RoomComponent, ...] = field(default_factory=tuple)

    @property
    def has_real_rooms(self) -> bool:
        return len(self.rooms) > 0

    @property
    def floors(self) -> int:
        return max(1, round(self.height_cm / 300))

    @property
    def footprint_area_m2(self) -> float:
        return (self.width_cm / 100) * (self.depth_cm / 100)


# Fallback bounding-box-only data (used for any unit type without a
# real per-room export yet). Values converted m -> cm.
_RAW = {
    "Studio_A": {"width_x": 10, "depth_y": 4, "height_z": 3, "object_count": 40},
    "Studio_B": {"width_x": 6,  "depth_y": 8, "height_z": 3, "object_count": 38},
    "1Bed_A":   {"width_x": 9,  "depth_y": 6, "height_z": 3, "object_count": 46},
    "1Bed_B":   {"width_x": 8,  "depth_y": 7, "height_z": 3, "object_count": 47},
    "2Bed_A":   {"width_x": 11, "depth_y": 6, "height_z": 3, "object_count": 63},
    "2Bed_B":   {"width_x": 10, "depth_y": 6, "height_z": 3, "object_count": 60},
    "3Bed_A":   {"width_x": 9,  "depth_y": 5, "height_z": 6, "object_count": 142},
    "3Bed_B":   {"width_x": 10, "depth_y": 5, "height_z": 6, "object_count": 103},
    "4Bed_A":   {"width_x": 11, "depth_y": 6, "height_z": 6, "object_count": 148},
    "4Bed_B":   {"width_x": 9,  "depth_y": 7, "height_z": 6, "object_count": 109},
}

UNIT_CATALOG: dict[str, UnitType] = {
    name: UnitType(
        name=name,
        width_cm=d["width_x"] * M_TO_CM,
        depth_cm=d["depth_y"] * M_TO_CM,
        height_cm=d["height_z"] * M_TO_CM,
        object_count=d["object_count"],
        rooms=(),
    )
    for name, d in _RAW.items()
}


def load_unit_from_export(path: str | Path) -> UnitType:
    """
    Parse one of Adela's export_unit_wall_infills.py JSON files into a
    UnitType with real per-room geometry. Objects still carrying the
    unit's own fallback name (i.e. never individually named in Rhino)
    are excluded from .rooms -- they contributed to the overall
    bounding box but aren't attributable to a specific room.
    """
    path = Path(path)
    data = json.loads(path.read_text())
    unit_name = data["name"]
    dims = data["dimensions"]
    origin = data["position_min"]
    ox, oy, oz = origin["x"], origin["y"], origin["z"]

    groups: dict[str, list[dict]] = {}
    for comp in data.get("components", []):
        key = comp["name"].strip()
        groups.setdefault(key, []).append(comp)

    rooms = []
    skipped = []
    for key, items in groups.items():
        if key == unit_name:
            continue  # unnamed fallback objects, not a labeled room
        xs_min = min(it["position_min"]["x"] for it in items)
        xs_max = max(it["position_max"]["x"] for it in items)
        ys_min = min(it["position_min"]["y"] for it in items)
        ys_max = max(it["position_max"]["y"] for it in items)
        zs_min = min(it["position_min"]["z"] for it in items)
        zs_max = max(it["position_max"]["z"] for it in items)
        height_m = zs_max - zs_min
        if height_m < 0.01:
            # degenerate/flat object (e.g. a marker or door-swing symbol,
            # not real 3D geometry) -- skip rather than emit a zero-height
            # massing box. Found in 4Bed_B's "Entrance" group.
            skipped.append(key)
            continue
        rooms.append(RoomComponent(
            name=key,
            x_min=(xs_min - ox) * M_TO_CM,
            x_max=(xs_max - ox) * M_TO_CM,
            y_min=(ys_min - oy) * M_TO_CM,
            y_max=(ys_max - oy) * M_TO_CM,
            z_min=(zs_min - oz) * M_TO_CM,
            height_cm=height_m * M_TO_CM,
        ))
    if skipped:
        print(f"note: {unit_name} skipped degenerate (near-zero height) groups: {skipped}")

    return UnitType(
        name=unit_name,
        width_cm=dims["width_x"] * M_TO_CM,
        depth_cm=dims["depth_y"] * M_TO_CM,
        height_cm=dims["height_z"] * M_TO_CM,
        object_count=data.get("object_count", len(data.get("components", []))),
        rooms=tuple(rooms),
    )


def load_catalog_from_dir(path: str | Path) -> dict[str, UnitType]:
    """Load/override unit types from a directory of export JSON files."""
    catalog = dict(UNIT_CATALOG)
    for file in Path(path).glob("*.json"):
        try:
            unit = load_unit_from_export(file)
            catalog[unit.name] = unit
        except (KeyError, json.JSONDecodeError) as e:
            print(f"warning: skipped {file.name} ({e})")
    return catalog


def get_unit(name: str) -> UnitType:
    if name not in UNIT_CATALOG:
        raise KeyError(f"Unknown unit type '{name}'. Available: {list(UNIT_CATALOG)}")
    return UNIT_CATALOG[name]


# Auto-load real per-room data bundled with the module, overriding the
# placeholder entries above for any unit type that has a real export.
if _EXPORTS_DIR.exists():
    UNIT_CATALOG.update(load_catalog_from_dir(_EXPORTS_DIR))
