"""
growth.py
Entrance -> corridor -> core -> branching corridors -> rooms.

Corridor width is fixed at 1700cm throughout (per Adela's rule -- not
derived from the room catalog). Residential units use their REAL
footprint from catalog.py (width_cm along the corridor frontage,
depth_cm extending outward), so different unit types genuinely occupy
different amounts of space, rather than a uniform placeholder module.
Communal spaces (SK, SL, etc.) remain flexible-sized single rooms.

Overlap is checked with geometry.polygons_overlap, which tolerates
flush-touching edges -- this is what makes units attach directly to
the corridor wall without a false collision.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import random

from .geometry import Point, polygons_overlap
from .components import walk_rectangle, WallSegment
from .catalog import UnitType, get_unit

# NOTE ON UNITS: everything in this engine is CENTIMETRES. The constants
# below were originally transcribed straight off the drawings in MM and
# stored in _CM fields, which made the corridor 17m wide and the core a
# 17x17m room. Anything sourced from Rhino (unit footprints, the 300/600
# storey heights) was always correct cm -- only these hand-typed values
# were off, uniformly by 10x.
CORRIDOR_WIDTH_CM = 170.0        # 1.7m total width, walls included
CORRIDOR_HALF = CORRIDOR_WIDTH_CM / 2
CORE_SIZE_CM = 170.0             # 1.7x1.7m -- see PROJECT_SUMMARY, may need revisiting
CORE_HALF = CORE_SIZE_CM / 2
ENTRY_CORRIDOR_BAYS_CM = 340.0   # entrance straight run before reaching core (2 bays)

# Communal rooms have no surveyed geometry, so these stay placeholders --
# but they are now sized against the real unit catalog (6m frontage,
# 4-7m deep = 24-42 sqm) rather than left at the old 17m x 20-40m, which
# was absurd next to a 1.7m corridor. Replace with real numbers when the
# communal catalog defines them.
# Naming is inherited and misleading: _DEPTH_CM is the FRONTAGE measured
# along the corridor; _WIDTH_RANGE is the extent perpendicular to it.
COMMUNAL_WIDTH_RANGE = (400.0, 700.0)
COMMUNAL_DEPTH_CM = 600.0


@dataclass
class PlacedElement:
    kind: str                 # "corridor" | "core" | "unit" | "communal"
    label: str                # e.g. "1Bed_A", "SK"
    corners: list[Point]      # 4 corners, in order
    height_cm: float = 300.0  # default single floor
    walls: list[WallSegment] = field(default_factory=list)


@dataclass
class FloorPlan:
    elements: list[PlacedElement]
    entrance: Point
    core_position: Point
    unit_counts: dict[str, int]


def _rect(p1: Point, p2: Point, p3: Point, p4: Point) -> list[Point]:
    return [p1, p2, p3, p4]


def _add_corridor(elements, occupied, seg_start: Point, seg_end: Point, direction: Point):
    pd_ = Point(-direction.y, direction.x)
    c1 = seg_start + pd_.scaled(-CORRIDOR_HALF)
    c2 = seg_end + pd_.scaled(-CORRIDOR_HALF)
    c3 = seg_end + pd_.scaled(CORRIDOR_HALF)
    c4 = seg_start + pd_.scaled(CORRIDOR_HALF)
    corners = _rect(c1, c2, c3, c4)
    elements.append(PlacedElement("corridor", "Corridor", corners, walls=walk_rectangle(*corners)))
    occupied.append(corners)


def _add_core(elements, occupied, core_pos: Point):
    c1 = Point(core_pos.x - CORE_HALF, core_pos.y - CORE_HALF)
    c2 = Point(core_pos.x + CORE_HALF, core_pos.y - CORE_HALF)
    c3 = Point(core_pos.x + CORE_HALF, core_pos.y + CORE_HALF)
    c4 = Point(core_pos.x - CORE_HALF, core_pos.y + CORE_HALF)
    corners = _rect(c1, c2, c3, c4)
    elements.append(PlacedElement("core", "Core", corners, walls=walk_rectangle(*corners)))
    occupied.append(corners)


def _try_add_unit(elements, occupied, edge_start: Point, edge_end: Point,
                   perp_dir: Point, side: int, unit: UnitType) -> bool:
    out = perp_dir.scaled(side)
    c1, c2 = edge_start, edge_end
    c3 = edge_end + out.scaled(unit.depth_cm)
    c4 = edge_start + out.scaled(unit.depth_cm)
    corners = _rect(c1, c2, c3, c4)
    if not all(not polygons_overlap(corners, ex) for ex in occupied):
        return False
    occupied.append(corners)
    elements.append(PlacedElement(
        "unit", unit.name, corners, height_cm=unit.height_cm,
        walls=walk_rectangle(*corners),
    ))
    return True


def _try_add_communal(elements, occupied, edge_start: Point, edge_end: Point,
                       perp_dir: Point, side: int, label: str) -> bool:
    width = random.uniform(*COMMUNAL_WIDTH_RANGE)
    shrink = 1.0
    for attempt in range(7):
        w = width * shrink
        off = perp_dir.scaled(side * w)
        c1, c2 = edge_start, edge_end
        c3, c4 = edge_end + off, edge_start + off
        corners = _rect(c1, c2, c3, c4)
        if all(not polygons_overlap(corners, ex) for ex in occupied):
            occupied.append(corners)
            elements.append(PlacedElement(
                "communal", label, corners, walls=walk_rectangle(*corners),
            ))
            return True
        shrink *= 0.68
    return False


def generate_floorplan(program: list[str], seed: int | None = None) -> FloorPlan:
    """
    program: ordered list of type keys to place, e.g.
        ["Studio_A", "1Bed_B", "SK", "2Bed_A", "SL", "3Bed_A"]
    Residential entries must match names in catalog.UNIT_CATALOG.
    "SK" / "SL" (or any other non-catalog key) are treated as flexible
    communal rooms.
    """
    if seed is not None:
        random.seed(seed)

    elements: list[PlacedElement] = []
    occupied: list[list[Point]] = []
    unit_counts: dict[str, int] = {}

    entrance = Point(0, 0)
    entry_dir = Point(0, -1)
    core_pos = entrance + entry_dir.scaled(ENTRY_CORRIDOR_BAYS_CM)
    _add_corridor(elements, occupied, entrance, core_pos + entry_dir.scaled(-CORE_HALF), entry_dir)
    _add_core(elements, occupied, core_pos)

    branch_dirs = [Point(0, -1), Point(-1, 0), Point(1, 0)]  # straight, left, right -- orthogonal
    branches = []
    for d in branch_dirs:
        pd_ = Point(-d.y, d.x)
        start = core_pos + d.scaled(CORE_HALF)
        branches.append({"dir": d, "pd": pd_, "start": start, "offset_l": 0.0, "offset_r": 0.0})

    qi = 0
    bi = 0
    max_iterations = len(program) * 12  # safety valve against infinite retry loops
    iterations = 0
    while qi < len(program) and iterations < max_iterations:
        iterations += 1
        br = branches[bi % 3]
        side = -1 if (bi // 3) % 2 == 0 else 1
        offset_key = "offset_l" if side == -1 else "offset_r"
        type_key = program[qi]

        is_residential = type_key in [
            "Studio_A", "Studio_B", "1Bed_A", "1Bed_B",
            "2Bed_A", "2Bed_B", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
        ]

        if is_residential:
            unit = get_unit(type_key)
            length = unit.width_cm
        else:
            length = COMMUNAL_DEPTH_CM

        bay_start = br["start"] + br["dir"].scaled(br[offset_key])
        bay_end = br["start"] + br["dir"].scaled(br[offset_key] + length)
        edge_start = bay_start + br["pd"].scaled(side * CORRIDOR_HALF)
        edge_end = bay_end + br["pd"].scaled(side * CORRIDOR_HALF)

        if is_residential:
            placed = _try_add_unit(elements, occupied, edge_start, edge_end, br["pd"], side, unit)
        else:
            placed = _try_add_communal(elements, occupied, edge_start, edge_end, br["pd"], side, type_key)

        if placed:
            br[offset_key] += length
            unit_counts[type_key] = unit_counts.get(type_key, 0) + 1
            qi += 1
        bi += 1

    for br in branches:
        total = max(br["offset_l"], br["offset_r"])
        if total > 0:
            _add_corridor(elements, occupied, br["start"], br["start"] + br["dir"].scaled(total), br["dir"])

    return FloorPlan(elements=elements, entrance=entrance, core_position=core_pos, unit_counts=unit_counts)
