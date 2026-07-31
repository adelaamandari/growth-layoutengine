"""
site/analysis.py

Grid-based daylight and circulation analysis run BEFORE growth starts.
Takes a site boundary (real, from osm_site_finder.SiteCandidate, or a
manually specified polygon for testing) and produces per-cell scores
the growth engine can later use to bias placement -- e.g. pull
communal/living rooms toward high-daylight cells, place the entrance
where circulation access is highest.

Two scores, deliberately kept separate rather than pre-combined, since
growth.py should decide its own weighting between them rather than
this module baking in an opinion about which matters more:

  - daylight_score  (0-1): based on real known obstructions -- the
    flanking neighbor buildings' heights -- via a Vertical Sky
    Component-style obstruction angle. This is the honest, defensible
    part: it's real geometry, not a guess.
  - circulation_score (0-1): distance-decay from the site's frontage
    edge (the street-facing side). Simple and legible, not a real
    pedestrian-flow simulation.

WHAT THIS DELIBERATELY DOES NOT DO:
  - No sun-path/solar-hours simulation (would need date, time, real
    shadow projection -- possible to add later, this is a first-pass
    heuristic, not a certified daylight study).
  - No prediction of self-shadowing from the building that will grow
    ON this site -- can't know that before growth runs. Only accounts
    for the two known existing neighbors.
  - No pedestrian/vehicle circulation simulation -- "circulation score"
    here just means "how close is this cell to the street", nothing
    about actual movement patterns.
"""

from __future__ import annotations
from dataclasses import dataclass
import math

from ..geometry import Point, point_in_polygon


@dataclass
class Neighbor:
    """A known existing building flanking the site."""
    edge_point: Point  # local cm, closest point of the neighbor to the site
    height_cm: float


@dataclass
class GridCell:
    center: Point
    daylight_score: float    # 0 (fully obstructed) to 1 (fully open)
    circulation_score: float  # 0 (far from access) to 1 (at the frontage)

    def combined_score(self, daylight_weight: float = 0.5) -> float:
        """Simple weighted blend -- growth.py can also just use the two
        scores separately instead of calling this."""
        return (daylight_weight * self.daylight_score
                + (1 - daylight_weight) * self.circulation_score)


@dataclass
class SiteAnalysis:
    boundary: list[Point]
    frontage_edge: tuple[Point, Point]
    cells: list[GridCell]
    cell_size_cm: float

    def score_at(self, p: Point) -> GridCell:
        """Nearest-cell lookup -- fine for a bias field, not meant for
        precise interpolation."""
        return min(self.cells, key=lambda c: (c.center.x - p.x) ** 2 + (c.center.y - p.y) ** 2)

    def to_dict(self) -> dict:
        """JSON-serializable summary, ready for a frontend heatmap."""
        return {
            "boundary": [[p.x, p.y] for p in self.boundary],
            "frontage_edge": [[self.frontage_edge[0].x, self.frontage_edge[0].y],
                               [self.frontage_edge[1].x, self.frontage_edge[1].y]],
            "cell_size_cm": self.cell_size_cm,
            "cells": [
                {"x": c.center.x, "y": c.center.y,
                 "daylight": round(c.daylight_score, 3),
                 "circulation": round(c.circulation_score, 3)}
                for c in self.cells
            ],
        }


def _point_to_segment_distance(p: Point, a: Point, b: Point) -> float:
    ab = Point(b.x - a.x, b.y - a.y)
    ab_len2 = ab.x ** 2 + ab.y ** 2
    if ab_len2 == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = max(0.0, min(1.0, ((p.x - a.x) * ab.x + (p.y - a.y) * ab.y) / ab_len2))
    proj = Point(a.x + ab.x * t, a.y + ab.y * t)
    return math.hypot(p.x - proj.x, p.y - proj.y)


def _daylight_score(cell: Point, neighbors: list[Neighbor],
                     obstruction_weight: float = 0.6) -> float:
    """
    Vertical Sky Component-style heuristic: for each neighbor, compute
    the obstruction angle (how high the neighbor's roofline sits
    relative to this cell's horizontal distance from it). Tall +
    close = high obstruction = low score. Multiple neighbors compound
    multiplicatively rather than additively, so being flanked on both
    sides is worse than either alone, but a single very tall neighbor
    doesn't necessarily zero out the score entirely (obstruction_weight
    caps how much any one neighbor can block).
    """
    score = 1.0
    for n in neighbors:
        horiz_dist = math.hypot(cell.x - n.edge_point.x, cell.y - n.edge_point.y)
        if horiz_dist <= 1:
            horiz_dist = 1  # avoid division blow-up right at the boundary
        angle = math.atan2(n.height_cm, horiz_dist)
        obstruction = angle / (math.pi / 2)  # 0 (flat) to 1 (directly overhead)
        score *= (1 - obstruction * obstruction_weight)
    return max(0.0, min(1.0, score))


def _circulation_score(cell: Point, frontage_edge: tuple[Point, Point],
                        decay_cm: float = 1500.0) -> float:
    """Exponential decay from the frontage edge -- 1.0 right at the
    street, dropping off over roughly `decay_cm` of depth into the site."""
    dist = _point_to_segment_distance(cell, frontage_edge[0], frontage_edge[1])
    return math.exp(-dist / decay_cm)


def analyze_site(boundary: list[Point], frontage_edge: tuple[Point, Point],
                  neighbors: list[Neighbor], cell_size_cm: float = 200.0) -> SiteAnalysis:
    """
    Build a grid over the boundary polygon (only cells whose center
    falls inside count) and score each cell for daylight and
    circulation access.
    """
    xs = [p.x for p in boundary]
    ys = [p.y for p in boundary]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)

    cells = []
    x = x0 + cell_size_cm / 2
    while x < x1:
        y = y0 + cell_size_cm / 2
        while y < y1:
            center = Point(x, y)
            if point_in_polygon(center, boundary):
                cells.append(GridCell(
                    center=center,
                    daylight_score=_daylight_score(center, neighbors),
                    circulation_score=_circulation_score(center, frontage_edge),
                ))
            y += cell_size_cm
        x += cell_size_cm

    return SiteAnalysis(boundary=boundary, frontage_edge=frontage_edge,
                         cells=cells, cell_size_cm=cell_size_cm)
