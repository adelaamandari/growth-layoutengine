"""
components.py
The physical wall component system: N (node) and the SA/SB/SC edges,
walked in the symmetric sequence

    N + SA + SB + SC + SB + SA + N

across one 360cm structural bay.

WHY 360, AND WHY THIS SEQUENCE
Both are measured off `components.glb`, not chosen. The Beam A assembly
is 359.99 x 359.99, and one of its arms runs outward from the node
centre as SA (10..80), SB (60..140), SC (120..180) -- each member
lapping the next by exactly 20cm, one member width, reaching 180cm.
Mirror that arm and you have the sequence above, node centre to node
centre, 360cm apart. The nominal lengths agree exactly:

    SA + SB + SC + SB + SA  =  70 + 80 + 60 + 80 + 70  =  360

so a bay closes on real catalog parts with nothing left over. The 20cm
laps are how the members physically join; they do not change the pitch.

An earlier version of this module walked a NINE part sequence
(N-SA-SB-SB-SC-SB-SB-SA-N) and derived a scale factor per wall so it
stretched to fit any length. That produced members no joinery shop
could cut twice the same -- a median 40cm off the nearest catalog
length. The bay is now fixed and only the LAST bay of a run adapts.

THE LAST BAY ADAPTS
A wall is rarely a whole number of 360cm bays. The run is divided into
the nearest whole number of bays and the last one takes up the
difference, so it can be stretched or shortened -- between roughly half
a bay and one and a half. Every other bay in the run is exactly 360 and
its five members are exactly the catalog parts.
"""

from __future__ import annotations
from dataclasses import dataclass
from .geometry import Point, dist, normalize

# One structural bay, node centre to node centre. Surveyed off the Beam
# A assembly in components.glb -- see the module docstring.
BAY_CM = 360.0

# The members spanning one bay, in order. These are the REAL catalog
# lengths and they sum to BAY_CM exactly.
BAY_LENGTHS = [70.0, 80.0, 60.0, 80.0, 70.0]
BAY_NAMES = ["SA", "SB", "SC", "SB", "SA"]

# The connector plate standing at each node. It is 60x60 in plan, so it
# is emitted as a 60cm marker centred ON the node rather than as another
# link in the chain -- the node is a point where members meet, not a
# length of wall. It therefore overlaps the SA either side of it, which
# is what the plate physically does.
NODE_CM = 60.0

# A run shorter than this is not worth walking at all.
MIN_RUN_CM = 5.0


@dataclass(frozen=True)
class WallSegment:
    start: Point
    end: Point
    component: str  # "N" | "SA" | "SB" | "SC"


def bay_lengths(total: float) -> list[float]:
    """
    Divide a run into bays: as many exact 360s as fit, with the last one
    taking up the difference.

    Rounding rather than flooring keeps the odd bay closer to 360 -- a
    5m run becomes one bay of 500 either way, but a 6m run becomes
    360 + 240 instead of a single 600.
    """
    if total < MIN_RUN_CM:
        return []
    n = max(1, round(total / BAY_CM))
    last = total - (n - 1) * BAY_CM
    if last <= 0:                      # rounded up past what is there
        n -= 1
        last = total - (n - 1) * BAY_CM
    return [BAY_CM] * (n - 1) + [last]


def walk_bay(p1: Point, p2: Point, direction: Point,
             length: float) -> list[WallSegment]:
    """The five members of one bay, from p1 towards p2. At the exact
    360 they are catalog parts; the last bay of a run scales all five
    by the same factor so the joint proportions are preserved."""
    k = length / BAY_CM
    segments = []
    cursor = p1
    for nominal, name in zip(BAY_LENGTHS, BAY_NAMES):
        nxt = cursor + direction.scaled(nominal * k)
        segments.append(WallSegment(cursor, nxt, name))
        cursor = nxt
    return segments


def walk_wall(p1: Point, p2: Point) -> list[WallSegment]:
    """
    Build the component sequence along a wall from p1 to p2.

    The wall is divided into 360cm bays; each bay is N + SA + SB + SC +
    SB + SA + N. Nodes land on the bay boundaries AND on both ends of
    the wall, so a node is always where members meet.
    """
    total = dist(p1, p2)
    lengths = bay_lengths(total)
    if not lengths:
        return []

    direction = normalize(Point(p2.x - p1.x, p2.y - p1.y))
    half = direction.scaled(NODE_CM / 2)

    segments: list[WallSegment] = []
    cursor = p1
    for length in lengths:
        # The node at the start of this bay.
        segments.append(WallSegment(cursor - half, cursor + half, "N"))
        end = cursor + direction.scaled(length)
        segments.extend(walk_bay(cursor, end, direction, length))
        cursor = end
    # ...and the one closing the run.
    segments.append(WallSegment(cursor - half, cursor + half, "N"))
    return segments


def walk_rectangle(c1: Point, c2: Point, c3: Point, c4: Point) -> list[WallSegment]:
    """Build all four walls of a rectangle (or any quad) in order."""
    segments = []
    for a, b in [(c1, c2), (c2, c3), (c3, c4), (c4, c1)]:
        segments.extend(walk_wall(a, b))
    return segments
