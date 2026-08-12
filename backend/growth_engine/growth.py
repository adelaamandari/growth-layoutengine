"""
growth.py
Entrance -> corridor -> core -> branching corridors -> rooms, level by
level.

Corridor width is fixed at 170cm throughout (per Adela's rule -- not
derived from the room catalog). Residential units use their REAL
footprint from catalog.py (width_cm along the corridor frontage,
depth_cm extending outward), so different unit types genuinely occupy
different amounts of space, rather than a uniform placeholder module.
Shared spaces (Lobby, Gym, Library, Workspace, SK, SL) remain
flexible-sized single rooms, drawn from the ranges in shared_spaces.py.

OUTDOOR AREAS ARE GROUND, NOT STOREYS
Garden and Playground are placed by the same growth logic -- flush
against a corridor edge, because they have to be reachable -- but they
are not rooms. They enclose nothing, so they build no walls, carry no
frame, and are not floor area. `builds_walls` is the single predicate
that says so, and walls.py, frame.py and diagnostics.py all filter on
it. They are also placed in a separate ground-floor pass AFTER the
building has stacked, and are exempt from `max_branch_cm`: that cap
exists to stop the BUILDING sprawling, and a garden has no upper storey
to be pushed into.

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

from .components import BAY_CM
from .geometry import Point, polygon_contains, polygons_overlap
from .catalog import UnitType, get_unit
from .shared_spaces import SharedSpace, get_shared, is_outdoor
from .walls import Wall, resolve_walls, walls_by_owner

# NOTE ON UNITS: everything in this engine is CENTIMETRES. The constants
# below were originally transcribed straight off the drawings in MM and
# stored in _CM fields, which made the corridor 17m wide and the core a
# 17x17m room. Anything sourced from Rhino (unit footprints, the 300/600
# storey heights) was always correct cm -- only these hand-typed values
# were off, uniformly by 10x.
CORRIDOR_WIDTH_CM = 170.0        # 1.7m total width, walls included
CORRIDOR_HALF = CORRIDOR_WIDTH_CM / 2
# The core holds a LIFT AND AN EMERGENCY STAIR. Vertical circulation
# proper is a separate element -- see STAIR_SIZE_CM below.
#
# It was 170x170 -- 2.9m2, the same square as the corridor is wide.
# PROJECT_SUMMARY has flagged that as an open question since the number
# was first corrected: 2.9m2 cannot take a flight and a landing, let
# alone a lift beside them. Adela settled it by pointing at the Core and
# Stairs components: the core is a real room, not an anchor point.
#
# Adela's dimension is 6x3, stretched to the grid: TWO BAYS of frontage
# on the corridor by ONE BAY deep, 7.2 x 3.6m, 25.9m2. Along the 7.2 the
# emergency stair takes about 5.0 and the lift about 2.2; both clear the
# 3.6 depth (a stair wants 2.5, an 8-person accessible lift 2.4). Same
# area as the 3.6 x 7.2 it replaces, turned through 90 degrees, which is
# the better way round: a core one bay deep sits in a band rather than
# driving two bays back through the rooms behind it.
#
# Whole bays, not a rounded-up dimension, and that is the second reason
# for it: a core on the grid CONTAINS grid nodes, so it always carries
# its own columns. The stair was the worst offender in the support
# report when it was 170 wide and fell between grid lines.
CORE_RUN_CM = 2 * BAY_CM         # frontage on the corridor
CORE_DEPTH_CM = 1 * BAY_CM       # how far it reaches back off it
# Kept because branch starts and the entry run measure from the core's
# centre, and which half depends on which way you leave it.
CORE_RUN_HALF = CORE_RUN_CM / 2
CORE_DEPTH_HALF = CORE_DEPTH_CM / 2

# A lift core is expensive and wants to be rare. Two per storey on a
# site this size, which is Adela's call and the usual one -- you do not
# put a firefighting core every 8 metres. Escape distance is carried by
# the stairs below instead, which is what makes the split worth having.
MAX_CORES_PER_LEVEL = 2

# Vertical circulation proper: a stair, no lift, 3x3 stretched to one
# whole bay. 3.6 x 3.6m is tight for a 3m floor-to-floor and it does
# work -- about 4.25m of going at a 175mm rise, so a switchback with two
# roughly 2.4m flights and a landing between. It would not take a single
# straight flight, which needs the full 5m in one direction.
STAIR_SIZE_CM = 1 * BAY_CM
STAIR_HALF = STAIR_SIZE_CM / 2

# No two stairs closer than this. Looser than the core rule because a
# stair is 13m2 rather than 26 and its whole job is to be near things.
STAIR_MIN_SPACING_CM = 2 * BAY_CM

# No two cores closer than this, centre to centre, on one storey.
#
# core_pitch_cm bounds the walk ALONG a run since its last stair, and
# `last_core` is keyed per (branch, side) -- so the two sides of one
# corridor each keep their own counter and can put a stair opposite a
# stair. Adela caught exactly that: two cores either side of a corridor,
# metres apart, serving the same few rooms twice.
CORE_MIN_SPACING_CM = 4 * BAY_CM

# Deprecated alias. Nothing should read a single "core size" now that it
# is not square; kept so an old import fails loudly at the edit rather
# than silently building a 170 square somewhere.
CORE_SIZE_CM = CORE_RUN_CM
CORE_HALF = CORE_RUN_HALF
ENTRY_CORRIDOR_BAYS_CM = 340.0   # entrance straight run before reaching core (2 bays)

# Shared-space sizes used to live here as a single frontage/depth pair
# for every communal room. They are now per type, in shared_spaces.py,
# because a gym and a shared kitchen are not the same brief -- and
# because the ranges there also carry the indoor/outdoor distinction.

# An outdoor area is a surfaced piece of ground, not a storey. It gets a
# real but token thickness so the massing and OBJ export have a solid to
# extrude rather than a degenerate zero-height box (three.js warns on
# those, and a zero-volume OBJ face is not a thing).
OUTDOOR_HEIGHT_CM = 15.0

# Kinds that enclose space with built walls. Everything that counts
# walls, frames timber, or measures floor area filters on this -- an
# outdoor area is in the plan and in the massing, but it is ground, and
# ground has no perimeter to build. Keeping the test in ONE place is the
# point: walls.py, frame.py and diagnostics.py must agree about what has
# a wall, or verify_walls fails against its own plan.
WALLED_KINDS = ("corridor", "core", "stairs", "unit", "communal")

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
# program becomes a flexible shared space -- a known one gets its brief
# from shared_spaces.py, and an unknown one still becomes a blank room
# rather than an error, which is why a typo builds a box instead of
# failing.
RESIDENTIAL_KEYS = (
    "Studio_A", "Studio_B", "1Bed_A", "1Bed_B",
    "2Bed_A", "2Bed_B", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
)


@dataclass
class PlacedElement:
    kind: str                 # "corridor" | "core" | "stairs" | "unit" | "communal" | "outdoor"
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
    # The site this was grown inside, if any, and anything that ended up
    # outside it. See _audit_site: the armature is placed before any test
    # can run, so "constrained" is a claim that has to be checked rather
    # than assumed.
    boundary: list[Point] | None = None
    off_site: list[str] = field(default_factory=list)
    # The frame the plan was laid out on, (u, v). frame.py needs it: the
    # structural grid has to turn with the building, or its columns march
    # across a rotated plan at an angle to every wall they are meant to
    # stand in.
    axes: tuple[Point, Point] = (Point(1.0, 0.0), Point(0.0, 1.0))


def _rect(p1: Point, p2: Point, p3: Point, p4: Point) -> list[Point]:
    return [p1, p2, p3, p4]


# A stair counts as reached if its footprint comes this close to a
# corridor's. Not zero: the two are placed from different anchors and a
# few cm of float drift is not a missing doorway.
CIRCULATION_TOUCH_CM = 5.0


def _footprint_gap(a: PlacedElement, b: PlacedElement) -> float:
    """Smallest distance between two footprints' outlines, 0 if they touch."""
    def seg(px, py, p1, p2):
        dx, dy = p2.x - p1.x, p2.y - p1.y
        ln = dx * dx + dy * dy
        t = 0.0 if ln == 0 else max(0.0, min(1.0, ((px - p1.x) * dx + (py - p1.y) * dy) / ln))
        return ((px - (p1.x + t * dx)) ** 2 + (py - (p1.y + t * dy)) ** 2) ** 0.5

    best = float("inf")
    for x, y in ((a, b), (b, a)):
        n = len(y.corners)
        for c in x.corners:
            best = min(best, min(seg(c.x, c.y, y.corners[i], y.corners[(i + 1) % n])
                                 for i in range(n)))
    return best


