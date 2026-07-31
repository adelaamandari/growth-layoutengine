"""
walls.py
Shared-wall resolution: turn the per-element edges into the set of
PHYSICAL walls, each built exactly once.

This implements what PROJECT_SUMMARY states as fundamental -- a
`shared_walls` entry means two rooms share ONE physical built wall,
"built once, referenced by both, never duplicated" -- which growth.py
previously did not do. Every element walked all four of its own edges,
so a unit sitting flush against a corridor produced that wall twice.

WHY THIS IS NOT JUST "DROP THE DUPLICATE"
A corridor edge can be 25m long while a unit abuts only 10m of it.
They are not the same wall; they share a stretch OF one. So edges are
grouped by their supporting line, projected to 1D, and the line is cut
at every interval endpoint. Each resulting stretch becomes one wall
owned by whichever elements cover it. The walls then exactly tile the
union of all edges: no gaps, no overlaps, nothing built twice.

CONSEQUENCE FOR THE COMPONENT WALK
Each resolved wall is walked ONCE into the N-SA-SB-SB-SC-SB-SB-SA-N
sequence. Because a long corridor edge is now cut where units meet it,
those cuts land on N nodes -- which is structurally what a node is, the
point where members meet. It also means the two faces of a shared wall
finally agree about where the members are; previously each side walked
its own length and their breakpoints did not line up.
"""

from __future__ import annotations

from dataclasses import dataclass

from .components import WallSegment, walk_wall
from .geometry import Point, dist, normalize

# Two edges lie on the same physical line if every endpoint of one sits
# within this distance of the other's line. Deliberately looser than
# geometry.EPS (1cm): that epsilon decides collision, this decides
# identity, and a wall reached from both sides can be a hair off.
COLLINEAR_TOL_CM = 2.0

# Two DIFFERENT thresholds, deliberately separate -- conflating them
# silently truncated the last stretch on every line, because a cut
# within 5cm of its predecessor was discarded instead of becoming a
# short interval.
#
#   CUT_MERGE_TOL_CM  two cut positions are the same cut (float noise)
#   MIN_WALL_CM       an interval too short to be worth building
#
# A stretch between MIN_WALL_CM and CUT_MERGE_TOL_CM is real: it gets
# created, then dropped and counted, so length accounting stays exact.
CUT_MERGE_TOL_CM = 0.5
MIN_WALL_CM = 5.0

_PARALLEL_EPS = 1e-6


@dataclass(frozen=True)
class Wall:
    """One physical wall, built once, referenced by every element on it."""
    id: int
    start: Point
    end: Point
    owners: tuple[int, ...]              # indices into FloorPlan.elements
    segments: tuple[WallSegment, ...]    # the component walk, done once

    @property
    def shared(self) -> bool:
        return len(self.owners) > 1

    @property
    def length_cm(self) -> float:
        return dist(self.start, self.end)


def _canonical_direction(a: Point, b: Point) -> Point:
    """Unit direction with a fixed sign convention, so an edge and its
    reverse land on the same line group."""
    d = normalize(Point(b.x - a.x, b.y - a.y))
    if d.x < -_PARALLEL_EPS or (abs(d.x) <= _PARALLEL_EPS and d.y < 0):
        return Point(-d.x, -d.y)
    return d


class _Line:
    """A supporting line plus every interval any element claims on it."""

    __slots__ = ("origin", "dir", "intervals")

    def __init__(self, origin: Point, direction: Point):
        self.origin = origin
        self.dir = direction
        self.intervals: list[tuple[float, float, int]] = []

    def is_parallel(self, d: Point) -> bool:
        return abs(self.dir.x * d.y - self.dir.y * d.x) <= _PARALLEL_EPS

    def contains(self, p: Point) -> bool:
        nx, ny = -self.dir.y, self.dir.x
        return abs((p.x - self.origin.x) * nx + (p.y - self.origin.y) * ny) <= COLLINEAR_TOL_CM

    def project(self, p: Point) -> float:
        return (p.x - self.origin.x) * self.dir.x + (p.y - self.origin.y) * self.dir.y

    def point_at(self, t: float) -> Point:
        return Point(self.origin.x + self.dir.x * t, self.origin.y + self.dir.y * t)


