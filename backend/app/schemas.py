"""
schemas.py
Request/response models for the growth engine API.

All geometry crosses the wire in CENTIMETRES, matching the engine's
internal units. The frontend converts for display; nothing converts on
the way out, so there is exactly one place a unit error can be
introduced (and see growth.py for what happened last time there were
two).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from growth_engine.site.location import DEFAULT_SITE

# Keys the engine treats as real residential units; anything else in a
# program is built as a flexible shared space (see
# growth_engine.shared_spaces).
RESIDENTIAL = (
    "Studio_A", "Studio_B", "1Bed_A", "1Bed_B", "2Bed_A",
    "2Bed_B", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
)

# A full mixed brief rather than housing alone: every unit type, the
# shared rooms that make it a building rather than a corridor of flats,
# and the open ground. Kept in step with the copy in frontend App.jsx --
# that one is the UI's initial state, this one is the API default for a
# request that omits `program`.
DEFAULT_PROGRAM = [
    "Lobby", "Studio_A", "Studio_B", "1Bed_A", "1Bed_B", "SK",
    "Workspace", "2Bed_A", "2Bed_B", "SL", "Gym", "3Bed_A",
    "3Bed_B", "Library", "4Bed_A", "4Bed_B", "Garden", "Playground",
]


class PlanRequest(BaseModel):
    program: list[str] = Field(default_factory=lambda: list(DEFAULT_PROGRAM))
    seed: int | None = 42
    per_room: bool = True
    # /api/frame only: place the full 240x240 woven capital on every
    # column. Off by default because the bare column reads more clearly
    # while judging the plan -- it fits at every node on the 360 grid.
    # See growth_engine.frame.
    joint_blocks: bool = False
    # /api/frame only: vertical pitch of the beam courses filling each
    # wall. None means one course per storey, i.e. the ceiling beam
    # alone -- the frame as the Frame view has always drawn it. The
    # Build view asks for a finer pitch to fill the massing envelope.
    course_cm: float | None = None
    # /api/facade only: latitude for the solar analysis, degrees north.
    # Defaults to the REAL SITE rather than a placeholder -- a literal
    # here silently shadowed the site once already, which is the kind of
    # bug that shows up as a plausible-looking sun map.
    latitude: float = DEFAULT_SITE.lat
    # /api/facade only: "run" butts panels at their own 330cm width and
    # centres the run on the wall; "grid" puts one panel per 360cm
    # structural bay so every joint lands on a column. See
    # growth_engine.facade for what each costs.
    align: str = "run"
    # Keep growth inside the real site. On by default: the project has a
    # plot, and a building that ignores it is a different drawing.
    constrain_to_site: bool = True
    # "branch" is the original growth: entrance inside the plot, spine,
    # core, three orthogonal arms. "site" is the perimeter-block strategy
    # that enters from the street and lays out on the grids the plot's
    # own edges give. See growth_engine.growth_site.
    strategy: str = "branch"
    # Which boundary edge the entrance sits on, for strategy="site".
    # 1 is Deptford Church Street, the main road.
    entrance_edge: int = 1
    # Cell size for the residual/green pass, cm.
    grid_resolution_cm: float = 90.0
    # Setback from the street centrelines the boundary is measured on.
    site_inset_m: float = 6.0


class RoomOut(BaseModel):
    name: str
    poly: list[list[float]]
    z_min: float
    height_cm: float


class SegmentOut(BaseModel):
    c: str                # "N" | "SA" | "SB" | "SC"
    p: list[float]        # [x1, y1, x2, y2]


class WallOut(BaseModel):
    """One PHYSICAL wall, built once. A wall on the boundary between two
    elements is referenced by both but appears here a single time."""
    id: int
    owners: list[int]              # indices into `elements`
    owner_labels: list[str]
    shared: bool
    length_cm: float
    # Which storey it stands on. Walls resolve per level, so a wall
    # above another is a different wall, not the same one seen twice.
    level: int
    segments: list[SegmentOut]


class ElementOut(BaseModel):
    # "corridor" | "core" | "unit" | "communal" | "outdoor". An outdoor
    # element is ground, not a room: it has no wall_ids, no rooms, and a
    # token height rather than a storey.
    kind: str
    label: str
    height_cm: float
    corners: list[list[float]]
    wall_ids: list[int]   # into PlanResponse.walls
    rooms: list[RoomOut]
    # Storey index, 0 = ground, and the height of its floor slab. A
    # duplex is listed once, at its lower level, and is 600cm tall.
    level: int = 0
    z0: float = 0.0


class SharedSegment(BaseModel):
    """One stretch of wall that two elements both build. See
    growth_engine.diagnostics for why this is worth reporting."""
    a: str
    b: str
    length_cm: float
    p: list[float]        # [x1, y1, x2, y2]


class PlanResponse(BaseModel):
    elements: list[ElementOut]
    walls: list[WallOut]
    shared_segments: list[SharedSegment]
    # Report from diagnostics.verify_walls -- proves the wall set really
    # is deduplicated rather than asking the client to trust it.
    wall_check: dict
    entrance: list[float]
    core_position: list[float]
    unit_counts: dict[str, int]
    missing: list[str]
    # Every non-residential key in the program, i.e. everything built as
    # a flexible shared space. `suspect` is the subset that matches
    # neither catalog and looks like a misspelt unit type -- see
    # _classify_program in main.py.
    communal: list[str]
    suspect: list[str]
    extent_cm: list[float]
    # Whether this building lands on the real site. Reported, not
    # enforced -- growth.py does not know about the boundary yet.
    site_fit: dict = Field(default_factory=dict)
    # How many storeys the program needed. The plan view filters on it.
    level_count: int = 1
    stats: dict[str, float]


class BlockOut(BaseModel):
    kind: str
    label: str
    base_corners: list[list[float]]
    z0: float
    z1: float
    element_index: int
    # Where this block's element sits in the growth sequence -- entrance
    # -> corridor -> core -> branch corridors -> rooms. Blocks sharing a
    # step grow together, so a unit's rooms rise as one unit. See
    # growth._assign_growth_steps for why this is not element_index.
    growth_step: int


class MassingResponse(BaseModel):
    blocks: list[BlockOut]
    summary: dict[str, dict]
    # Number of distinct growth steps, so a client can size a timeline
    # without scanning every block.
    growth_steps: int


class FrameMemberOut(BaseModel):
    """One timber member. Centre `c` and size `s` are packed as arrays
    rather than named fields because a frame runs to a few thousand
    members and the field names would dominate the payload."""
    # "post" | "plate" | "beam" | "infill" | "floor" | "ceiling" | "lacing"
    kind: str
    component: str        # "N" | "SA" | "SB" | "SC" | "Deck" | "Ceiling" | ...
    c: list[float]        # centre [x, y, z], cm
    s: list[float]        # size [length, width, depth], cm
    angle: float          # radians about the vertical axis
    growth_step: int
    grow_sign: int


class FrameNodeOut(BaseModel):
    id: int
    x: float
    y: float
    height_cm: float
    wall_count: int
    # True where 3+ walls meet -- a T or a cross, the splayed capital.
    is_junction: bool
    depth: int            # BFS distance from the entrance node


class FrameResponse(BaseModel):
    members: list[FrameMemberOut]
    nodes: list[FrameNodeOut]
    # Growth here is TOPOLOGICAL, not program order: posts rise at BFS
    # depth d on step 2d, beams reach out from them on step 2d+1.
    growth_steps: int
    step_labels: list[str]
    summary: dict


class FacadeMemberOut(BaseModel):
    """One timber member inside a panel, in PANEL-LOCAL centimetres:
    x along the wall, y across it with 0 on the wall centre line and -y
    outward, z up from the panel's own floor slab. Packed as arrays for
    the same reason FrameMemberOut is -- there are ~1500 of them."""
    c: list[float]        # centre [x, y, z]
    s: list[float]        # size [x, y, z]


class FacadePanelType(BaseModel):
    key: str              # "A".."I"
    label: str
    note: str
    use: str              # "residential" | "shared" | "any"
    # Rank from blank to most open. The one axis all nine sit on, and
    # what the legend sorts by.
    glazing: int
    width_cm: float
    height_cm: float
    depth_cm: float
    # How far it reaches out past the column it sits on: 0 for the
    # unshaded panel, 116 for the balcony.
    projection_cm: float
    members: list[FacadeMemberOut]


class FacadeCatalogResponse(BaseModel):
    panel_width_cm: float
    panels: list[FacadePanelType]


class FacadePanelOut(BaseModel):
    panel: str            # "A".."I"
    c: list[float]        # [x, y] of the panel centre on the wall line, cm
    z0: float             # its floor slab
    angle: float          # radians about the vertical
    level: int
    owner: str            # the element it clads
    rule: str             # why this panel was chosen
    # Clear-sky irradiation on this panel's plane, and the same rescaled
    # 0..1 across the building so the heatmap uses its full range.
    sun_kwh: float = 0.0
    sun_norm: float = 0.0


class FacadeResponse(BaseModel):
    panels: list[FacadePanelOut]
    summary: dict
    # Proof the panels actually meet each other, vertically and
    # horizontally -- see growth_engine.facade.verify_facade. Reported on
    # every response, the way /api/plan reports wall_check.
    connection_check: dict
    # How the panel module lands against the structural column grid --
    # the one thing the two systems cannot both have on their own terms.
    alignment: dict
    solar: dict


class RoomInfo(BaseModel):
    name: str
    width_cm: float
    depth_cm: float
    height_cm: float
    z_min: float
    area_m2: float


class UnitInfo(BaseModel):
    name: str
    width_cm: float
    depth_cm: float
    height_cm: float
    floors: int
    object_count: int
    has_real_rooms: bool
    footprint_area_m2: float
    rooms: list[RoomInfo]


class SiteResponse(BaseModel):
    """The real site the project sits on. Boundary comes across in
    CENTIMETRES relative to the ENTRANCE, like everything else in the
    plan, so the client can draw it straight over the floor plan."""
    name: str
    address: str
    lat: float
    lon: float
    area_m2: float
    developable_area_m2: float
    inset_m: float
    rotation_deg: float
    # [[x, y], …] cm from the entrance, at inset_m, plus the raw
    # street-centreline outline for context.
    boundary_cm: list[list[float]]
    centreline_cm: list[list[float]]
    source: str
    notes: list[str]


class SiteGridResponse(BaseModel):
    """The grid read OFF the site — see growth_engine.site_grid.

    Geometry is in CENTIMETRES relative to the entrance, like the rest of
    the plan, so it overlays the floor plan directly."""
    resolution_cm: float
    spacing_cm: float
    axes: list[dict]
    # Acute angle between each pair, folded to 0..90: two axes 89° apart
    # describe the SAME grid, so this reports 1°, not 89°.
    separations: list[dict]
    # Each family carries its clipped lattice as [[x0,y0,x1,y1], …] cm.
    families: list[dict]
    cells: list[dict]
    seam_cells: int
    total_cells: int


class SharedSpaceInfo(BaseModel):
    """One flexible program entry. Unlike a UnitInfo these are RANGES,
    because a shared space has a brief rather than a survey -- the
    generator picks inside them and the seed is what varies the pick."""
    name: str
    kind: str                      # "communal" | "outdoor"
    # [min, max] along the corridor, and away from it.
    frontage_cm: list[float]
    depth_cm: list[float]
    min_area_m2: float
    max_area_m2: float
    description: str


class CatalogResponse(BaseModel):
    units: list[UnitInfo]
    # Every flexible space with its size range and blurb.
    shared_spaces: list[SharedSpaceInfo]
    # Names only, split the way the program editor groups them.
    # `communal_keys` is the indoor half and keeps its old name so an
    # existing client does not break.
    communal_keys: list[str]
    outdoor_keys: list[str]
    residential_keys: list[str]
    corridor_width_cm: float
    core_size_cm: float
