"""
site_grid.py
Read the grid off the site instead of imposing one on it.

Every previous version of this engine laid a building on axes it brought
with it -- +x and +y, anchored at an entrance the caller chose -- and
then asked whether the result fitted the plot. This module inverts that:
the plot's own edges are the candidate grid directions, and the building
is laid out on them.

WHAT THE EDGES ACTUALLY GIVE YOU
Measured on the Deptford triangle, which is worth stating because it
changes the design:

    Coffey Street            113.9 m   bearing  87.0 deg
    Deptford Church Street    80.6 m   bearing 176.0 deg
    Crossfield Street        140.6 m   bearing 121.9 deg

    Coffey x Deptford Church  89.0 deg apart
    Coffey x Crossfield       35.0 deg
    Church x Crossfield       54.1 deg

So the site does NOT offer three equal options. The two street frontages
are square to each other to within a degree -- they are ONE grid, and it
is the grid the 360cm structural bay already assumes. Crossfield's
diagonal is a genuinely separate system, 35 degrees off, and a 35-degree
crossing cannot be resolved by a 360x360 assembly with four orthogonal
arms. Two families, not three axes.

THE SEAM IS NOT DRAWN, IT IS FOUND
With two grid families the building needs a line where one stops and the
other starts. Rather than picking one, every cell is assigned the family
of its NEAREST site edge; the seam is wherever that nearest edge changes.
For a triangle that would give three zones meeting near the incentre --
but the two street edges share a family, so their zones merge and exactly
one seam is left. It falls out of the plot's own geometry.

WHAT THE CELL FIELD IS FOR
Deciding WHERE things go, not what shape they are. Residential units have
surveyed footprints from Rhino -- Studio_A is 10.2 x 4.2 m, which is not
a whole number of any cell -- so a cell can never be a room module. It is
an availability and zoning field: inside/outside, which grid family, how
far from the boundary, how far from the street. Rooms snap to the grid;
the residual becomes green.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geometry import Point, point_in_polygon

# Two axes belong to the same grid if they are within this of parallel or
# perpendicular. Coffey and Deptford Church come out 89.0 apart, so 5
# degrees is comfortable; tightening it below 1 would split them and give
# every street its own grid, which is not what the site is telling us.
FAMILY_TOL_DEG = 5.0

# An edge shorter than this is a chamfer or a survey artefact, not a
# frontage worth taking a grid from.
MIN_EDGE_M = 15.0


@dataclass(frozen=True)
class Axis:
    """One candidate grid direction, taken from a site edge."""
    name: str
    bearing_deg: float      # 0..180 from north; direction is unsigned
    ux: float
    uy: float
    support_m: float        # length of the edge backing it
    edge_index: int

    @property
    def perpendicular(self) -> tuple[float, float]:
        return (-self.uy, self.ux)


@dataclass
class GridFamily:
    """A set of site edges that agree on one orthogonal grid.

    `axes` are all the edges that fell into it; `bearing_deg` is the
    length-weighted average of their directions, so a long frontage
    counts for more than a short one. That matters here: Coffey (113.9 m)
    and Deptford Church (80.6 m) disagree by a degree, and the grid
    should sit nearer the longer one.
    """
    axes: list[Axis] = field(default_factory=list)
    bearing_deg: float = 0.0

    @property
    def name(self) -> str:
        return " + ".join(a.name for a in self.axes)

    @property
    def support_m(self) -> float:
        return sum(a.support_m for a in self.axes)

    @property
    def u(self) -> tuple[float, float]:
        r = math.radians(self.bearing_deg)
        return (math.sin(r), math.cos(r))

    @property
    def v(self) -> tuple[float, float]:
        ux, uy = self.u
        return (-uy, ux)


def _edge_bearing(a, b) -> tuple[float, float, float, float]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    brg = math.degrees(math.atan2(dx, dy)) % 180.0
    return brg, dx / length, dy / length, length


def extract_axes(boundary_m, names=None) -> list[Axis]:
    """One candidate axis per site edge, longest first."""
    n = len(boundary_m)
    out = []
    for i in range(n):
        a, b = boundary_m[i], boundary_m[(i + 1) % n]
        brg, ux, uy, length = _edge_bearing(a, b)
        if length < MIN_EDGE_M:
            continue
        label = names[i] if names and i < len(names) else f"edge {i}"
        out.append(Axis(label, round(brg, 1), ux, uy, round(length, 1), i))
    return sorted(out, key=lambda a: -a.support_m)


def axis_separation(a: float, b: float) -> float:
    """Acute angle between two unsigned bearings, folded to 0..90.

    Folded because a grid is symmetric: an axis at 87 degrees and one at
    177 describe the SAME grid, one being the other's cross direction.
    Comparing raw bearings would call those two different systems.
    """
    d = abs(a - b) % 180.0
    d = min(d, 180.0 - d)
    return min(d, 90.0 - d) if d > 45.0 else d


def grid_families(axes: list[Axis], tol_deg: float = FAMILY_TOL_DEG) -> list[GridFamily]:
    """Group axes that describe the same orthogonal grid.

    Greedy, seeded from the longest edge, which is deliberate: the grid a
    building is laid out on should be the one its biggest frontage asks
    for, not whichever edge the polygon happened to start at.
    """
    families: list[GridFamily] = []
    for ax in axes:
        for fam in families:
            if axis_separation(ax.bearing_deg, fam.bearing_deg) <= tol_deg:
                fam.axes.append(ax)
                # Length-weighted mean, folded onto the family's own
                # direction so a cross-axis at +90 does not drag the
                # average halfway round.
                total = fam.support_m
                folded = _fold_onto(ax.bearing_deg, fam.bearing_deg)
                fam.bearing_deg = round(
                    (fam.bearing_deg * (total - ax.support_m)
                     + folded * ax.support_m) / total, 2)
                break
        else:
            families.append(GridFamily(axes=[ax], bearing_deg=ax.bearing_deg))
    return sorted(families, key=lambda f: -f.support_m)


def _fold_onto(bearing: float, reference: float) -> float:
    """`bearing` expressed as the nearest equivalent to `reference`."""
    best, bd = bearing, 999.0
    for cand in (bearing, bearing + 90, bearing - 90, bearing + 180, bearing - 180):
        d = abs(cand - reference)
        if d < bd:
            best, bd = cand, d
    return best


# --- the cell field --------------------------------------------------

@dataclass
class Cell:
    ix: int
    iy: int
    x: float                # centre, metres
    y: float
    family: int             # index into the families list
    edge: int               # index of the nearest site edge
    edge_dist_m: float      # distance to the boundary
    seam: bool = False      # sits against a cell of a different family


@dataclass
class CellField:
    resolution_m: float
    cells: list[Cell]
    families: list[GridFamily]
    bounds_m: tuple[float, float, float, float]

    @property
    def area_m2(self) -> float:
        return len(self.cells) * self.resolution_m ** 2

    def by_family(self) -> dict[int, list[Cell]]:
        out: dict[int, list[Cell]] = {}
        for c in self.cells:
            out.setdefault(c.family, []).append(c)
        return out


def _nearest_edge(px: float, py: float, poly) -> tuple[int, float]:
    best_i, best_d = 0, float("inf")
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        span = ex * ex + ey * ey
        t = 0.0 if span == 0 else max(0.0, min(1.0, ((px - ax) * ex + (py - ay) * ey) / span))
        d = math.hypot(px - (ax + t * ex), py - (ay + t * ey))
        if d < best_d:
            best_i, best_d = i, d
    return best_i, best_d


def build_field(boundary_m, families: list[GridFamily],
                resolution_m: float = 3.6) -> CellField:
    """
    Rasterise the site and tag every cell with the grid it belongs to.

    The raster is a plain axis-aligned lattice, NOT one of the families'
    grids, and that is on purpose: with two families no single lattice
    can carry both, and this field is analysis rather than construction.
    It answers "what is here" -- inside, which grid, how far from the
    edge -- and placement then uses the family's own grid.

    Family assignment is by NEAREST EDGE, which is what produces the seam
    without anyone drawing one. See the module docstring.
    """
    xs = [p[0] for p in boundary_m]
    ys = [p[1] for p in boundary_m]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    # Which family does each edge belong to?
    edge_family = {}
    for fi, fam in enumerate(families):
        for ax in fam.axes:
            edge_family[ax.edge_index] = fi

    poly = [Point(x, y) for x, y in boundary_m]
    cells: list[Cell] = []
    index: dict[tuple[int, int], Cell] = {}

    nx = int((x1 - x0) / resolution_m) + 1
    ny = int((y1 - y0) / resolution_m) + 1
    for i in range(nx):
        for j in range(ny):
            px = x0 + (i + 0.5) * resolution_m
            py = y0 + (j + 0.5) * resolution_m
            if not point_in_polygon(Point(px, py), poly):
                continue
            e, d = _nearest_edge(px, py, boundary_m)
            # An edge too short to give an axis has no family of its own;
            # fall back to the dominant one rather than inventing a zone.
            cell = Cell(i, j, round(px, 2), round(py, 2),
                        edge_family.get(e, 0), e, round(d, 2))
            cells.append(cell)
            index[(i, j)] = cell

    # The seam: cells with a 4-neighbour of a different family. This is
    # the line where one grid hands over to the other, and it is where
    # the awkward junction detail will have to live.
    for c in cells:
        for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            other = index.get((c.ix + di, c.iy + dj))
            if other is not None and other.family != c.family:
                c.seam = True
                break

    return CellField(resolution_m, cells, families, (x0, y0, x1, y1))


# --- drawing the grid ------------------------------------------------

def grid_lines(family: GridFamily, boundary_m, spacing_m: float = 3.6,
               origin_m: tuple[float, float] = (0.0, 0.0)) -> list[list]:
    """
    The family's lattice, clipped to the site -- the coloured lines in
    Adela's grid-extraction sketch.

    Returned as [[x0, y0, x1, y1], ...] in metres. Both directions of the
    grid are emitted, so one family gives the blue AND the orange of that
    drawing; a second family gives the purple.
    """
    out = []
    for ux, uy in (family.u, family.v):
        px, py = -uy, ux                     # across the lines
        # How far the site spans across this direction, measured from the
        # origin so two families anchored on the same point stay in
        # register where they meet.
        ts = [(p[0] - origin_m[0]) * px + (p[1] - origin_m[1]) * py
              for p in boundary_m]
        k0 = math.floor(min(ts) / spacing_m)
        k1 = math.ceil(max(ts) / spacing_m)
        for k in range(k0, k1 + 1):
            offset = k * spacing_m
            base = (origin_m[0] + px * offset, origin_m[1] + py * offset)
            seg = _clip_line(base, (ux, uy), boundary_m)
            if seg is not None:
                out.append([round(v, 2) for v in (*seg[0], *seg[1])])
    return out


def _clip_line(base, direction, poly):
    """Where an infinite line crosses a convex polygon.

    Parametric clip against each edge's half-plane. Returns None when the
    line misses the polygon entirely, which is most of them -- a lattice
    covering the bounding box is mostly outside a triangle.
    """
    ux, uy = direction
    lo, hi = -1e9, 1e9
    n = len(poly)
    # Inward normal depends on winding; measure it rather than assume.
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1]
               for i in range(n))
    sign = 1.0 if area > 0 else -1.0

    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        nx, ny = -ey * sign, ex * sign        # inward normal
        denom = ux * nx + uy * ny
        num = (ax - base[0]) * nx + (ay - base[1]) * ny
        if abs(denom) < 1e-12:
            if num > 0:
                return None                   # parallel and outside
            continue
        t = num / denom
        if denom > 0:
            lo = max(lo, t)
        else:
            hi = min(hi, t)
        if lo > hi:
            return None
    if hi - lo < 1e-6:
        return None
    return ((base[0] + ux * lo, base[1] + uy * lo),
            (base[0] + ux * hi, base[1] + uy * hi))


def analyse(boundary_m, names=None, resolution_m: float = 3.6,
            spacing_m: float = 3.6) -> dict:
    """Everything the UI needs to draw the grid-extraction diagram."""
    axes = extract_axes(boundary_m, names)
    fams = grid_families(axes)
    fieldd = build_field(boundary_m, fams, resolution_m)
    counts = {fi: len(cs) for fi, cs in fieldd.by_family().items()}
    return {
        "resolution_m": resolution_m,
        "spacing_m": spacing_m,
        "axes": [
            {"name": a.name, "bearing_deg": a.bearing_deg,
             "support_m": a.support_m, "edge": a.edge_index}
            for a in axes
        ],
        "separations": [
            {"a": axes[i].name, "b": axes[j].name,
             "deg": round(axis_separation(axes[i].bearing_deg,
                                          axes[j].bearing_deg), 1)}
            for i in range(len(axes)) for j in range(i + 1, len(axes))
        ],
        "families": [
            {"index": i, "name": f.name, "bearing_deg": f.bearing_deg,
             "support_m": round(f.support_m, 1),
             "cells": counts.get(i, 0),
             "area_m2": round(counts.get(i, 0) * resolution_m ** 2, 0),
             "lines_m": grid_lines(f, boundary_m, spacing_m)}
            for i, f in enumerate(fams)
        ],
        "cells": [
            {"x": c.x, "y": c.y, "f": c.family, "d": c.edge_dist_m,
             "seam": c.seam}
            for c in fieldd.cells
        ],
        "seam_cells": sum(1 for c in fieldd.cells if c.seam),
        "total_cells": len(fieldd.cells),
    }
