"""
main.py
FastAPI wrapper around growth_engine.

The engine itself stays a pure-stdlib library with no web dependency --
this module is a thin adapter over it, so the engine remains usable
from a plain Python REPL, from Claude Code, and (eventually) from a
GHPython adapter, exactly as PROJECT_SUMMARY intends.

Run:
    cd backend
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import io
import json

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from growth_engine import (
    UNIT_CATALOG,
    generate_floorplan,
    generate_massing,
    generate_room_massing,
    massing_summary,
    plan_to_obj,
)
from growth_engine.growth import CORE_SIZE_CM, CORRIDOR_WIDTH_CM
from growth_engine.shared_spaces import INDOOR_KEYS, OUTDOOR_KEYS, SHARED_CATALOG
from growth_engine.frame import STOREY_CM, build_frame, frame_summary
from growth_engine.facade import (
    PANEL_ROLES, build_facade, column_alignment, facade_summary, verify_facade,
)
from growth_engine.frame import GRID_CM
from growth_engine.facade_import import load_facades
from growth_engine.solar import apply_solar
from growth_engine.site_grid import analyse
from growth_engine.growth_site import generate_site_floorplan, generate_spine_floorplan
from growth_engine.site.location import DEFAULT_SITE, site_fit
from growth_engine.site.location import _area as _poly_area
from growth_engine.preview import render_svg

from growth_engine.diagnostics import (
    access_report, shared_boundaries, verify_walls, wall_length,
)
from growth_engine.geometry import polygon_area as _poly_area_pts

from .schemas import (
    RESIDENTIAL,
    BlockOut,
    CatalogResponse,
    ElementOut,
    FacadeCatalogResponse,
    FacadeMemberOut,
    FacadePanelOut,
    FacadePanelType,
    FacadeResponse,
    FrameMemberOut,
    FrameNodeOut,
    FrameResponse,
    MassingResponse,
    PlanRequest,
    PlanResponse,
    RoomInfo,
    RoomOut,
    SegmentOut,
    SharedSegment,
    SharedSpaceInfo,
    SiteGridResponse,
    SiteResponse,
    UnitInfo,
    WallOut,
)

app = FastAPI(
    title="LinX Growth Engine API",
    description="Generative floor plan + massing engine for the timber joinery system.",
    version="0.1.0",
)

# The Vite dev server runs on 5173; the preview build on 4173.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:4173", "http://127.0.0.1:4173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _site_boundary(req: PlanRequest):
    """The site as growth wants it: Points, cm, entrance at the origin."""
    if not req.constrain_to_site:
        return None
    from growth_engine.geometry import Point
    return [Point(x, y) for x, y in DEFAULT_SITE.boundary_cm(req.site_inset_m)]


def _build_plan(req: PlanRequest):
    """Generate a plan, raising a 400 rather than a 500 for a bad program."""
    if not req.program:
        raise HTTPException(400, "program is empty")
    try:
        if req.strategy == "spine":
            # growth.py's own logic, re-based: entrance on a real street
            # and the whole armature turned onto a site grid.
            return generate_spine_floorplan(
                program=list(req.program), site=DEFAULT_SITE, seed=req.seed,
                inset_m=req.site_inset_m, entrance_edge=req.entrance_edge,
                resolution_cm=req.grid_resolution_cm,
                branch_depth=req.branch_depth,
                program_repeat=req.program_repeat,
                street_names=["Coffey St", "Deptford Church St", "Crossfield St"],
            )
        if req.strategy == "site":
            # The site strategy takes the plot itself rather than a
            # boundary polygon: it needs the edges to read grids off, not
            # just a region to stay inside.
            return generate_site_floorplan(
                program=list(req.program), site=DEFAULT_SITE, seed=req.seed,
                inset_m=req.site_inset_m, entrance_edge=req.entrance_edge,
                resolution_cm=req.grid_resolution_cm,
                street_names=["Coffey St", "Deptford Church St", "Crossfield St"],
            )
        return generate_floorplan(program=list(req.program), seed=req.seed,
                                  boundary=_site_boundary(req),
                                  branch_depth=req.branch_depth)
    except KeyError as e:
        raise HTTPException(400, f"unknown unit type: {e}") from e


def _classify_program(program: list[str]) -> tuple[list[str], list[str]]:
    """
    The engine treats ANY key it doesn't recognise as a flexible room --
    that is deliberate (it is how SK/SL worked before there was a shared
    catalog, and it is still the fallback), but it means a typo silently
    becomes a blank box instead of failing. We can't reject unknown keys
    without breaking that, so instead report them: `communal` is every
    non-residential key, and `suspect` is the subset that is in NEITHER
    catalog and looks like a misspelt unit type, which the UI warns
    about.

    A key in SHARED_CATALOG is never suspect -- it is a real brief with
    a real size range, not a guess.
    """
    communal, suspect = [], []
    lower = {k.lower(): k for k in UNIT_CATALOG}
    for key in dict.fromkeys(program):
        if key in UNIT_CATALOG:
            continue
        communal.append(key)
        if key in SHARED_CATALOG:
            continue
        k = key.lower()
        if k in lower or any(k.startswith(c[:6]) for c in lower):
            suspect.append(key)
    return communal, suspect


def _room_polys(el):
    """World-space room polygons, mirroring massing.generate_room_massing."""
    from growth_engine.catalog import get_unit
    from growth_engine.geometry import Point, normalize

    try:
        unit = get_unit(el.label)
    except KeyError:
        return []
    if not unit.has_real_rooms:
        return []
    c1, c2, _c3, c4 = el.corners
    along = normalize(Point(c2.x - c1.x, c2.y - c1.y))
    out = normalize(Point(c4.x - c1.x, c4.y - c1.y))
    result = []
    for room in unit.rooms:
        poly = []
        for rx, ry in ((room.x_min, room.y_min), (room.x_max, room.y_min),
                       (room.x_max, room.y_max), (room.x_min, room.y_max)):
            p = c1 + along.scaled(rx) + out.scaled(ry)
            poly.append([round(p.x, 2), round(p.y, 2)])
        result.append(RoomOut(name=room.name, poly=poly,
                              z_min=room.z_min, height_cm=room.height_cm))
    return result


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "units": len(UNIT_CATALOG)}


@app.get("/api/catalog", response_model=CatalogResponse)
def catalog() -> CatalogResponse:
    units = []
    for name in sorted(UNIT_CATALOG):
        u = UNIT_CATALOG[name]
        units.append(UnitInfo(
            name=u.name, width_cm=u.width_cm, depth_cm=u.depth_cm,
            height_cm=u.height_cm, floors=u.floors,
            object_count=u.object_count, has_real_rooms=u.has_real_rooms,
            footprint_area_m2=round(u.footprint_area_m2, 2),
            rooms=[RoomInfo(name=r.name, width_cm=round(r.width_cm, 1),
                            depth_cm=round(r.depth_cm, 1),
                            height_cm=round(r.height_cm, 1),
                            z_min=round(r.z_min, 1),
                            area_m2=round(r.area_m2, 2)) for r in u.rooms],
        ))
    shared = [
        SharedSpaceInfo(
            name=s.name, kind=s.kind,
            frontage_cm=list(s.frontage_cm), depth_cm=list(s.depth_cm),
            min_area_m2=round(s.min_area_m2, 1),
            max_area_m2=round(s.max_area_m2, 1),
            description=s.description,
        )
        for s in SHARED_CATALOG.values()
    ]
    return CatalogResponse(
        units=units,
        shared_spaces=shared,
        communal_keys=list(INDOOR_KEYS),
        outdoor_keys=list(OUTDOOR_KEYS),
        residential_keys=list(RESIDENTIAL),
        corridor_width_cm=CORRIDOR_WIDTH_CM,
        core_size_cm=CORE_SIZE_CM,
    )


@app.post("/api/plan", response_model=PlanResponse)
def plan(req: PlanRequest) -> PlanResponse:
    fp = _build_plan(req)

    elements = [
        ElementOut(
            kind=el.kind, label=el.label, height_cm=el.height_cm,
            corners=[[round(c.x, 2), round(c.y, 2)] for c in el.corners],
            wall_ids=list(el.wall_ids),
            rooms=_room_polys(el),
            level=el.level, z0=el.z0,
        )
        for el in fp.elements
    ]

    walls = [
        WallOut(
            id=w.id,
            owners=list(w.owners),
            owner_labels=[fp.elements[i].label for i in w.owners],
            shared=w.shared,
            length_cm=round(w.length_cm, 2),
            # Walls are resolved per storey, so every owner of a wall is
            # on the same level by construction.
            level=w.level,
            segments=[SegmentOut(c=s.component,
                                 p=[round(s.start.x, 2), round(s.start.y, 2),
                                    round(s.end.x, 2), round(s.end.y, 2)])
                      for s in w.segments],
        )
        for w in fp.walls
    ]

    xs = [c[0] for e in elements for c in e.corners]
    ys = [c[1] for e in elements for c in e.corners]

    perim = wall_length(fp.elements)
    shared_len, shared_segs = shared_boundaries(fp.elements)

    # Footprint is what the building covers on the GROUND; floor area is
    # every storey added up. They were the same number until the plan
    # started stacking, and conflating them would make a compact scheme
    # look like it lost area.
    #
    # Outdoor areas are neither. A garden is not floor area and it is not
    # building footprint -- counting it as either would inflate the
    # scheme's density on paper by exactly the amount of open ground it
    # provides, which is backwards. It gets its own total.
    footprint = 0.0
    floor_area = 0.0
    outdoor_area = 0.0
    # Zipped against fp.elements because the shoelace needs Points, and
    # `elements` has already been flattened to lists for the wire.
    for el, e in zip(fp.elements, elements):
        # Shoelace, not the bounding box -- see geometry.polygon_area.
        # A rotated element's box over-reports it, which would credit the
        # scheme with floor area it does not have.
        area = _poly_area_pts(el.corners) / 10000
        if e.kind == "outdoor":
            outdoor_area += area
            continue
        floor_area += area
        if e.level == 0:
            footprint += area

    return PlanResponse(
        elements=elements,
        walls=walls,
        shared_segments=[SharedSegment(**s) for s in shared_segs],
        wall_check=verify_walls(fp),
        entrance=[fp.entrance.x, fp.entrance.y],
        core_position=[fp.core_position.x, fp.core_position.y],
        unit_counts=fp.unit_counts,
        missing=[p for p in req.program if p not in fp.unit_counts],
        communal=_classify_program(req.program)[0],
        suspect=_classify_program(req.program)[1],
        extent_cm=[min(xs), min(ys), max(xs), max(ys)],
        # Whether the building this program produced actually lands on
        # the site. REPORTED, not enforced -- growth.py still knows
        # nothing about the boundary, which is the open item.
        site_fit={
            **site_fit(DEFAULT_SITE, [el.corners for el in fp.elements],
                       req.site_inset_m),
            "constrained": req.constrain_to_site,
            # Anything the constraint could not stop -- the entry run and
            # the core are laid down before any test can run. Empty is
            # the expected answer, not a guaranteed one.
            "off_site": fp.off_site,
            # Adela's two design targets: a 20m walk to a stair, and
            # 30-40% of the ground floor green. Measured, not asserted.
            **access_report(fp),
        },
        level_count=fp.level_count,
        stats={
            # What actually gets built, now that shared walls resolve to
            # one wall each. This is the figure a take-off should use.
            "wall_length_m": round(sum(w.length_cm for w in fp.walls) / 100, 1),
            "wall_count": float(len(fp.walls)),
            "shared_wall_count": float(sum(1 for w in fp.walls if w.shared)),
            "shared_length_m": round(shared_len / 100, 1),
            # What the same plan measured before deduplication, kept so
            # the saving stays visible rather than silently disappearing.
            "naive_length_m": round(perim / 100, 1),
            "saved_pct": round(100 * shared_len / perim, 1) if perim else 0.0,
            "footprint_m2": round(footprint, 1),
            "floor_area_m2": round(floor_area, 1),
            "outdoor_area_m2": round(outdoor_area, 1),
            "level_count": float(fp.level_count),
            "shared_count": float(len(shared_segs)),
        },
    )


@app.post("/api/massing", response_model=MassingResponse)
def massing(req: PlanRequest) -> MassingResponse:
    fp = _build_plan(req)
    blocks = generate_room_massing(fp) if req.per_room else generate_massing(fp)
    return MassingResponse(
        blocks=[BlockOut(kind=b.kind, label=b.label,
                         base_corners=[[round(c.x, 2), round(c.y, 2)] for c in b.base_corners],
                         z0=round(b.z0, 2), z1=round(b.z1, 2),
                         element_index=b.element_index,
                         growth_step=b.growth_step) for b in blocks],
        summary=massing_summary(blocks),
        growth_steps=(max((b.growth_step for b in blocks), default=-1) + 1),
    )


@app.post("/api/frame", response_model=FrameResponse)
def frame(req: PlanRequest) -> FrameResponse:
    """The timber frame -- posts and beams -- ordered by parasitic
    spread outward from the entrance. See growth_engine.frame."""
    fp = _build_plan(req)
    fr = build_frame(fp, joint_blocks=req.joint_blocks,
                     course_cm=req.course_cm or STOREY_CM)
    return FrameResponse(
        members=[
            FrameMemberOut(
                kind=m.kind, component=m.component,
                c=[round(m.cx, 1), round(m.cy, 1), round(m.cz, 1)],
                s=[round(m.sx, 1), round(m.sy, 1), round(m.sz, 1)],
                angle=round(m.angle, 4), growth_step=m.growth_step,
                grow_sign=m.grow_sign,
            )
            for m in fr.members
        ],
        nodes=[
            FrameNodeOut(id=n.id, x=round(n.x, 1), y=round(n.y, 1),
                         height_cm=round(n.height_cm, 1),
                         wall_count=n.wall_count, is_junction=n.is_junction,
                         depth=n.depth)
            for n in fr.nodes
        ],
        growth_steps=fr.growth_steps,
        step_labels=fr.step_labels,
        summary=frame_summary(fr),
    )


@app.get("/api/site", response_model=SiteResponse)
def site(inset_m: float = 6.0) -> SiteResponse:
    """The real site. Static for a given inset, so the client fetches it
    once beside the catalogs."""
    s = DEFAULT_SITE
    return SiteResponse(
        name=s.name, address=s.address, lat=s.lat, lon=s.lon,
        area_m2=round(s.area_m2, 0),
        developable_area_m2=round(_poly_area(s.boundary(inset_m)), 0),
        inset_m=inset_m,
        rotation_deg=s.rotation_deg,
        boundary_cm=[[round(x, 1), round(y, 1)] for x, y in s.boundary_cm(inset_m)],
        centreline_cm=[[round(x, 1), round(y, 1)] for x, y in s.boundary_cm(0.0)],
        source=s.source, notes=list(s.notes),
    )


@app.get("/api/site/grid", response_model=SiteGridResponse)
def site_grid(inset_m: float = 6.0, resolution_cm: float = 360.0,
              spacing_cm: float = 360.0) -> SiteGridResponse:
    """The candidate grids the site's own edges give, and the seam where
    one hands over to the other."""
    s = DEFAULT_SITE
    names = ["Coffey St", "Deptford Church St", "Crossfield St"]
    d = analyse(s.boundary(inset_m), names,
                resolution_m=resolution_cm / 100.0,
                spacing_m=spacing_cm / 100.0)

    # Everything crosses the wire in cm relative to the ENTRANCE, so it
    # lands on the same frame as the plan. site_grid works in metres from
    # the site origin, so this is the one place they are reconciled.
    ox, oy = s.origin_m

    def to_cm_xy(x, y):
        return [round((x - ox) * 100, 1), round((y - oy) * 100, 1)]

    for fam in d["families"]:
        fam["lines_cm"] = [
            [*to_cm_xy(a, b), *to_cm_xy(c, e)]
            for a, b, c, e in fam.pop("lines_m")
        ]
    cells = [
        {"c": to_cm_xy(c["x"], c["y"]), "f": c["f"], "seam": c["seam"]}
        for c in d["cells"]
    ]
    return SiteGridResponse(
        resolution_cm=resolution_cm, spacing_cm=spacing_cm,
        axes=d["axes"], separations=d["separations"], families=d["families"],
        cells=cells, seam_cells=d["seam_cells"], total_cells=d["total_cells"],
    )


@app.get("/api/facade/catalog", response_model=FacadeCatalogResponse)
def facade_catalog() -> FacadeCatalogResponse:
    """The nine panel types with their member geometry.

    Separate from /api/facade because it is STATIC -- ~1500 members that
    do not depend on the program, so the client fetches it once and
    instances it, instead of re-downloading 200KB on every regenerate.
    """
    data = load_facades()
    if data is None:
        raise HTTPException(
            503,
            "facade catalog not generated — run: "
            'python -m growth_engine.facade_import "path/to/facade panel glb"',
        )
    panels = []
    # Blank to most open, so the UI legend is in a meaningful order
    # without having to know the roles table.
    for key in sorted(data["panels"], key=lambda k: (PANEL_ROLES.get(k, {}).get("glazing", 0), k)):
        p = data["panels"][key]
        role = PANEL_ROLES.get(key, {})
        panels.append(FacadePanelType(
            key=key,
            label=role.get("label", key),
            note=role.get("note", ""),
            use=role.get("use", "any"),
            glazing=role.get("glazing", 0),
            width_cm=p["width_cm"], height_cm=p["height_cm"],
            depth_cm=p["depth_cm"], projection_cm=p["projection_cm"],
            members=[FacadeMemberOut(c=m["c"], s=m["s"]) for m in p["members"]],
        ))
    return FacadeCatalogResponse(panel_width_cm=data["panel_width_cm"], panels=panels)


@app.post("/api/facade", response_model=FacadeResponse)
def facade(req: PlanRequest) -> FacadeResponse:
    """Which panel clads which bay. Instances only -- the geometry they
    reference comes from /api/facade/catalog."""
    fp = _build_plan(req)
    align = req.align if req.align in ("run", "grid") else "run"
    fa = build_facade(fp, align=align)
    # Always run: ~160ms on the default program, and the heatmap is a
    # display toggle rather than a different request, so the client can
    # switch it on without a refetch.
    solar = apply_solar(fa, fp, latitude_deg=req.latitude)
    return FacadeResponse(
        panels=[
            FacadePanelOut(
                panel=p.panel, c=[round(p.cx, 2), round(p.cy, 2)],
                z0=round(p.z0, 2), angle=round(p.angle, 4),
                level=p.level, owner=p.owner, rule=p.rule,
                sun_kwh=p.sun_kwh, sun_norm=p.sun_norm,
            )
            for p in fa.panels
        ],
        summary=facade_summary(fa),
        # In grid mode neighbours are a structural bay apart, not a panel
        # width; handing verify the wrong spacing makes every joint read
        # as a gap.
        connection_check=verify_facade(
            fa, step_cm=GRID_CM if align == "grid" else None),
        alignment={**column_alignment(fa, fp), "mode": align},
        solar=solar,
    )


@app.post("/api/export/obj")
def export_obj(req: PlanRequest) -> Response:
    fp = _build_plan(req)
    body = plan_to_obj(fp, per_room=req.per_room)
    return Response(
        content=body, media_type="model/obj",
        headers={"Content-Disposition": 'attachment; filename="growth_engine.obj"'},
    )


@app.post("/api/export/svg")
def export_svg(req: PlanRequest) -> Response:
    fp = _build_plan(req)
    body = render_svg(fp, title=f"Generated floor plan - seed {req.seed}")
    return Response(
        content=body, media_type="image/svg+xml",
        headers={"Content-Disposition": 'attachment; filename="plan.svg"'},
    )


@app.post("/api/export/json")
def export_json(req: PlanRequest) -> Response:
    from growth_engine.preview import plan_to_dict

    fp = _build_plan(req)
    body = json.dumps(plan_to_dict(fp), indent=2)
    return Response(
        content=body, media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="plan.json"'},
    )