def builds_walls(el: PlacedElement) -> bool:
    """Does this element have a physical perimeter to build? False for
    outdoor areas, which are ground rather than rooms. See WALLED_KINDS."""
    return el.kind in WALLED_KINDS


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
    # Outdoor areas rank last: the ground around a building is laid out
    # after the building, and the animation reads better for it.
    rank = {"corridor": 1, "core": 0, "stairs": 1, "unit": 2, "communal": 2, "outdoor": 3}
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


def _on_site(corners, boundary) -> bool:
    """Does this footprint lie inside the site?

    `boundary` is None when growth is unconstrained, which is still the
    library default -- the engine describes a building, and not every
    caller has a site. The API supplies one.

    Applied at EVERY level, not just the ground. A cantilever over the
    boundary is a real building move and this rules it out; that is the
    conservative reading, and the one to revisit first if the massing
    wants to reach out over the pavement.
    """
    return boundary is None or polygon_contains(corners, boundary)


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


# The structural grid frame.py stands its columns on, named here because
# this module owns the two things that anchor it: the entrance, which is
# its origin, and the plan's axes. frame.py takes GRID_CM from the same
# BAY_CM, so there is one number and not two that must agree.
STRUCTURAL_GRID_CM = BAY_CM

# Slide each distributed stair along its run to meet the grid.
#
# OFF, on measurement. It was worth trying -- a stair is the one room
# whose floor really must be held up -- but at the shipped 6-bay entry
# run it makes the structure WORSE, not better: the worst unsupported
# span goes 2.46m -> 6.31m and one element crosses the one-bay limit
# that nothing crosses without it. Sliding forward to meet a grid line
# along the run can push a core to a position no better in the
# perpendicular axis, which is the one the corridor fixes, and it
# displaces everything the run places after it.
#
# Kept rather than deleted because the reasoning is sound and a future
# change to how runs are filled could make it pay. Flip it and re-run
# frame.support_report and diagnostics.access_report before believing
# it helps.
#
#             max->core avg   worst   unsupported   over 1 bay   worst gap
#   off            18.2 m    26.9 m       14.2          0          2.46 m
#   on             18.6 m    23.4 m       10.2          1          6.31 m
SNAP_CORES_TO_GRID = False


