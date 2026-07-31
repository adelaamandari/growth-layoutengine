"""
geometry.py
Pure vector math and polygon overlap testing. No Rhino/Grasshopper
dependency -- this module works with plain (x, y) tuples so it can be
unit tested in isolation before wiring into GHPython.
"""

from __future__ import annotations
from dataclasses import dataclass
from math import hypot
from typing import Sequence

# Tolerance (cm) for treating flush-touching edges as NOT overlapping.
# Without this, two components sharing a wall (e.g. a room built flush
# against the corridor edge) will register as a false-positive collision,
# since their shared boundary line has zero separation.
EPS = 1.0


@dataclass(frozen=True)
class Point:
    x: float
    y: float

    def __add__(self, other: "Point") -> "Point":
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: "Point") -> "Point":
        return Point(self.x - other.x, self.y - other.y)

    def scaled(self, k: float) -> "Point":
        return Point(self.x * k, self.y * k)

    def as_tuple(self) -> tuple:
        return (self.x, self.y)


def dist(a: Point, b: Point) -> float:
    return hypot(a.x - b.x, a.y - b.y)


def normalize(v: Point) -> Point:
    length = hypot(v.x, v.y)
    if length == 0:
        raise ValueError("cannot normalize a zero-length vector")
    return Point(v.x / length, v.y / length)


def perpendicular(v: Point) -> Point:
    """Rotate a vector 90 degrees counter-clockwise."""
    return Point(-v.y, v.x)


# ---------------------------------------------------------------------
# Polygon overlap (Separating Axis Theorem), tolerant of flush touching.
# Works for any convex polygon, not just rectangles, so it covers
# rotated units on diagonal branches if that's ever reintroduced.
# ---------------------------------------------------------------------

def _polygon_axes(poly: Sequence[Point]) -> list[Point]:
    axes = []
    n = len(poly)
    for i in range(n):
        p1, p2 = poly[i], poly[(i + 1) % n]
        edge = Point(p2.x - p1.x, p2.y - p1.y)
        axes.append(normalize(perpendicular(edge)))
    return axes


def _project(poly: Sequence[Point], axis: Point) -> tuple[float, float]:
    values = [p.x * axis.x + p.y * axis.y for p in poly]
    return min(values), max(values)


def polygons_overlap(a: Sequence[Point], b: Sequence[Point]) -> bool:
    """
    True if convex polygons a and b overlap by more than EPS.
    Flush-touching edges (shared walls) are NOT considered overlapping --
    this is the fix for the false-positive collision bug found when
    rooms attach directly to a corridor edge.
    """
    for axis in [*_polygon_axes(a), *_polygon_axes(b)]:
        a_min, a_max = _project(a, axis)
        b_min, b_max = _project(b, axis)
        if a_max <= b_min + EPS or b_max <= a_min + EPS:
            return False
    return True


def point_in_polygon(p: Point, poly: Sequence[Point]) -> bool:
    """Standard ray-casting test. Kept for when a site boundary is
    reintroduced -- not currently used by growth.py."""
    inside = False
    n = len(poly)
    for i in range(n):
        j = (i - 1) % n
        xi, yi = poly[i].x, poly[i].y
        xj, yj = poly[j].x, poly[j].y
        if (yi > p.y) != (yj > p.y):
            x_intersect = (xj - xi) * (p.y - yi) / (yj - yi) + xi
            if p.x < x_intersect:
                inside = not inside
    return inside