def _element_edges(corners: list[Point]) -> list[tuple[Point, Point]]:
    return [(corners[i], corners[(i + 1) % 4]) for i in range(4)]


def _merge_cuts(values: list[float]) -> list[float]:
    """
    Collapse cut positions that coincide to within float noise.

    Uses CUT_MERGE_TOL_CM, NOT MIN_WALL_CM: merging at the larger
    threshold discards a genuine cut near the end of a line, which
    silently shortens the union. Short intervals are handled later, by
    dropping and counting them.
    """
    out: list[float] = []
    for v in sorted(values):
        if not out or v - out[-1] > CUT_MERGE_TOL_CM:
            out.append(v)
    return out


@dataclass(frozen=True)
class WallResolution:
    """The resolved walls plus what was discarded getting there.

    `dropped_cm` matters for verification: stretches shorter than
    MIN_WALL_CM are deliberately not emitted (you do not fabricate a 2cm
    wall), so resolved length alone is a few centimetres short of the
    true union. Reporting it lets the invariant be checked exactly
    instead of absorbed into a tolerance.
    """
    walls: list[Wall]
    dropped_cm: float
    dropped_count: int


def resolve_walls(elements) -> WallResolution:
    """
    Build the deduplicated wall set for a list of PlacedElements.

    Returns walls that tile the union of every element edge, minus any
    sub-MIN_WALL_CM slivers. Total resolved length plus dropped length
    equals the union length, so a material take-off off these walls
    counts each wall exactly once.
    """
    lines: list[_Line] = []

    for idx, el in enumerate(elements):
        for a, b in _element_edges(el.corners):
            if dist(a, b) < MIN_WALL_CM:
                continue
            d = _canonical_direction(a, b)
            line = next(
                (ln for ln in lines
                 if ln.is_parallel(d) and ln.contains(a) and ln.contains(b)),
                None,
            )
            if line is None:
                line = _Line(a, d)
                lines.append(line)
            t0, t1 = sorted((line.project(a), line.project(b)))
            line.intervals.append((t0, t1, idx))

    walls: list[Wall] = []
    dropped_cm = 0.0
    dropped_count = 0
    for line in lines:
        cuts = _merge_cuts([t for iv in line.intervals for t in iv[:2]])
        for lo, hi in zip(cuts, cuts[1:]):
            mid = (lo + hi) / 2
            owners = tuple(sorted({
                owner for (a0, a1, owner) in line.intervals if a0 <= mid <= a1
            }))
            if not owners:
                continue  # a gap between two runs on the same line
            if hi - lo < MIN_WALL_CM:
                # Real but unfabricable sliver -- account for it rather
                # than letting it vanish from the length total.
                dropped_cm += hi - lo
                dropped_count += 1
                continue
            p0, p1 = line.point_at(lo), line.point_at(hi)
            walls.append(Wall(
                id=len(walls), start=p0, end=p1,
                owners=owners, segments=tuple(walk_wall(p0, p1)),
            ))
    return WallResolution(walls=walls, dropped_cm=dropped_cm, dropped_count=dropped_count)


def walls_by_owner(walls: list[Wall], count: int) -> list[list[int]]:
    """Inverse index: for each element, the ids of the walls on it."""
    out: list[list[int]] = [[] for _ in range(count)]
    for w in walls:
        for owner in w.owners:
            out[owner].append(w.id)
    return out


def wall_summary(walls: list[Wall]) -> dict:
    total = sum(w.length_cm for w in walls)
    shared = [w for w in walls if w.shared]
    return {
        "wall_count": len(walls),
        "shared_count": len(shared),
        "total_length_m": round(total / 100, 1),
        "shared_length_m": round(sum(w.length_cm for w in shared) / 100, 1),
        "segment_count": sum(len(w.segments) for w in walls),
    }
