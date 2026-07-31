"""
components.py
The physical wall component system: N (node), SA, SB, SC edges,
walked in the symmetric sequence N-SA-SB-SB-SC-SB-SB-SA-N. A wall of
any length is rescaled from the original ratios (50:80:100:80) so the
sequence always sums exactly to that wall's real length -- no rounding
baked into constants, see MANUAL - COMPONENT GEOMETRY RULESET.py for
the full derivation.
"""

from __future__ import annotations
from dataclasses import dataclass
from .geometry import Point, dist, normalize

# ratios: N, SA, SB, SB, SC, SB, SB, SA, N
RATIOS = [50, 80, 100, 100, 80, 100, 100, 80, 50]
RATIO_SUM = sum(RATIOS)  # 740
COMPONENT_NAMES = ["N", "SA", "SB", "SB", "SC", "SB", "SB", "SA", "N"]


@dataclass(frozen=True)
class WallSegment:
    start: Point
    end: Point
    component: str  # "N" | "SA" | "SB" | "SC"


def walk_wall(p1: Point, p2: Point) -> list[WallSegment]:
    """
    Build the real component sequence along a wall from p1 to p2.
    The scale factor is derived fresh from this wall's own length, so
    every wall -- corridor edge, unit partition, whatever -- is exactly
    proportioned regardless of how long or short it is.
    """
    total = dist(p1, p2)
    if total < 5:
        return []
    k = total / RATIO_SUM
    direction = normalize(Point(p2.x - p1.x, p2.y - p1.y))
    segments = []
    cursor = p1
    for ratio, name in zip(RATIOS, COMPONENT_NAMES):
        length = ratio * k
        nxt = cursor + direction.scaled(length)
        segments.append(WallSegment(cursor, nxt, name))
        cursor = nxt
    return segments


def walk_rectangle(c1: Point, c2: Point, c3: Point, c4: Point) -> list[WallSegment]:
    """Build all four walls of a rectangle (or any quad) in order."""
    segments = []
    for a, b in [(c1, c2), (c2, c3), (c3, c4), (c4, c1)]:
        segments.extend(walk_wall(a, b))
    return segments
