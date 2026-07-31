"""
massing.py
Turns a generated FloorPlan into simple extruded 3D blocks -- one box
per placed element, using its real height (single-floor rooms get one
storey, 3Bed/4Bed duplex units get their full two-storey height).

This is intentionally just a volumetric massing step: box geometry
only, no roof, no per-floor slab detail. OBJ/other file export is a
later step once the engine's logic is settled.
"""

from __future__ import annotations
from dataclasses import dataclass

from .geometry import Point, normalize
from .growth import FloorPlan, PlacedElement
from .catalog import get_unit

DEFAULT_FLOOR_HEIGHT_CM = 300.0


@dataclass
class MassingBlock:
    kind: str            # "corridor" | "core" | "unit" | "communal"
    label: str
    base_corners: list[Point]  # 4 corners at z0
    z0: float
    z1: float

    @property
    def height_cm(self) -> float:
        return self.z1 - self.z0

    def bounding_box(self) -> dict:
        xs = [c.x for c in self.base_corners]
        ys = [c.y for c in self.base_corners]
        return {
            "min": {"x": min(xs), "y": min(ys), "z": self.z0},
            "max": {"x": max(xs), "y": max(ys), "z": self.z1},
        }


def generate_massing(plan: FloorPlan, base_z: float = 0.0) -> list[MassingBlock]:
    """Coarse massing: one box per placed element (corridor, core, unit,
    communal room). Use generate_room_massing() instead if you want real
    interior room breakdown for units that have it."""
    blocks = []
    for el in plan.elements:
        height = el.height_cm if el.kind == "unit" else DEFAULT_FLOOR_HEIGHT_CM
        blocks.append(MassingBlock(
            kind=el.kind,
            label=el.label,
            base_corners=el.corners,
            z0=base_z,
            z1=base_z + height,
        ))
    return blocks


def generate_room_massing(plan: FloorPlan, base_z: float = 0.0) -> list[MassingBlock]:
    """
    Like generate_massing(), but for any placed unit whose catalog entry
    has real per-room geometry (unit.has_real_rooms), emit one block per
    ROOM instead of one block for the whole unit.

    Units without real room data (3Bed/4Bed, until exported) fall back
    to a single box, same as generate_massing().

    Room-local coordinates are mapped into world space using the unit's
    actual placed corners: c1 (edge_start) is the local origin, the
    c1->c2 edge is the local x-axis (along the corridor frontage,
    matching width_cm), and c1->c4 is the local y-axis (into the unit's
    depth, matching depth_cm) -- this matches how load_unit_from_export
    built each room's coordinates relative to the unit's position_min.
    """
    blocks = []
    for el in plan.elements:
        if el.kind == "unit":
            unit = get_unit(el.label)
            if unit.has_real_rooms:
                c1, c2, c3, c4 = el.corners
                along = normalize(Point(c2.x - c1.x, c2.y - c1.y))
                out = normalize(Point(c4.x - c1.x, c4.y - c1.y))
                for room in unit.rooms:
                    p1 = c1 + along.scaled(room.x_min) + out.scaled(room.y_min)
                    p2 = c1 + along.scaled(room.x_max) + out.scaled(room.y_min)
                    p3 = c1 + along.scaled(room.x_max) + out.scaled(room.y_max)
                    p4 = c1 + along.scaled(room.x_min) + out.scaled(room.y_max)
                    blocks.append(MassingBlock(
                        kind="room",
                        label=f"{el.label}:{room.name}",
                        base_corners=[p1, p2, p3, p4],
                        z0=base_z + room.z_min,
                        z1=base_z + room.z_min + room.height_cm,
                    ))
                continue
        height = el.height_cm if el.kind == "unit" else DEFAULT_FLOOR_HEIGHT_CM
        blocks.append(MassingBlock(
            kind=el.kind, label=el.label, base_corners=el.corners,
            z0=base_z, z1=base_z + height,
        ))
    return blocks


def massing_summary(blocks: list[MassingBlock]) -> dict:
    """Quick sanity-check summary: counts and total footprint area by kind."""
    summary: dict[str, dict] = {}
    for b in blocks:
        entry = summary.setdefault(b.kind, {"count": 0, "footprint_area_m2": 0.0})
        entry["count"] += 1
        xs = [c.x for c in b.base_corners]
        ys = [c.y for c in b.base_corners]
        width = max(xs) - min(xs)
        depth = max(ys) - min(ys)
        entry["footprint_area_m2"] += (width * depth) / 10000  # cm^2 -> m^2
    return summary
