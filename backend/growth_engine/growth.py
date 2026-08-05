"""
growth.py
Entrance -> corridor -> core -> branching corridors -> rooms, level by
level.

Corridor width is fixed at 170cm throughout (per Adela's rule -- not
derived from the room catalog). Residential units use their REAL
footprint from catalog.py (width_cm along the corridor frontage,
depth_cm extending outward), so different unit types genuinely occupy
different amounts of space, rather than a uniform placeholder module.
Communal spaces (SK, SL, etc.) remain flexible-sized single rooms.

Overlap is checked with geometry.polygons_overlap, which tolerates
flush-touching edges -- this is what makes units attach directly to
the corridor wall without a false collision.

WHY THE PLAN GROWS UP AND NOT JUST OUT
Growth used to run every unit onto the three ground-floor branches, so
a twelve-unit program spread over a 60x35m extent -- three arms of
loose frontage, one storey, nothing above. `max_branch_cm` now caps how
far a branch may run from the core. A unit that no run on this level
can take without breaking the cap starts the next level instead, above
the same footprint. The composition compacts because the program
stacks rather than sprawls, which is also what the circulation implies:
the core is a stair, and a stair with one floor to serve is decoration.

Each level carries its own armature -- core, branch corridors -- and
its own occupancy, so a unit only has to miss what is actually on its
own storey. A duplex is 600cm tall and therefore reserves its footprint
on TWO levels, which is why `_floors()` exists and why occupancy is a
dict keyed by level rather than one flat list.

Walls are NOT built per element. Once every element is placed,
walls.resolve_walls() turns the set of element edges into the physical
walls, each built once and referenced by the elements that sit on it --
see walls.py. That resolution runs PER LEVEL: a corridor on level 1
stands directly above the one on level 0, and resolving them together
would collapse two real walls into one.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import random

from .geometry import Point, polygons_overlap
from .catalog import UnitType, get_unit
from .walls import Wall, resolve_walls, walls_by_owner

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

# One storey. Matches massing.DEFAULT_FLOOR_HEIGHT_CM and frame.STOREY_CM;
# a duplex's surveyed 600cm is exactly two of these.
LEVEL_HEIGHT_CM = 300.0

# How far a branch may run from the core before the level is full. The
# widest surveyed unit has an 11.2m frontage, so 12m lets a run take one
# large unit or two small ones and then hands the rest of the program to
# the level above. This is the single number that decides how compact
# the composition is: raise it and the plan spreads, lower it and it
# stacks.
MAX_BRANCH_CM = 1200.0

# Safety valve. A program that cannot place inside this many levels is
# not going to place at all.
MAX_LEVELS = 12

# How many storeys in a row may come up empty before growth gives up. A
# level can be completely blocked by the duplexes reaching into it from
# below -- their footprints are up to 11m long, so on a 12m branch they
# fill every bay -- while the level ABOVE them is free. Stopping at the
# first empty storey abandoned most of the program in exactly that case.
MAX_EMPTY_LEVELS = 2

# How far along a run to shuffle when a bay is blocked. Upper storeys
# are not empty the way the ground floor is -- a duplex below reserves
# its footprint on the level above -- so a run has to be able to step
# PAST an obstruction rather than stalling on it. 100cm is the source
# file's own grid; without this, a level whose first bays are all under
# duplexes places nothing and the program gives up with units unbuilt.
PROBE_STEP_CM = 100.0

# Keys the engine builds as real surveyed units. Anything else in a
# program becomes a flexible communal room -- that is how SK/SL work,
# and it is why a typo builds a blank box instead of failing.
RESIDENTIAL_KEYS = (
    "Studio_A", "Studio_B", "1Bed_A", "1Bed_B",
    "2Bed_A", "2Bed_B", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
)


@dataclass
class PlacedElement:
    kind: str                 # "corridor" | "core" | "unit" | "communal"
    label: str                # e.g. "1Bed_A", "SK"
    corners: list[Point]      # 4 corners, in order
    height_cm: float = 300.0  # default single floor
    # Which storey this sits on. 0 is the ground floor. A duplex placed
    # on level L is 600cm tall and therefore also occupies L+1 -- it is
    # still ONE element with one footprint, listed once, at level L.
    level: int = 0
    # Ids into FloorPlan.walls. Elements REFERENCE walls rather than
    # owning them -- a wall shared with a neighbour appears in both
    # elements' wall_ids but exists once in the plan.
    wall_ids: list[int] = field(default_factory=list)
    # Position in the growth sequence. NOT this element's index in
    # FloorPlan.elements -- see _assign_growth_steps for why they differ.
    growth_step: int = 0

    @property
    def z0(self) -> float:
        """Height of this element's floor slab above the ground."""
        return self.level * LEVEL_HEIGHT_CM

    @property
    def floors(self) -> int:
        """How many levels it occupies. 2 for a duplex, 1 for the rest."""
        return max(1, int(round(self.height_cm / LEVEL_HEIGHT_CM)))


