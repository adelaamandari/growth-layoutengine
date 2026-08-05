"""
frame.py
The timber FRAME: the real surveyed components standing on a regular
structural grid, ordered by parasitic growth outward and upward from
the entrance.

WHY THIS IS NOT THE MASSING VIEW
massing.py answers "what volume does this building occupy". This module
answers "what gets built" -- columns at the grid nodes, beams spanning
between them, a deck at each storey, and the walls infilled between the
bays.

THE GRID IS INDEPENDENT OF THE ROOMS
Columns used to stand wherever a wall happened to end, which meant they
only lined up vertically by accident. They now stand at every
intersection of a 360cm grid that lies inside the building, whether or
not there is a wall there -- so some land inside rooms, and the walls
become infill between bays. That is the whole point: a column is only a
vertical system if the SAME plan position carries through every storey,
and the only way to guarantee that is to derive it from the grid rather
than from each level's walls.

    the grid is anchored at the entrance (0, 0), the growth seed
    a node exists where its grid point falls inside the plan on any level
    its column runs UNBROKEN from the ground to the top of the highest
      level that contains it -- through any storey that happens not to,
      because a column with a gap in it is not a column

360 is not a round number chosen for convenience. The Beam A assembly
in components.glb is 359.99 x 359.99 and its arm runs SA-SB-SC out to
180cm from the node centre, so the full span node to node is 360 and
the sequence across it is N + SA + SB + SC + SB + SA + N. See
components.py, which walks exactly that.

THE FOUR PHASES OF A RING
A RING is one step of the growth front, out and up together:

    ring = grid distance from the entrance node + storeys climbed

and each ring builds in the order the thing is actually assembled:

    step 4r + 0   columns rise through this storey
    step 4r + 1   primary beams span the grid lines between them
    step 4r + 2   the floor deck lands on those beams
    step 4r + 3   the walls infill between the bays

The column assembly's 38 members sit at distinct heights (25, 65,
70.75, 115 ... 270.75), so binning them by storey makes a column rise
band by band rather than appearing whole.

COURSES: FILLING A WALL RATHER THAN OUTLINING IT
Wall infill is not one beam at the ceiling. `course_cm` divides each
storey into that many horizontal courses and repeats the component walk
at each one, so a wall fills with timber the way it does in the
reference render. The storey is always divided a WHOLE number of times,
so the ceiling course lands exactly on the storey line. Primary grid
beams are not coursed -- there is one at each storey line, because that
is the structure rather than the infill.

WHAT THE SOURCE AND THE ENGINE STILL DISAGREE ABOUT
BAY SIZE OF THE CAPITAL. The woven joint assembly is 240x240, which
fits comfortably inside a 360 grid -- but it is still off by default
and its overlap is still counted, because nothing has confirmed it
belongs at every node rather than only at the primary ones.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import atan2, hypot

from .components import BAY_CM, BAY_LENGTHS, BAY_NAMES
from .glb_import import load_catalog
from .growth import FloorPlan

# Two N nodes within this distance are the same physical node. Wall ends
# meeting at a junction are computed from different elements, so they
# land a hair apart.
NODE_CLUSTER_CM = 25.0

STOREY_CM = 300.0

# The structural grid. Surveyed off the Beam A assembly -- see
# components.BAY_CM, which this deliberately reuses rather than
# redeclaring, so the grid and the wall walk can never disagree.
GRID_CM = BAY_CM

# A grid point this far outside an element still counts as inside it.
# Columns belong on the building line, and a grid point landing exactly
# on a wall face would otherwise fall out through float noise.
GRID_TOL_CM = 1.0

# The floor deck. 10cm is the thickness of every surveyed member.
FLOOR_CM = 10.0

# No column stands outside the volume. Where the massing runs past the
# last column, the frame reaches the building line with a HALF SPAN --
# a beam cantilevering out and stopping, rather than another column
# planted in open air with a full bay run out to it. Snapping columns to
# the nearest gridline put 1792 post members up to 195cm outside the
# massing, which is what this replaces.
STUB_CM = GRID_CM / 2

# A stub shorter than this is not worth building -- the massing edge is
# effectively already at the column.
MIN_STUB_CM = 60.0

# Vertical pitch of the beam courses that fill a wall. 100cm is the
# source file's own 100mm grid times ten -- three courses to a 300
# storey. build_frame defaults to STOREY_CM instead, i.e. the single
# ceiling course, so the Frame view is unaffected unless asked.
COURSE_CM = 100.0

# Used only if component_exports/components.json is absent. Regenerate
# it with `python -m growth_engine.glb_import <file>.glb`.
_FALLBACK = {
    "catalog": {
        "N": {"length_cm": 60.0, "width_cm": 60.0, "thickness_cm": 10.0},
        "SA": {"length_cm": 70.0, "width_cm": 20.0, "thickness_cm": 10.0},
        "SB": {"length_cm": 80.0, "width_cm": 20.0, "thickness_cm": 10.0},
        "SC": {"length_cm": 60.0, "width_cm": 20.0, "thickness_cm": 10.0},
    },
    "assemblies": {},
}

_DATA = load_catalog() or _FALLBACK
CATALOG: dict[str, dict] = _DATA.get("catalog") or _FALLBACK["catalog"]
ASSEMBLIES: dict[str, dict] = _DATA.get("assemblies") or {}
HAS_REAL_COMPONENTS = bool(ASSEMBLIES)


@dataclass(frozen=True)
class FrameMember:
    """One drawn timber member: an axis-aligned box rotated about the
    vertical axis by `angle`. Centre and size are both in cm."""
    # "post"   the four-post column bundle at a grid node
    # "plate"  its 60x60 connector, one per storey
    # "beam"   a primary member spanning a grid line
    # "infill" a wall member, coursed between the bays
    # "floor"  a storey deck
    # "lacing" the woven capital, only when joint_blocks is on
    kind: str
    component: str       # catalog name, or the assembly part it came from
    cx: float
    cy: float
    cz: float
    sx: float
    sy: float
    sz: float
    angle: float
    growth_step: int
    node_id: int         # -1 for beams
    # Which end of a beam stays put while it extends: -1 anchors the
    # start end, +1 the far end. Set so a beam grows OUT of the column
    # nearer the seed. Unused for members that rise vertically.
    grow_sign: int = -1


@dataclass(frozen=True)
class FrameNode:
    """One intersection of the structural grid that falls inside the
    building. Its column is continuous: base_cm is always the ground."""
    id: int
    x: float
    y: float
    base_cm: float
    height_cm: float
    # How many of the four grid neighbours also carry a column, i.e. how
    # many primary beams arrive here.
    wall_count: int
    axis_count: int
    depth: int
    # Which storeys the plan actually occupies at this node. A column
    # passes through the ones that are missing, but no beam or deck is
    # drawn there.
    levels: tuple[int, ...] = ()

    @property
    def is_junction(self) -> bool:
        """A capital: a T or a cross. Two arriving beams is just a
        corner, not the splayed node in the reference render."""
        return self.wall_count >= 3


@dataclass
class Frame:
    members: list[FrameMember]
    nodes: list[FrameNode]
    growth_steps: int
    step_labels: list[str] = field(default_factory=list)
    length_deviation: dict = field(default_factory=dict)
    joint_overlaps: int = 0
    course_cm: float = STOREY_CM
    grid_cm: float = GRID_CM
    # How many grid lines carry a primary beam on at least one storey.
    span_count: int = 0


def _key(x: float, y: float) -> tuple[int, int]:
    return (round(x / NODE_CLUSTER_CM), round(y / NODE_CLUSTER_CM))


def _storeys(height_cm: float) -> int:
    return max(1, int(round(height_cm / STOREY_CM)))


def _courses_per_storey(course_cm: float) -> int:
    """How many courses a storey divides into. Whole divisions only, so
    the ceiling course always lands on the storey line."""
    return max(1, int(round(STOREY_CM / max(course_cm, 1.0))))


def _levels(height_cm: float, per_storey: int) -> list[tuple[int, float]]:
    """The course heights up a wall as (ordinal, z), counting from the
    ground. With per_storey == 1 this is the single ceiling level per
    storey that the frame drew before courses existed."""
    pitch = STOREY_CM / per_storey
    return [
        (s * per_storey + k, s * STOREY_CM + k * pitch)
        for s in range(_storeys(height_cm))
        for k in range(1, per_storey + 1)
    ]


def _storey_of(z: float) -> int:
    """Which storey a height sits in. The floor slab of level L is at
    exactly L*300 and belongs to level L, not the storey below."""
    return max(0, int(z // STOREY_CM))


def _ring(depth: int, z: float) -> int:
    """How far the growth front has travelled to reach this member:
    grid steps out from the entrance node, plus storeys climbed. Out and
    up are the same currency, so the front is a diagonal shell rather
    than a plan that fills before it rises."""
    return depth + _storey_of(z)


def _step(depth: int, z: float, phase: int) -> int:
    """The growth step of a member. Four phases to a ring, in the order
    the thing is assembled: columns, primary beams, floor deck, infill."""
    return _ring(depth, z) * 4 + phase


PHASE_COLUMN, PHASE_BEAM, PHASE_FLOOR, PHASE_INFILL = 0, 1, 2, 3


def _boxes(plan: FloorPlan) -> list[tuple[int, float, float, float, float, float, float]]:
    """Each element as (level, x0, y0, x1, y1, z0, z1).

    A plan bounding box is enough because growth.py only ever builds
    axis-aligned rectangles -- corridors, cores and units are all laid
    out along the orthogonal branch directions.
    """
    out = []
    for el in plan.elements:
        xs = [c.x for c in el.corners]
        ys = [c.y for c in el.corners]
        z0 = getattr(el, "z0", 0.0)
        out.append((el.level, min(xs), min(ys), max(xs), max(ys),
                    z0, z0 + el.height_cm))
    return out


def _inside(x: float, y: float, box) -> bool:
    _lv, x0, y0, x1, y1, _z0, _z1 = box
    return (x0 - GRID_TOL_CM <= x <= x1 + GRID_TOL_CM
            and y0 - GRID_TOL_CM <= y <= y1 + GRID_TOL_CM)


def _dist_to_box(x: float, y: float, box) -> float:
    """Distance from a point to an element's footprint, 0 if inside."""
    _lv, x0, y0, x1, y1, _z0, _z1 = box
    dx = max(x0 - x, 0.0, x - x1)
    dy = max(y0 - y, 0.0, y - y1)
    return (dx * dx + dy * dy) ** 0.5