def grid_offset_cm(p: Point, origin: Point, axes, pitch: float = STRUCTURAL_GRID_CM) -> float:
    """How far `p` is from the nearest node of the structural grid.

    A column exists only where a grid node falls inside a footprint, so
    this is the difference between a room the frame can hold up and one
    whose floor draws in mid-air. Measured in the plan's own frame, not
    the world's -- the grid turns with the building.
    """
    u, v = axes
    du = (p.x - origin.x) * u.x + (p.y - origin.y) * u.y
    dv = (p.x - origin.x) * v.x + (p.y - origin.y) * v.y
    eu = du - round(du / pitch) * pitch
    ev = dv - round(dv / pitch) * pitch
    return (eu * eu + ev * ev) ** 0.5


def _add_core(elements, occupied, core_pos: Point, level: int = 0, axes=None):
    """The stair, square on the plan's own axes.

    It used to build its square from hardcoded x/y offsets, which was
    invisible while the whole plan was axis-aligned and wrong the moment
    the frame could rotate: every corridor and room turned onto the site
    grid and the core alone stayed square to the page, sitting askew in
    the middle of its own building.
    """
    u, v = axes if axes else (Point(1.0, 0.0), Point(0.0, 1.0))
    c1 = Point(core_pos.x - u.x * CORE_RUN_HALF - v.x * CORE_DEPTH_HALF,
               core_pos.y - u.y * CORE_RUN_HALF - v.y * CORE_DEPTH_HALF)
    c2 = Point(c1.x + u.x * CORE_RUN_CM, c1.y + u.y * CORE_RUN_CM)
    c3 = Point(c2.x + v.x * CORE_DEPTH_CM, c2.y + v.y * CORE_DEPTH_CM)
    c4 = Point(c1.x + v.x * CORE_DEPTH_CM, c1.y + v.y * CORE_DEPTH_CM)
    corners = _rect(c1, c2, c3, c4)
    elements.append(PlacedElement("core", "Core", corners, level=level))
    _reserve(occupied, level, 1, corners)


def _try_add_unit(elements, occupied, edge_start: Point, edge_end: Point,
                   perp_dir: Point, side: int, unit: UnitType,
                   level: int = 0, boundary=None) -> bool:
    out = perp_dir.scaled(side)
    c1, c2 = edge_start, edge_end
    c3 = edge_end + out.scaled(unit.depth_cm)
    c4 = edge_start + out.scaled(unit.depth_cm)
    corners = _rect(c1, c2, c3, c4)
    # A duplex has to clear BOTH the storey it stands on and the one it
    # reaches into, or it would grow through the floor above it.
    floors = max(1, int(round(unit.height_cm / LEVEL_HEIGHT_CM)))
    if not _on_site(corners, boundary):
        return False
    if not _is_free(occupied, level, floors, corners):
        return False
    _reserve(occupied, level, floors, corners)
    elements.append(PlacedElement(
        "unit", unit.name, corners, height_cm=unit.height_cm, level=level,
    ))
    return True


def _try_add_shared(elements, occupied, edge_start: Point, edge_end: Point,
                    perp_dir: Point, side: int, spec: SharedSpace, label: str,
                    depth: float, level: int = 0, boundary=None) -> bool:
    """Place one flexible space of the given depth against the corridor.

    Frontage is fixed by the caller -- it is the length the run walks and
    the corridor has to reach -- so the only thing that gives when the
    bay is tight is the DEPTH, shrinking away from the corridor. That is
    the one dimension a shared space can lose without moving anything
    already placed.

    An outdoor area is a pad, not a storey: it takes OUTDOOR_HEIGHT_CM
    and the "outdoor" kind, and everything downstream reads the kind.
    """
    height = OUTDOOR_HEIGHT_CM if spec.is_outdoor else LEVEL_HEIGHT_CM
    shrink = 1.0
    for _attempt in range(7):
        off = perp_dir.scaled(side * depth * shrink)
        c1, c2 = edge_start, edge_end
        c3, c4 = edge_end + off, edge_start + off
        corners = _rect(c1, c2, c3, c4)
        # The shrink loop is what makes a shared space flexible, so the
        # site test belongs INSIDE it: a lobby too deep for the plot
        # should get shallower, not disappear.
        if _on_site(corners, boundary) and _is_free(occupied, level, 1, corners):
            _reserve(occupied, level, 1, corners)
            elements.append(PlacedElement(
                spec.kind, label, corners, height_cm=height, level=level,
            ))
            return True
        shrink *= 0.68
    return False


def _corridor_bay(br: dict, probe: float, length: float) -> list[Point]:
    """The stretch of branch corridor serving one bay, as a rectangle."""
    a = br["start"] + br["dir"].scaled(probe)
    b = br["start"] + br["dir"].scaled(probe + length)
    pd_ = br["pd"]
    return _rect(a + pd_.scaled(-CORRIDOR_HALF), b + pd_.scaled(-CORRIDOR_HALF),
                 b + pd_.scaled(CORRIDOR_HALF), a + pd_.scaled(CORRIDOR_HALF))