@dataclass
class FloorPlan:
    elements: list[PlacedElement]
    entrance: Point
    core_position: Point
    unit_counts: dict[str, int]
    # The physical walls, each built once. See walls.resolve_walls.
    walls: list[Wall] = field(default_factory=list)
    # Sub-MIN_WALL_CM stretches that were real but too short to build.
    # Tracked so length accounting stays exact rather than approximate.
    dropped_wall_cm: float = 0.0
    dropped_wall_count: int = 0
    # How many storeys the program ended up needing.
    level_count: int = 1


def _rect(p1: Point, p2: Point, p3: Point, p4: Point) -> list[Point]:
    return [p1, p2, p3, p4]


def _assign_growth_steps(elements: list[PlacedElement]) -> None:
    """
    Number the elements in the order the building GROWS -- level by
    level, and within a level entrance -> corridor -> core -> branching
    corridors -> rooms -- which is deliberately NOT their order in
    `elements`.

    The two differ for a real reason. A branch corridor's length is
    max(offset_l, offset_r), which is not known until every unit on that
    branch has been placed, so branch corridors can only be APPENDED
    after the placement loop. Structurally, though, a corridor is the
    armature the rooms attach to and grows before them. This restores
    the structural order for anything replaying the growth (the 3D
    viewer animates on it). No geometry depends on it -- it is an
    ordering annotation only, so getting it wrong cannot move a wall.

    Sorting by level first is what makes the animation read as a
    building going up rather than as storeys arriving interleaved.

    Elements sharing a step grow together: a unit's rooms all carry the
    unit's step, so a unit rises as one thing rather than room by room.
    """
    rank = {"corridor": 1, "core": 0, "unit": 2, "communal": 2}
    # The entry run is elements[0] by construction, and it is the one
    # corridor that should precede the core rather than follow it.
    order = sorted(
        range(len(elements)),
        key=lambda i: (elements[i].level,
                       -1 if i == 0 else rank.get(elements[i].kind, 2),
                       i),
    )
    for step, idx in enumerate(order):
        elements[idx].growth_step = step


def _reserve(occupied: dict[int, list], level: int, floors: int, corners) -> None:
    """Claim a footprint on every level the element passes through."""
    for lv in range(level, level + floors):
        occupied.setdefault(lv, []).append(corners)


def _is_free(occupied: dict[int, list], level: int, floors: int, corners) -> bool:
    for lv in range(level, level + floors):
        if any(polygons_overlap(corners, ex) for ex in occupied.get(lv, [])):
            return False
    return True


def _add_corridor(elements, occupied, seg_start: Point, seg_end: Point,
                  direction: Point, level: int = 0):
    pd_ = Point(-direction.y, direction.x)
    c1 = seg_start + pd_.scaled(-CORRIDOR_HALF)
    c2 = seg_end + pd_.scaled(-CORRIDOR_HALF)
    c3 = seg_end + pd_.scaled(CORRIDOR_HALF)
    c4 = seg_start + pd_.scaled(CORRIDOR_HALF)
    corners = _rect(c1, c2, c3, c4)
    elements.append(PlacedElement("corridor", "Corridor", corners, level=level))
    _reserve(occupied, level, 1, corners)


def _add_core(elements, occupied, core_pos: Point, level: int = 0):
    c1 = Point(core_pos.x - CORE_HALF, core_pos.y - CORE_HALF)
    c2 = Point(core_pos.x + CORE_HALF, core_pos.y - CORE_HALF)
    c3 = Point(core_pos.x + CORE_HALF, core_pos.y + CORE_HALF)
    c4 = Point(core_pos.x - CORE_HALF, core_pos.y + CORE_HALF)
    corners = _rect(c1, c2, c3, c4)
    elements.append(PlacedElement("core", "Core", corners, level=level))
    _reserve(occupied, level, 1, corners)