def _at_massing(x: float, y: float, boxes, margin: float = GRID_TOL_CM) -> bool:
    """Is this point in the volume? Columns only stand inside it; the
    frame reaches the building line with a half-span stub instead."""
    return any(_dist_to_box(x, y, b) <= margin for b in boxes)


def _reach_to_edge(x: float, y: float, ux: float, uy: float, boxes) -> float:
    """How far the massing continues from a node along one grid
    direction, capped at half a bay. This is how long the stub that
    closes the frame on that side needs to be -- it must reach the
    building line and stop, never overhang it."""
    step = 10.0
    out = 0.0
    d = step
    while d <= STUB_CM:
        if _at_massing(x + ux * d, y + uy * d, boxes):
            out = d
        d += step
    return out


def _partial_bay(length: float) -> list[tuple[str, float]]:
    """The members of a run shorter than a full bay: the bay sequence
    from its start, truncated. A half span comes out as SA + SB + half
    an SC, which is the arm of the surveyed assembly."""
    out: list[tuple[str, float]] = []
    used = 0.0
    for nominal, name in zip(BAY_LENGTHS, BAY_NAMES):
        if used >= length:
            break
        out.append((name, min(nominal, length - used)))
        used += nominal
    return out


def _touches_bays(x: float, y: float, box) -> bool:
    """Does this element reach into any of the four bays meeting at the
    grid node? That is the region a node's column actually carries --
    one bay in each direction -- so it is what decides how tall the
    column has to be."""
    _lv, x0, y0, x1, y1, _z0, _z1 = box
    return (x0 - GRID_CM - GRID_TOL_CM <= x <= x1 + GRID_CM + GRID_TOL_CM
            and y0 - GRID_CM - GRID_TOL_CM <= y <= y1 + GRID_CM + GRID_TOL_CM)