def _make_branches(core_pos: Point, axes=None) -> list[dict]:
    """The three orthogonal arms leaving the core: straight, left, right.

    `axes` is the frame the whole plan is laid out on: (u, v), a unit
    pair with v the "north" the entry run comes down from and u the
    cross direction. Default is the world frame, which is what this
    engine always used. Passing a rotated pair turns the ENTIRE armature
    onto a site grid without changing any of the growth logic -- the
    branches are still orthogonal to each other, they are just no longer
    orthogonal to the page.
    """
    u, v = axes if axes else (Point(1.0, 0.0), Point(0.0, 1.0))
    branches = []
    for d in (Point(-v.x, -v.y), Point(-u.x, -u.y), u):
        pd_ = Point(-d.y, d.x)
        # Leave from the core's FACE, and the core is no longer square:
        # going along v you clear its depth, along u its frontage. A
        # single CORE_HALF here would have started the v branch 180cm
        # inside a core that reaches 360.
        half = CORE_DEPTH_HALF if abs(d.x * u.x + d.y * u.y) < 0.5 else CORE_RUN_HALF
        branches.append({
            "dir": d, "pd": pd_, "start": core_pos + d.scaled(half),
            "offset_l": 0.0, "offset_r": 0.0, "depth": 0,
        })
    return branches


def _spawn_tertiary(branches: list[dict], pitch_cm: float,
                    reach_cm: float) -> list[dict]:
    """Sub-branches off the primary arms, perpendicular to them.

    The third order of circulation: the spine runs one way, its arms
    cross it, and these run back parallel to the spine again. That is
    what turns three loose corridors into a network -- without them a
    run can only ever be double-loaded, so the plan is a set of strips
    and the depth of the plot beyond one unit either side of an arm is
    unreachable.

    Spawned UP FRONT, at a fixed pitch, not after the primaries have
    filled. Spawning them late looked more informed -- their positions
    could follow how far each arm actually ran -- but by then the strip a
    tertiary corridor needs is full of the units that attached to its
    parent's side, so the corridor was laid straight through them: eight
    overlapping elements and a failed wall check. Created with the
    primaries, every run competes through the same occupancy test and
    the conflict cannot arise.

    Both sides of every parent, at a fixed pitch. A tertiary starts on
    the parent corridor's EDGE, not its centreline, so the two corridors
    meet rather than overlap.
    """
    out: list[dict] = []
    for br in branches:
        if br.get("depth", 0) != 0:
            continue                      # no fourth order
        t = pitch_cm
        while t <= reach_cm:
            anchor = br["start"] + br["dir"].scaled(t)
            for sign in (-1, 1):
                d = br["pd"].scaled(sign)
                out.append({
                    "dir": d, "pd": Point(-d.y, d.x),
                    "start": anchor + d.scaled(CORRIDOR_HALF),
                    "offset_l": 0.0, "offset_r": 0.0, "depth": 1,
                    # Which run this hangs off, and how far along it. The
                    # parent has to be built out at least this far or the
                    # two never meet -- see the corridor emit below.
                    "parent": br, "anchor_t": t,
                })
            t += pitch_cm
    return out


def _grow_outdoor(elements, occupied, branches: list[dict], keys: list[str],
                  unit_counts: dict[str, int], max_branch_cm: float,
                  boundary=None) -> None:
    """
    Lay the open-air areas on the ground, past whatever the built program
    left on each run.

    Two things make this a separate pass rather than another case inside
    the main loop.

    It is GROUND FLOOR ONLY. The main loop moves up a storey when a level
    fills, which is right for rooms and meaningless for a garden -- there
    is no storey above the ground for open ground to go to. Letting an
    outdoor entry take part in that loop meant a garden that did not fit
    on level 0 either vanished or stalled the rest of the program behind
    it.

    It is EXEMPT from max_branch_cm. That cap decides how compact the
    BUILDING is: a unit that would overshoot it starts the next storey
    instead. Open ground has no next storey, and a garden squeezed
    against the core is not a better garden, so the runs may reach
    further out here. The branch corridors are measured after this pass,
    so a corridor grows to MEET the garden rather than stopping short of
    it -- which is what makes the garden reachable.
    """
    runs = [(br, side) for br in branches for side in (-1, 1)]
    reach = max_branch_cm * 3
    bi = 0
    for key in keys:
        spec = get_shared(key)
        frontage = random.uniform(*spec.frontage_cm)
        depth = random.uniform(*spec.depth_cm)
        placed = False
        for attempt in range(len(runs)):
            br, side = runs[(bi + attempt) % len(runs)]
            offset_key = "offset_l" if side == -1 else "offset_r"
            probe = br[offset_key]
            while probe + frontage <= reach and not placed:
                bay_start = br["start"] + br["dir"].scaled(probe)
                bay_end = br["start"] + br["dir"].scaled(probe + frontage)
                edge_start = bay_start + br["pd"].scaled(side * CORRIDOR_HALF)
                edge_end = bay_end + br["pd"].scaled(side * CORRIDOR_HALF)
                # Exempt from max_branch_cm, NOT from the site. Open
                # ground still has to be on the plot -- a garden on the
                # neighbour's land is not a garden.
                if _try_add_shared(elements, occupied, edge_start, edge_end,
                                   br["pd"], side, spec, key, depth, level=0,
                                   boundary=boundary):
                    br[offset_key] = probe + frontage
                    unit_counts[key] = unit_counts.get(key, 0) + 1
                    bi += attempt + 1
                    placed = True
                    break
                probe += PROBE_STEP_CM
            if placed:
                break