def _try_add_unit(elements, occupied, edge_start: Point, edge_end: Point,
                   perp_dir: Point, side: int, unit: UnitType,
                   level: int = 0) -> bool:
    out = perp_dir.scaled(side)
    c1, c2 = edge_start, edge_end
    c3 = edge_end + out.scaled(unit.depth_cm)
    c4 = edge_start + out.scaled(unit.depth_cm)
    corners = _rect(c1, c2, c3, c4)
    # A duplex has to clear BOTH the storey it stands on and the one it
    # reaches into, or it would grow through the floor above it.
    floors = max(1, int(round(unit.height_cm / LEVEL_HEIGHT_CM)))
    if not _is_free(occupied, level, floors, corners):
        return False
    _reserve(occupied, level, floors, corners)
    elements.append(PlacedElement(
        "unit", unit.name, corners, height_cm=unit.height_cm, level=level,
    ))
    return True


def _try_add_communal(elements, occupied, edge_start: Point, edge_end: Point,
                       perp_dir: Point, side: int, label: str,
                       level: int = 0) -> bool:
    width = random.uniform(*COMMUNAL_WIDTH_RANGE)
    shrink = 1.0
    for attempt in range(7):
        w = width * shrink
        off = perp_dir.scaled(side * w)
        c1, c2 = edge_start, edge_end
        c3, c4 = edge_end + off, edge_start + off
        corners = _rect(c1, c2, c3, c4)
        if _is_free(occupied, level, 1, corners):
            _reserve(occupied, level, 1, corners)
            elements.append(PlacedElement(
                "communal", label, corners, level=level,
            ))
            return True
        shrink *= 0.68
    return False


def _make_branches(core_pos: Point) -> list[dict]:
    """The three orthogonal arms leaving the core: straight, left, right."""
    branches = []
    for d in (Point(0, -1), Point(-1, 0), Point(1, 0)):
        pd_ = Point(-d.y, d.x)
        branches.append({
            "dir": d, "pd": pd_, "start": core_pos + d.scaled(CORE_HALF),
            "offset_l": 0.0, "offset_r": 0.0,
        })
    return branches


def _resolve_walls_per_level(elements: list[PlacedElement]):
    """
    Resolve walls one storey at a time and renumber into a single list.

    Resolving every element together would be wrong now that the plan
    stacks: a level-1 corridor sits exactly above the level-0 one, and
    `resolve_walls` works in plan, so it would merge two real walls into
    one and halve the take-off. Elements are grouped by their OWN level
    -- a duplex belongs to the level it stands on, and its walls are
    simply 600cm tall.

    Returns (walls, dropped_cm, dropped_count) with owners as global
    indices into `elements`, exactly as the single-group version did.
    """
    by_level: dict[int, list[int]] = {}
    for i, el in enumerate(elements):
        by_level.setdefault(el.level, []).append(i)

    walls: list[Wall] = []
    dropped_cm = 0.0
    dropped_count = 0
    for level in sorted(by_level):
        idxs = by_level[level]
        res = resolve_walls([elements[i] for i in idxs])
        for w in res.walls:
            walls.append(Wall(
                id=len(walls), start=w.start, end=w.end,
                owners=tuple(idxs[o] for o in w.owners),
                segments=w.segments,
            ))
        dropped_cm += res.dropped_cm
        dropped_count += res.dropped_count
    return walls, dropped_cm, dropped_count