def build_frame(plan: FloorPlan, joint_blocks: bool = False,
                course_cm: float = STOREY_CM) -> Frame:
    """
    Resolve a plan into real components, ordered by parasitic growth.

    Reads only plan.walls -- already deduplicated, so every member here
    is built exactly once -- and plan.elements for heights.

    joint_blocks places the full 240x240 woven capital at every junction.
    Off by default: it is wider than the spacing of most of the plan's
    nodes, so it self-intersects. See the module docstring.

    course_cm is the vertical pitch of the beam courses that fill each
    wall. The default of one course per storey draws the ceiling beam
    and nothing between it, which is the frame as it was before courses
    existed; COURSE_CM (100) fills the wall.
    """
    boxes = _boxes(plan)
    if not boxes:
        return Frame(members=[], nodes=[], growth_steps=0)

    # --- the grid ----------------------------------------------------
    # Anchored at the entrance, which is the growth seed and the origin
    # of the whole plan, so the grid is a property of the building
    # rather than of its bounding box.
    ox, oy = plan.entrance.x, plan.entrance.y
    min_x = min(b[1] for b in boxes)
    min_y = min(b[2] for b in boxes)
    max_x = max(b[3] for b in boxes)
    max_y = max(b[4] for b in boxes)

    def _span(lo, hi, origin):
        i0 = int((lo - origin) // GRID_CM)
        i1 = int((hi - origin) // GRID_CM) + 1
        return range(i0, i1 + 1)

    # The grid runs to the EDGE OF THE MASSING and stops. Every grid
    # point that falls inside the volume carries a column -- including
    # the ones in the gaps between rooms, which is what makes this a
    # grid rather than a set of room outlines -- but the field does not
    # keep going past the outer face into open air. The bounding box of
    # a cross-shaped plan is mostly not the building.
    #
    # HEIGHT stops where the column stops holding floor. Where the
    # building is full height so is the column, but where an upper
    # storey sets back its columns end with it rather than carrying on
    # up holding nothing. `levels` is the storeys at which any of the
    # four bays meeting at the node has floor in them, so the top of the
    # highest one is where the column ends.
    cells: dict[tuple[int, int], dict] = {}
    for i in _span(min_x, max_x, ox):
        for j in _span(min_y, max_y, oy):
            x = ox + i * GRID_CM
            y = oy + j * GRID_CM
            if not _at_massing(x, y, boxes):
                continue          # past the edge of the volume
            near = [b for b in boxes if _touches_bays(x, y, b)]
            levels = set()
            for _lv, _x0, _y0, _x1, _y1, z0, z1 in near:
                for s in range(_storey_of(z0), _storey_of(z1 - 1) + 1):
                    levels.add(s)
            if not levels:
                continue          # carries no floor at any storey
            cells[(i, j)] = {
                "x": x, "y": y,
                "top": (max(levels) + 1) * STOREY_CM,
                "levels": levels,
            }

    keys = sorted(cells)
    index = {k: n for n, k in enumerate(keys)}

    # --- parasitic spread: BFS across the GRID from the entrance -----
    # Four-neighbour, because beams run along grid lines. The graph is
    # the structure's own adjacency now, not the plan's.
    adj: dict[int, set[int]] = {n: set() for n in range(len(keys))}
    for (i, j), n in index.items():
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            m = index.get((i + di, j + dj))
            if m is not None:
                adj[n].add(m)

    seed = min(range(len(keys)),
               key=lambda n: hypot(cells[keys[n]]["x"] - plan.entrance.x,
                                   cells[keys[n]]["y"] - plan.entrance.y)) if keys else 0

    depth = {seed: 0} if keys else {}
    queue = deque([seed] if keys else [])
    while queue:
        cur = queue.popleft()
        for nxt in sorted(adj[cur]):
            if nxt not in depth:
                depth[nxt] = depth[cur] + 1
                queue.append(nxt)
    if depth:
        tail = max(depth.values()) + 1
        for n in range(len(keys)):
            depth.setdefault(n, tail)

    nodes = [
        FrameNode(id=n, x=cells[keys[n]]["x"], y=cells[keys[n]]["y"],
                  # A column is continuous: it starts on the ground
                  # whatever storey its highest room is on.
                  base_cm=0.0,
                  height_cm=cells[keys[n]]["top"],
                  wall_count=len(adj[n]),
                  axis_count=len({d for d in (0, 1)
                                  if index.get((keys[n][0] + (1 - d), keys[n][1] + d)) is not None
                                  or index.get((keys[n][0] - (1 - d), keys[n][1] - d)) is not None}),
                  depth=depth.get(n, 0),
                  levels=tuple(sorted(cells[keys[n]]["levels"])))
        for n in range(len(keys))
    ]

    members: list[FrameMember] = []
    column = ASSEMBLIES.get("column")
    joint = ASSEMBLIES.get("joint")
    # The connector plate caps each column. In the source it sits at
    # z 290..300, i.e. the top 10cm of a storey, so it is rebased here
    # against the storey line rather than trusting an absolute z.
    plate = None
    if joint:
        plate = next((m for m in joint["members"] if m["name"] == "N"), None)
    lacing = [m for m in (joint["members"] if joint else []) if m["name"] != "N"]

    # --- columns: step 4r -------------------------------------------
    # UNBROKEN from the ground to the top of the highest level the node
    # sits under. A storey the plan does not occupy at this node is
    # still passed through, because a column with a gap in it is not a
    # column -- that continuity is the whole reason the grid exists.
    for node in nodes:
        for s in range(_storeys(node.height_cm)):
            base = s * STOREY_CM
            if column:
                for m in column["members"]:
                    cz = base + m["c"][2]
                    members.append(FrameMember(
                        kind="post", component="Column",
                        cx=node.x + m["c"][0], cy=node.y + m["c"][1],
                        cz=cz,
                        sx=m["s"][0], sy=m["s"][1], sz=m["s"][2],
                        angle=0.0, node_id=node.id,
                        growth_step=_step(node.depth, cz, PHASE_COLUMN),
                    ))
            else:
                sec = CATALOG["N"]["thickness_cm"]
                cz = base + STOREY_CM / 2
                members.append(FrameMember(
                    kind="post", component="Column",
                    cx=node.x, cy=node.y, cz=cz,
                    sx=sec * 4, sy=sec * 4, sz=STOREY_CM,
                    angle=0.0, node_id=node.id,
                    growth_step=_step(node.depth, cz, PHASE_COLUMN),
                ))
            if plate:
                # Source z is absolute against a 300 storey (the plate
                # spans 290..300), so the storey base is all that needs
                # adding.
                cz = base + plate["c"][2]
                members.append(FrameMember(
                    kind="plate", component="N",
                    cx=node.x + plate["c"][0], cy=node.y + plate["c"][1],
                    cz=cz,
                    sx=plate["s"][0], sy=plate["s"][1], sz=plate["s"][2],
                    angle=0.0, node_id=node.id,
                    growth_step=_step(node.depth, cz, PHASE_COLUMN),
                ))

    # --- the woven capital, only where asked for ---------------------
    joint_overlaps = 0
    if joint:
        span = max(joint["footprint_cm"])
        for node in nodes:
            if not node.is_junction:
                continue
            near = min((hypot(node.x - o.x, node.y - o.y)
                        for o in nodes if o.id != node.id), default=1e9)
            if near < span:
                joint_overlaps += 1
            if not joint_blocks:
                continue
            for s in range(_storeys(node.height_cm)):
                base = s * STOREY_CM
                for m in lacing:
                    cz = base + m["c"][2]
                    members.append(FrameMember(
                        kind="lacing", component=m["name"],
                        cx=node.x + m["c"][0], cy=node.y + m["c"][1],
                        cz=cz,
                        sx=m["s"][0], sy=m["s"][1], sz=m["s"][2],
                        angle=0.0, node_id=node.id,
                        growth_step=_step(node.depth, cz, PHASE_COLUMN),
                    ))

    # --- primary beams on the grid lines: step 4r + 1 ----------------
    # One span is exactly one bay, so its members are the catalog parts
    # straight out of components.py with no scaling at all: N + SA + SB
    # + SC + SB + SA + N, 70 + 80 + 60 + 80 + 70 = 360.
    deviations: list[float] = []
    spans = 0
    for (i, j), n in index.items():
        for di, dj in ((1, 0), (0, 1)):          # each span once
            m = index.get((i + di, j + dj))
            if m is None:
                continue
            a, b = nodes[n], nodes[m]
            # Both ends are inside the volume, but the span between them
            # can still cross open air -- two arms of a cross-shaped plan
            # can face each other across a notch. A beam is only built
            # where the bay it spans is in the building.
            if not _at_massing((a.x + b.x) / 2, (a.y + b.y) / 2, boxes):
                continue
            # EVERY storey both columns reach, not only the ones the plan
            # occupies. Two columns a full span apart have to be tied at
            # every level they share: a column rising with nothing
            # spanning to its neighbour is not braced, and the rooms
            # happening to stop short of that bay does not change the
            # structure's problem. An earlier version of this tied only
            # where both ends were occupied, which left 6 of 41 adjacent
            # pairs with a storey of unconnected column.
            reach = int(min(a.height_cm, b.height_cm) // STOREY_CM)
            if reach <= 0:
                continue
            spans += 1
            ang = atan2(b.y - a.y, b.x - a.x)
            ux, uy = (b.x - a.x) / GRID_CM, (b.y - a.y) / GRID_CM
            grow_sign = -1 if a.depth <= b.depth else 1
            for storey in range(reach):
                # The beam sits at the ceiling of its storey, the same
                # 290..300 band the source assembly occupies.
                cz = (storey + 1) * STOREY_CM - CATALOG["N"]["thickness_cm"] / 2
                cursor = 0.0
                for nominal, name in zip(BAY_LENGTHS, BAY_NAMES):
                    spec = CATALOG.get(name, CATALOG["SB"])
                    # No deviation to record: a primary span is exactly
                    # one bay, so these ARE the catalog parts. Only the
                    # infill can drift, and only in a run's last bay.
                    mid = cursor + nominal / 2
                    members.append(FrameMember(
                        kind="beam", component=name,
                        cx=a.x + ux * mid, cy=a.y + uy * mid, cz=cz,
                        sx=nominal, sy=spec["width_cm"], sz=spec["thickness_cm"],
                        angle=ang, node_id=-1, grow_sign=grow_sign,
                        growth_step=_step(min(a.depth, b.depth), cz, PHASE_BEAM),
                    ))
                    cursor += nominal

    # --- half-span stubs at the edge: step 4r + 1 --------------------
    # Where the massing runs past the last column there is no next node
    # to span to, so the frame reaches the building line with half a bay
    # and stops. This replaces planting a column out in open air and
    # running a full span to it. The stub is clipped to the massing, so
    # it closes ON the face and never overhangs it.
    for (i, j), n in index.items():
        a = nodes[n]
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if index.get((i + di, j + dj)) is not None:
                continue                       # a real span goes here
            length = _reach_to_edge(a.x, a.y, di, dj, boxes)
            if length < MIN_STUB_CM:
                continue
            ang = atan2(float(dj), float(di))
            for storey in sorted(a.levels):
                cz = (storey + 1) * STOREY_CM - CATALOG["N"]["thickness_cm"] / 2
                cursor = 0.0
                for name, part in _partial_bay(length):
                    spec = CATALOG.get(name, CATALOG["SB"])
                    deviations.append(abs(part - spec["length_cm"]))
                    mid = cursor + part / 2
                    members.append(FrameMember(
                        kind="beam", component=name,
                        cx=a.x + di * mid, cy=a.y + dj * mid, cz=cz,
                        sx=part, sy=spec["width_cm"], sz=spec["thickness_cm"],
                        angle=ang, node_id=-1, grow_sign=-1,
                        growth_step=_step(a.depth, cz, PHASE_BEAM),
                    ))
                    cursor += part

    # --- floor deck: step 4r + 2 -------------------------------------
    # One plate per element footprint, sitting on the slab line of its
    # own storey. Per element rather than per level because that is what
    # the plan actually covers -- a level is not a rectangle.
    def _nearest_depth(x: float, y: float) -> int:
        best, bd = 0, float("inf")
        for nd in nodes:
            d = (nd.x - x) ** 2 + (nd.y - y) ** 2
            if d < bd:
                best, bd = nd.depth, d
        return best

    for el in plan.elements:
        xs = [c.x for c in el.corners]
        ys = [c.y for c in el.corners]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        z0 = getattr(el, "z0", 0.0)
        members.append(FrameMember(
            kind="floor", component="Deck",
            cx=cx, cy=cy, cz=z0 + FLOOR_CM / 2,
            sx=max(xs) - min(xs), sy=max(ys) - min(ys), sz=FLOOR_CM,
            angle=0.0, node_id=-1,
            growth_step=_step(_nearest_depth(cx, cy), z0, PHASE_FLOOR),
        ))

    # --- wall infill: step 4r + 3 ------------------------------------
    # The walls between the bays. All four Beam A arms sit coplanar at
    # z 290..300 in the source -- they interlock by halving, not by
    # vertical offset. An earlier version of this file staggered them,
    # which was invented.
    per_storey = _courses_per_storey(course_cm)

    def _wall_span(wall) -> tuple[float, float]:
        """(base_z, top_z) of a wall, from the elements that own it.
        Elements on level 1 sit a storey up, so a wall's base is not
        always the ground -- reading only height_cm would build every
        upper-floor wall down through the building."""
        owners = [plan.elements[i] for i in wall.owners]
        if not owners:
            return 0.0, STOREY_CM
        base = min(getattr(el, "z0", 0.0) for el in owners)
        top = max(getattr(el, "z0", 0.0) + el.height_cm for el in owners)
        return base, top

    for wall in plan.walls:
        wbase, wtop = _wall_span(wall)
        near = _nearest_depth((wall.start.x + wall.end.x) / 2,
                              (wall.start.y + wall.end.y) / 2)
        grow_sign = -1
        # Courses are measured up from the wall's OWN floor slab, then
        # lifted onto it -- a level-1 wall gets the same courses as a
        # level-0 one, three metres higher.
        levels = _levels(wtop - wbase, per_storey)
        for seg in wall.segments:
            if seg.component == "N":
                continue  # N is the connector plate, drawn with the column
            dx = seg.end.x - seg.start.x
            dy = seg.end.y - seg.start.y
            length = hypot(dx, dy)
            if length < 1:
                continue
            spec = CATALOG.get(seg.component, CATALOG["SB"])
            deviations.append(abs(length - spec["length_cm"]))
            ang = atan2(dy, dx)
            mx = (seg.start.x + seg.end.x) / 2
            my = (seg.start.y + seg.end.y) / 2
            # Unit normal in plan, for the alternating course offset.
            nx, ny = -dy / length, dx / length
            for ordinal, lv in levels:
                cz = wbase + lv - spec["thickness_cm"] / 2
                # The ceiling course is the structural beam and stays on
                # the wall centre line. The courses between it weave
                # either side by half a member, which is what the
                # surveyed capital does: its F1/F2 lacing layers
                # alternate a +/-10cm offset between vertical layers
                # (c [10, 40, 275] against [-10, 20, 255] in
                # component_exports/components.json).
                off = (0.0 if ordinal % per_storey == 0
                       else spec["width_cm"] / 2 * (1 if ordinal % 2 else -1))
                members.append(FrameMember(
                    kind="infill", component=seg.component,
                    cx=mx + nx * off, cy=my + ny * off, cz=cz,
                    sx=length, sy=spec["width_cm"], sz=spec["thickness_cm"],
                    angle=ang, node_id=-1, grow_sign=grow_sign,
                    growth_step=_step(near, cz, PHASE_INFILL),
                ))

    steps = (max((m.growth_step for m in members), default=-1) + 1)

    by_step: dict[int, list[FrameMember]] = {}
    for m in members:
        by_step.setdefault(m.growth_step, []).append(m)
    junctions = {nd.id for nd in nodes if nd.is_junction}

    labels: list[str] = []
    for s in range(steps):
        at = by_step.get(s, [])
        # How far the front has reached, out and up together. Four steps
        # to a ring, in the order the thing is assembled.
        ring = f" · ring {s // 4}"
        if not at:
            labels.append("—")
            continue
        phase = s % 4
        if phase == PHASE_COLUMN:
            ids = {m.node_id for m in at}
            caps = len(ids & junctions)
            labels.append(f"columns · {len(ids)} node{'s' if len(ids) != 1 else ''}"
                          + (f", {caps} capital" if caps else "") + ring)
        elif phase == PHASE_BEAM:
            labels.append(f"beams · {len(at)} member{'s' if len(at) != 1 else ''}" + ring)
        elif phase == PHASE_FLOOR:
            labels.append(f"floor · {len(at)} deck{'s' if len(at) != 1 else ''}" + ring)
        else:
            labels.append(f"infill · {len(at)} member{'s' if len(at) != 1 else ''}" + ring)

    dev = {}
    if deviations:
        ordered = sorted(deviations)
        dev = {
            "mean_cm": round(sum(deviations) / len(deviations), 1),
            "median_cm": round(ordered[len(ordered) // 2], 1),
            "max_cm": round(ordered[-1], 1),
            "within_5cm_pct": round(100 * sum(1 for d in deviations if d <= 5) / len(deviations), 1),
            "sample": len(deviations),
        }

    return Frame(members=members, nodes=nodes, growth_steps=steps,
                 step_labels=labels, length_deviation=dev,
                 joint_overlaps=joint_overlaps,
                 course_cm=STOREY_CM / per_storey,
                 grid_cm=GRID_CM, span_count=spans)


def frame_summary(frame: Frame) -> dict:
    """Counts for a sanity check and for the UI census."""
    by_component: dict[str, int] = {}
    for m in frame.members:
        by_component[m.component] = by_component.get(m.component, 0) + 1
    return {
        "member_count": len(frame.members),
        "post_count": sum(1 for m in frame.members if m.kind == "post"),
        "beam_count": sum(1 for m in frame.members if m.kind == "beam"),
        "infill_count": sum(1 for m in frame.members if m.kind == "infill"),
        "floor_count": sum(1 for m in frame.members if m.kind == "floor"),
        "plate_count": sum(1 for m in frame.members if m.kind == "plate"),
        "lacing_count": sum(1 for m in frame.members if m.kind == "lacing"),
        "node_count": len(frame.nodes),
        "junction_count": sum(1 for n in frame.nodes if n.is_junction),
        "max_depth": max((n.depth for n in frame.nodes), default=0),
        "by_component": by_component,
        # The structural grid the columns stand on, and how many of its
        # lines carry a primary beam.
        "grid_cm": frame.grid_cm,
        "span_count": frame.span_count,
        # The vertical pitch the wall was filled at, and how many courses
        # that puts in a storey. 1 course is the ceiling beam alone.
        "course_cm": frame.course_cm,
        "courses_per_storey": round(STOREY_CM / frame.course_cm),
        # Provenance, so the UI can say whether it is drawing surveyed
        # geometry or the placeholder.
        "real_components": HAS_REAL_COMPONENTS,
        "source": _DATA.get("source", "fallback"),
        "catalog": CATALOG,
        # How far the INFILL members land from the nearest catalog
        # length. Primary grid beams are excluded because a span is
        # exactly one bay, so they are catalog parts by construction --
        # averaging them in would only dilute the number that matters.
        # What is left is the cost of the last bay of each wall run
        # adapting to close it.
        "length_deviation": frame.length_deviation,
        "joint_overlaps": frame.joint_overlaps,
    }
