"""
growth_engine
Pure Python generative layout engine: entrance -> corridor -> core ->
branching corridors -> real-dimension residential units + flexible
communal spaces, with a massing (3D extrusion) step on top.

No Rhino/Grasshopper dependency. Intended usage from Claude Code:

    from growth_engine import generate_floorplan, generate_massing

    plan = generate_floorplan(
        program=["Studio_A", "1Bed_B", "SK", "2Bed_A", "SL", "3Bed_A"],
        seed=42,
    )
    blocks = generate_massing(plan)

Export to OBJ/Rhino geometry is intentionally NOT included yet --
that's a planned next step once the growth logic itself is settled.
"""

from .geometry import Point, polygons_overlap, point_in_polygon
from .catalog import UNIT_CATALOG, UnitType, RoomComponent, get_unit, load_catalog_from_dir, load_unit_from_export
from .growth import generate_floorplan, FloorPlan, PlacedElement, CORRIDOR_WIDTH_CM, CORE_SIZE_CM
from .walls import Wall, resolve_walls, wall_summary
from .massing import generate_massing, generate_room_massing, massing_summary, MassingBlock
from .export import plan_to_obj, blocks_to_obj, save_obj

__all__ = [
    "plan_to_obj", "blocks_to_obj", "save_obj",
    "Point", "polygons_overlap", "point_in_polygon",
    "UNIT_CATALOG", "UnitType", "RoomComponent", "get_unit", "load_catalog_from_dir", "load_unit_from_export",
    "generate_floorplan", "FloorPlan", "PlacedElement",
    "Wall", "resolve_walls", "wall_summary",
    "CORRIDOR_WIDTH_CM", "CORE_SIZE_CM",
    "generate_massing", "generate_room_massing", "massing_summary", "MassingBlock",
]