def generate_floorplan(program: list[str], seed: int | None = None,
                       max_branch_cm: float = MAX_BRANCH_CM,
                       max_levels: int = MAX_LEVELS) -> FloorPlan:
    """
    program: ordered list of type keys to place, e.g.
        ["Studio_A", "1Bed_B", "SK", "2Bed_A", "SL", "3Bed_A"]
    Residential entries must match names in catalog.UNIT_CATALOG.
    "SK" / "SL" (or any other non-catalog key) are treated as flexible
    communal rooms.

    max_branch_cm caps how far a branch runs from the core. When no run
    on the current level can take the next unit within that cap, growth
    moves up a storey rather than reaching further out -- this is the
    knob that decides whether the composition sprawls or stacks. Pass a
    very large value for the old single-storey behaviour.
    """
    if seed is not None:
        random.seed(seed)

    elements: list[PlacedElement] = []
    # Occupancy is per level: a unit only has to clear what is actually
    # on its own storey.
    occupied: dict[int, list[list[Point]]] = {}
    unit_counts: dict[str, int] = {}

    entrance = Point(0, 0)
    entry_dir = Point(0, -1)
    core_pos = entrance + entry_dir.scaled(ENTRY_CORRIDOR_BAYS_CM)
    # The entry run belongs to the ground floor only. Upper storeys
    # reach the branches through the core, which is the stair.
    _add_corridor(elements, occupied, entrance,
                  core_pos + entry_dir.scaled(-CORE_HALF), entry_dir, level=0)

    qi = 0
    level = 0
    level_branches: list[tuple[int, list[dict]]] = []
    max_iterations = len(program) * 12  # safety valve against infinite retry loops
    iterations = 0

    empty_streak = 0
    while qi < len(program) and level < max_levels and iterations < max_iterations:
        # The core is the stair, so it is built on every storey the
        # building passes through -- including one that ends up holding
        # only the upper halves of the duplexes below. Storeys above the
        # topmost occupied one are pruned after the loop.
        _add_core(elements, occupied, core_pos, level=level)
        branches = _make_branches(core_pos)
        level_branches.append((level, branches))

        # Runs in the order they should fill: both sides of one branch
        # before moving to the next, so a corridor is double-loaded
        # rather than three arms each growing a single-loaded tail.
        runs = [(br, side) for br in branches for side in (-1, 1)]
        bi = 0
        placed_on_level = False

        while qi < len(program) and iterations < max_iterations:
            iterations += 1
            type_key = program[qi]
            is_residential = type_key in RESIDENTIAL_KEYS
            unit = get_unit(type_key) if is_residential else None
            length = unit.width_cm if is_residential else COMMUNAL_DEPTH_CM

            placed = False
            for attempt in range(len(runs)):
                br, side = runs[(bi + attempt) % len(runs)]
                offset_key = "offset_l" if side == -1 else "offset_r"

                # Walk along the run until the unit fits or the cap is
                # reached. The cap is checked BEFORE placing, so a run
                # never overshoots by a unit width, and stepping past a
                # blocked bay is what lets an upper storey build around
                # the duplexes reaching up into it.
                probe = br[offset_key]
                while probe + length <= max_branch_cm and not placed:
                    bay_start = br["start"] + br["dir"].scaled(probe)
                    bay_end = br["start"] + br["dir"].scaled(probe + length)
                    edge_start = bay_start + br["pd"].scaled(side * CORRIDOR_HALF)
                    edge_end = bay_end + br["pd"].scaled(side * CORRIDOR_HALF)

                    if is_residential:
                        ok = _try_add_unit(elements, occupied, edge_start, edge_end,
                                           br["pd"], side, unit, level=level)
                    else:
                        ok = _try_add_communal(elements, occupied, edge_start, edge_end,
                                               br["pd"], side, type_key, level=level)
                    if ok:
                        # Assign, not increment: the run may have
                        # skipped a gap to get past an obstruction, and
                        # the corridor still has to reach this far.
                        br[offset_key] = probe + length
                        unit_counts[type_key] = unit_counts.get(type_key, 0) + 1
                        qi += 1
                        bi += attempt + 1
                        placed = placed_on_level = True
                        break
                    probe += PROBE_STEP_CM

                if placed:
                    break

            if not placed:
                break

        if placed_on_level:
            empty_streak = 0
        else:
            empty_streak += 1
            if empty_streak > MAX_EMPTY_LEVELS:
                # Not a blocked storey any more -- the program is asking
                # for something no level can hold.
                break
        level += 1

    # Branch corridors are only as long as the units that ended up on
    # them, which is not known until the level is finished.
    for level_i, branches in level_branches:
        for br in branches:
            total = max(br["offset_l"], br["offset_r"])
            if total > 0:
                _add_corridor(elements, occupied, br["start"],
                              br["start"] + br["dir"].scaled(total),
                              br["dir"], level=level_i)

    # Growth probes one storey beyond the last one it could use, and a
    # blocked storey may have been passed through on the way up. Keep
    # every level the building actually reaches -- a core on an
    # otherwise-empty floor is the stair passing through it -- but drop
    # anything left standing above the topmost room.
    top_level = max((el.level + el.floors - 1
                     for el in elements if el.kind in ("unit", "communal")),
                    default=0)
    elements = [el for el in elements if el.level <= top_level]

    # Walls are resolved ONCE per storey, rather than each element
    # walking its own four edges. Where two elements meet, the shared
    # stretch becomes a single wall they both reference -- see
    # walls.resolve_walls for why this needs interval decomposition and
    # not just duplicate removal.
    walls, dropped_cm, dropped_count = _resolve_walls_per_level(elements)
    for el, ids in zip(elements, walls_by_owner(walls, len(elements))):
        el.wall_ids = ids

    _assign_growth_steps(elements)

    return FloorPlan(elements=elements, entrance=entrance, core_position=core_pos,
                     unit_counts=unit_counts, walls=walls,
                     dropped_wall_cm=dropped_cm,
                     dropped_wall_count=dropped_count,
                     level_count=max((el.level + el.floors for el in elements),
                                     default=1))