def _resolve_walls_per_level(elements: list[PlacedElement]):
    """
    Resolve walls one storey at a time and renumber into a single list.

    Resolving every element together would be wrong now that the plan
    stacks: a level-1 corridor sits exactly above the level-0 one, and
    `resolve_walls` works in plan, so it would merge two real walls into
    one and halve the take-off.

    An element is grouped into EVERY storey it occupies, not just the one
    it stands on. Grouping a duplex by its base level alone -- on the
    reasoning that its walls are simply 600cm tall -- quietly reintroduced
    the duplication this function exists to prevent: a duplex spanning
    levels 0-1 and an ordinary unit on level 1 share a plan line, but they
    never met in the same resolve group, so each built its own copy of it.
    177m of wall on the default plan, built twice.

    It passed verification because diagnostics.shared_boundaries skipped
    the same pairs, by the same el.level test. Two independent modules
    agreeing is only evidence when they do not share the assumption -- and
    that one they did. Both now work per occupied storey.

    Outdoor areas are skipped: they have no perimeter to build, and
    handing their edges to resolve_walls would put a timber wall around
    a garden and count it in the take-off. Their indices are still
    global, so the walls' owner ids stay valid against `elements`.

    Returns (walls, dropped_cm, dropped_count) with owners as global
    indices into `elements`, exactly as the single-group version did.
    """
    by_level: dict[int, list[int]] = {}
    for i, el in enumerate(elements):
        if not builds_walls(el):
            continue
        for lv in range(el.level, el.level + max(1, el.floors)):
            by_level.setdefault(lv, []).append(i)

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
                level=level,
            ))
        dropped_cm += res.dropped_cm
        dropped_count += res.dropped_count
    return walls, dropped_cm, dropped_count


def generate_floorplan(program: list[str], seed: int | None = None,
                       max_branch_cm: float = MAX_BRANCH_CM,
                       max_levels: int = MAX_LEVELS,
                       boundary: list[Point] | None = None,
                       entrance: Point | None = None,
                       axes: tuple[Point, Point] | None = None,
                       branch_depth: int = 1,
                       tertiary_pitch_cm: float = 1200.0,
                       entry_run_cm: float = ENTRY_CORRIDOR_BAYS_CM,
                       core_pitch_cm: float | None = None,
                       reserved: list[list[Point]] | None = None) -> FloorPlan:
    """
    program: ordered list of type keys to place, e.g.
        ["Lobby", "Studio_A", "SK", "2Bed_A", "Gym", "Garden"]
    Residential entries must match names in catalog.UNIT_CATALOG.
    Everything else is a flexible shared space: a key in
    shared_spaces.SHARED_CATALOG takes that entry's size range, and any
    other key still becomes a blank flexible room.

    Outdoor keys (Garden, Playground) are pulled out of the program and
    placed together on the ground after the building has grown -- see
    _grow_outdoor for why. Their order relative to each other is kept;
    their position among the rooms is not, because they are not on a
    storey to be interleaved with.

    max_branch_cm caps how far a branch runs from the core. When no run
    on the current level can take the next unit within that cap, growth
    moves up a storey rather than reaching further out -- this is the
    knob that decides whether the composition sprawls or stacks. Pass a
    very large value for the old single-storey behaviour.

    boundary is the site, as a polygon in the SAME frame as everything
    else -- centimetres, with the entrance at the origin. Nothing is
    placed that does not lie wholly inside it, at any level. Default None
    keeps the engine site-agnostic: it describes a building, and not
    every caller has a plot.

    The boundary and max_branch_cm do different jobs and both stay on.
    The cap decides compactness -- how far a run reaches before the
    program goes up a storey. The boundary decides possibility. On a
    tight site the boundary usually binds first, and the effect is the
    one you want: the building stops spreading and starts stacking,
    because that is the only direction left.
    """
    if seed is not None:
        random.seed(seed)

    # Ground and building grow separately. Order within each half is
    # preserved -- only the interleaving between them is dropped.
    outdoor_program = [k for k in program if is_outdoor(k)]
    program = [k for k in program if not is_outdoor(k)]

    elements: list[PlacedElement] = []
    # Occupancy is per level: a unit only has to clear what is actually
    # on its own storey.
    occupied: dict[int, list[list[Point]]] = {}

    # COURTYARDS. Reserved before anything is placed, on EVERY storey --
    # a courtyard open to the sky is not a hole in the ground floor with
    # flats over it. Growth simply cannot see this ground, so the
    # building forms around it rather than being cut out of afterwards.
    for block in (reserved or []):
        for lv in range(max_levels + 2):
            occupied.setdefault(lv, []).append(block)
    unit_counts: dict[str, int] = {}

    # The frame the plan is laid out on. Defaults to the world axes with
    # the entrance at the origin, which is what this engine always did;
    # passing either turns the whole armature without touching the growth
    # logic below. `entrance` is where the front door is -- on a real
    # site that belongs on a street, not at an arbitrary interior point.
    u_ax, v_ax = axes if axes else (Point(1.0, 0.0), Point(0.0, 1.0))
    entrance = entrance if entrance is not None else Point(0, 0)
    entry_dir = Point(-v_ax.x, -v_ax.y)
    # How far in the core sits. Two bays by default -- a front door and
    # a stair right behind it. On a long plan that leaves the stair at
    # one END of the building, so every unit is reached by walking the
    # whole spine and the far ones only through everything before them;
    # the site strategy pushes it into the body of the plan instead.
    core_pos = entrance + entry_dir.scaled(entry_run_cm)
    # The entry run belongs to the ground floor only. Upper storeys
    # reach the branches through the core, which is the stair.
    _add_corridor(elements, occupied, entrance,
                  core_pos + entry_dir.scaled(-CORE_DEPTH_HALF), entry_dir, level=0)

    qi = 0
    level = 0
    # Vertical circulation, decided once on level 0 and repeated up the
    # building. (kind, label, corners) -- see where it is replayed below.
    vert_slots: list[tuple[str, str, list]] = []
    level_branches: list[tuple[int, list[dict]]] = []
    max_iterations = len(program) * 12  # safety valve against infinite retry loops
    iterations = 0

    empty_streak = 0
    while qi < len(program) and level < max_levels and iterations < max_iterations:
        # The core is the stair, so it is built on every storey the
        # building passes through -- including one that ends up holding
        # only the upper halves of the duplexes below. Storeys above the
        # topmost occupied one are pruned after the loop.
        _add_core(elements, occupied, core_pos, level=level, axes=(u_ax, v_ax))

        # Every other lift core and stair, in the position it was given
        # on level 0. Vertical circulation has to STACK: a shaft decided
        # afresh on each storey is a lift that moves sideways between
        # floors and a stair you cannot climb. The main core always
        # stacked, because it is placed from the same core_pos each time;
        # the ones the run walk found did not, and landed metres apart
        # storey to storey.
        #
        # Placed BEFORE the units on this level rather than during the
        # walk, so the rooms grow around the circulation instead of the
        # circulation squeezing into what the rooms left. Where an upper
        # storey has stepped back past a slot it simply is not there, and
        # that shaft serves the storeys below it -- which is a real
        # building, not a failure.
        for kind_v, label_v, poly_v in vert_slots:
            if _on_site(poly_v, boundary) and _is_free(occupied, level, 1, poly_v):
                _reserve(occupied, level, 1, poly_v)
                elements.append(PlacedElement(kind_v, label_v, poly_v, level=level))

        branches = _make_branches(core_pos, (u_ax, v_ax))
        if branch_depth >= 2:
            branches.extend(_spawn_tertiary(branches, tertiary_pitch_cm,
                                            max_branch_cm))
        level_branches.append((level, branches))

        # Runs in the order they should fill: both sides of one branch
        # before moving to the next, so a corridor is double-loaded
        # rather than three arms each growing a single-loaded tail.
        runs = [(br, side) for br in branches for side in (-1, 1)]
        bi = 0
        placed_on_level = False
        # Distance along each run since its last stair. One core at the
        # centre means the far end of a long plan is reached only by
        # walking everything between; a stair every `core_pitch_cm`
        # bounds that walk. Keyed per run because the two sides of a
        # corridor are served independently.
        last_core: dict[tuple[int, int], float] = {}

        while qi < len(program) and iterations < max_iterations:
            iterations += 1
            type_key = program[qi]
            is_residential = type_key in RESIDENTIAL_KEYS
            unit = get_unit(type_key) if is_residential else None
            # A shared space is flexible, so its size is drawn here --
            # once per program entry, not once per probe, or the run
            # would be walking a different length at every step. The
            # frontage is what the run consumes; the depth is what
            # _try_add_shared gives back when the bay is tight.
            spec = None if is_residential else get_shared(type_key)
            depth = 0.0
            if spec is not None:
                length = random.uniform(*spec.frontage_cm)
                depth = random.uniform(*spec.depth_cm)
            else:
                length = unit.width_cm

            # A stair wherever a run has gone `core_pitch_cm` without
            # one. Placed as a bay ON the corridor edge, like a unit,
            # rather than on the centreline: a core straddling the
            # corridor would be overlapped by it when the corridor is
            # emitted, and a stair you cannot walk past is a dead end.
            if core_pitch_cm and level == 0:
                for br_c, side_c in runs:
                    okey = "offset_l" if side_c == -1 else "offset_r"
                    rkey = (id(br_c), side_c)
                    if br_c[okey] - last_core.get(rkey, 0.0) < core_pitch_cm:
                        continue
                    # Slide the stair ALONG its run to wherever it comes
                    # closest to a grid node, before committing to the
                    # offset the pitch counter happened to land on. A
                    # 170cm core between grid lines carries no column and
                    # its floor draws unsupported; a core is the one room
                    # that must not, because it is the stair.
                    #
                    # Along the run only -- the perpendicular position is
                    # the corridor's and moving off it would leave a
                    # stair you cannot reach. That means this REDUCES the
                    # gap rather than always closing it: the corridor
                    # centreline may simply not pass near a node, and
                    # frame.support_report says so when it does not.
                    # FORWARD only. This offset is the run's fill cursor,
                    # not a free coordinate: everything behind it is
                    # already built. Searching backwards as well looked
                    # harmless and cost 4 of 8 test seeds their stair
                    # spacing -- the rewound core collided with what was
                    # already there, failed _is_free, and simply was not
                    # placed, so the worst walk went 20.7m -> 41.2m. It
                    # also left near-miss slivers that broke the wall
                    # invariant on seed 11. One pitch forward reaches
                    # every alignment anyway, because nodes repeat.
                    base_off = br_c[okey]
                    best_off, best_gap = base_off, None
                    step = STRUCTURAL_GRID_CM / 12.0
                    k = 0
                    while SNAP_CORES_TO_GRID and k * step <= STRUCTURAL_GRID_CM:
                        for cand_off in (base_off + k * step,):
                            m0 = br_c["start"] + br_c["dir"].scaled(cand_off + CORE_RUN_HALF)
                            centre = m0 + br_c["pd"].scaled(
                                side_c * (CORRIDOR_HALF + CORE_DEPTH_HALF))
                            g = grid_offset_cm(centre, entrance, (u_ax, v_ax))
                            if best_gap is None or g < best_gap:
                                best_off, best_gap = cand_off, g
                        k += 1
                    br_c[okey] = best_off
                    a0 = br_c["start"] + br_c["dir"].scaled(br_c[okey])
                    a1 = br_c["start"] + br_c["dir"].scaled(br_c[okey] + CORE_RUN_CM)
                    e0 = a0 + br_c["pd"].scaled(side_c * CORRIDOR_HALF)
                    e1 = a1 + br_c["pd"].scaled(side_c * CORRIDOR_HALF)
                    out_c = br_c["pd"].scaled(side_c)
                    # A CORE if the storey has not had its two yet,
                    # otherwise a STAIR. The lift core is the expensive
                    # one and is capped; escape distance is carried by
                    # stairs, which is the whole point of splitting them.
                    n_cores = sum(1 for e in elements
                                  if e.kind == "core" and e.level == level)
                    if n_cores < MAX_CORES_PER_LEVEL:
                        kind_c, label_c = "core", "Core"
                        run_c, depth_c = CORE_RUN_CM, CORE_DEPTH_CM
                    else:
                        kind_c, label_c = "stairs", "Stairs"
                        run_c, depth_c = STAIR_SIZE_CM, STAIR_SIZE_CM
                    a1 = br_c["start"] + br_c["dir"].scaled(br_c[okey] + run_c)
                    e1 = a1 + br_c["pd"].scaled(side_c * CORRIDOR_HALF)
                    cc = _rect(e0, e1,
                               e1 + out_c.scaled(depth_c),
                               e0 + out_c.scaled(depth_c))
                    # Not within CORE_MIN_SPACING_CM of a stair this
                    # storey already has. core_pitch_cm only bounds the
                    # walk along ONE run and keeps its count per side, so
                    # without this the two sides of a corridor put a
                    # stair opposite a stair -- two cores metres apart
                    # serving the same rooms, which is what Adela saw.
                    ccx = sum(c.x for c in cc) / len(cc)
                    ccy = sum(c.y for c in cc) / len(cc)
                    # Spacing is measured against the SAME kind. Two
                    # lift cores must not huddle; a stair next to a core
                    # is fine and often right, because the stair is there
                    # to shorten a walk the core cannot.
                    crowded = False
                    for other in elements:
                        if other.kind != kind_c or other.level != level:
                            continue
                        ox_ = sum(c.x for c in other.corners) / len(other.corners)
                        oy_ = sum(c.y for c in other.corners) / len(other.corners)
                        gap_min = (CORE_MIN_SPACING_CM if kind_c == "core"
                                   else STAIR_MIN_SPACING_CM)
                        if ((ccx - ox_) ** 2 + (ccy - oy_) ** 2) ** 0.5 < gap_min:
                            crowded = True
                            break
                    if (not crowded and _on_site(cc, boundary)
                            and _is_free(occupied, level, 1, cc)):
                        _reserve(occupied, level, 1, cc)
                        elements.append(PlacedElement(kind_c, label_c, cc,
                                                      level=level))
                        vert_slots.append((kind_c, label_c, cc))
                        br_c[okey] += run_c
                    last_core[rkey] = br_c[okey]

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

                    # The corridor that reaches this bay has to be on the
                    # site too, or a unit can end up legitimately inside
                    # the boundary while the only way to it crosses out.
                    # Checked per bay rather than for the whole run: the
                    # branch corridor is emitted later as the union of
                    # the bays that were actually used.
                    if not _on_site(_corridor_bay(br, probe, length), boundary):
                        probe += PROBE_STEP_CM
                        continue

                    if is_residential:
                        ok = _try_add_unit(elements, occupied, edge_start, edge_end,
                                           br["pd"], side, unit, level=level,
                                           boundary=boundary)
                    else:
                        ok = _try_add_shared(elements, occupied, edge_start, edge_end,
                                             br["pd"], side, spec, type_key,
                                             depth, level=level, boundary=boundary)
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

    # Open ground, on the ground floor, before the branch corridors are
    # measured -- so a corridor reaching a garden actually reaches it. A
    # program of nothing but outdoor entries never entered the loop
    # above and so has no armature yet; it still needs the core and the
    # branches to attach to.
    if outdoor_program:
        ground = next((brs for lv, brs in level_branches if lv == 0), None)
        if ground is None:
            _add_core(elements, occupied, core_pos, level=0, axes=(u_ax, v_ax))
            ground = _make_branches(core_pos, (u_ax, v_ax))
            level_branches.append((0, ground))
        _grow_outdoor(elements, occupied, ground, outdoor_program,
                      unit_counts, max_branch_cm, boundary=boundary)

    # Branch corridors are only as long as the units that ended up on
    # them, which is not known until the level is finished.
    #
    # A run may have STEPPED PAST a blocked bay, so the emitted corridor
    # can cover ground no bay test ever saw. On a site with a diagonal
    # edge that stretch can fall outside, so the length is trimmed back
    # to what fits rather than assumed. Trimming can only shorten a
    # corridor to units it already reaches, never orphan one: every unit
    # was placed at an offset whose own corridor bay tested on-site.
    for level_i, branches in level_branches:
        # A CONNECTED NETWORK, not a set of strips.
        #
        # A branch corridor is only as long as the units that ended up on
        # it. A tertiary hangs off its parent at a fixed distance, and
        # that distance is often FURTHER than the parent's own units
        # reached -- so the parent was built short, the tertiary started
        # in mid-air, and the plan came out as three to five disconnected
        # pieces of circulation with no way between them.
        #
        # So each parent is extended to reach the furthest child that
        # actually took anything. The corridor exists to connect what was
        # built; its length has to answer to the children as well as to
        # its own bays.
        for br in branches:
            if br.get("depth", 0) != 0:
                continue
            for child in branches:
                if child.get("parent") is not br:
                    continue
                if max(child["offset_l"], child["offset_r"]) <= 0:
                    continue          # child took nothing; nothing to meet
                reach = child["anchor_t"]
                if reach > br["offset_l"] and reach > br["offset_r"]:
                    br["offset_l"] = max(br["offset_l"], reach)

        for br in branches:
            total = max(br["offset_l"], br["offset_r"])

            # A corridor must REACH the stairs standing on it. This runs
            # last, after every unit and stair on the run is placed, and
            # it used to be trimmed purely for fit -- so a stair at 30m
            # with its corridor trimmed back to 12m was a stair you could
            # see and not walk to. 15 of 24 on the default plan.
            #
            # Circulation sitting on this run sets a floor for the trim.
            # The perpendicular distance is checked too, or a stair on a
            # PARALLEL run further out would drag this corridor across
            # the building to reach something that was never on it.
            reach_for_circulation = 0.0
            for el in elements:
                if el.level != level_i or el.kind not in ("core", "stairs"):
                    continue
                n = len(el.corners)
                ex = sum(c.x for c in el.corners) / n
                ey = sum(c.y for c in el.corners) / n
                dx, dy = ex - br["start"].x, ey - br["start"].y
                along = dx * br["dir"].x + dy * br["dir"].y
                perp = abs(dx * br["pd"].x + dy * br["pd"].y)
                if along <= 0:
                    continue
                span = CORRIDOR_HALF + max(CORE_DEPTH_CM, STAIR_SIZE_CM) / 2 + 20.0
                if perp <= span:
                    reach_for_circulation = max(reach_for_circulation, along)
            total = max(total, reach_for_circulation)

            # Trimmed back until it is BOTH on the site and clear of what
            # is already built. The free test is new and matters for the
            # tertiary runs: three corridors radiating from a core cannot
            # foul each other, but a network of them can.
            #
            # The reach above is a TARGET, not a floor. Making it a floor
            # -- refusing to trim below it -- was tried and is exactly
            # wrong: it drives the corridor through whatever is in the
            # way and off the site, because those two tests are the only
            # thing stopping it. That produced wall-check deltas of 6-16m
            # on every seed and elements off the plot. A corridor that
            # cannot legally reach its stair means the STAIR is in the
            # wrong place, and the fix is to drop the stair, below.
            while total > 0 and not (
                    _on_site(_corridor_bay(br, 0.0, total), boundary)
                    and _is_free(occupied, level_i, 1,
                                 _corridor_bay(br, 0.0, total))):
                total -= PROBE_STEP_CM
            if total > 0:
                _add_corridor(elements, occupied, br["start"],
                              br["start"] + br["dir"].scaled(total),
                              br["dir"], level=level_i)

    # A stair the corridors never reached is not a stair. Corridors are
    # emitted after the rooms and trimmed to what will legally fit, so a
    # stair placed at a large offset can end up stranded when its run is
    # cut back behind it -- 15 of 24 on the default plan, worst 30m from
    # anything you could walk on.
    #
    # Dropped rather than reached for. The corridor cannot be driven out
    # to it without going through a room or off the plot, so the stair is
    # in the wrong place, and removing it is the honest repair. Whole
    # SHAFT at a time, every storey of it: a stair present on levels 0-1
    # and missing on 2 is worse than no stair, because it reads as
    # continuous on the drawing.
    def _stranded_shafts():
        corridors = [e for e in elements if e.kind == "corridor"]
        bad = set()
        for el in elements:
            if el.kind not in ("core", "stairs"):
                continue
            here = [c for c in corridors if c.level == el.level]
            if not any(_footprint_gap(el, c) <= CIRCULATION_TOUCH_CM for c in here):
                # Keyed on plan position, which is what a shaft IS -- the
                # same square on every storey it passes through.
                n = len(el.corners)
                bad.add((round(sum(c.x for c in el.corners) / n),
                         round(sum(c.y for c in el.corners) / n)))
        return bad

    stranded = _stranded_shafts()
    if stranded:
        def _key(el):
            n = len(el.corners)
            return (round(sum(c.x for c in el.corners) / n),
                    round(sum(c.y for c in el.corners) / n))
        elements = [el for el in elements
                    if el.kind not in ("core", "stairs") or _key(el) not in stranded]

    # Growth probes one storey beyond the last one it could use, and a
    # blocked storey may have been passed through on the way up. Keep
    # every level the building actually reaches -- a core on an
    # otherwise-empty floor is the stair passing through it -- but drop
    # anything left standing above the topmost room.
    top_level = max((el.level + el.floors - 1
                     for el in elements
                     if el.kind in ("unit", "communal", "outdoor")),
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

    # The entrance run and the core are laid down before any placement
    # test can run -- they ARE the thing everything else is placed
    # against -- so if the origin sits too near an edge they can end up
    # off the plot with nothing to stop them. Audited rather than
    # trusted, and reported rather than raised: a plan that pokes over
    # the line is still worth looking at, and the caller should be the
    # one to decide it is unacceptable.
    off_site = [f"{el.label} (L{el.level})" for el in elements
                if not _on_site(el.corners, boundary)]

    return FloorPlan(elements=elements, entrance=entrance, core_position=core_pos,
                     unit_counts=unit_counts, walls=walls,
                     dropped_wall_cm=dropped_cm,
                     dropped_wall_count=dropped_count,
                     level_count=max((el.level + el.floors for el in elements),
                                     default=1),
                     boundary=boundary, off_site=off_site,
                     axes=(u_ax, v_ax))
