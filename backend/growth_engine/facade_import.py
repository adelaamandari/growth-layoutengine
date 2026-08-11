"""
facade_import.py
Read the facade panel GLBs (A..I) into a bundled catalog, standard
library only -- same approach as glb_import.py, which this reuses: GLB
is a JSON chunk plus a BIN chunk, every POSITION accessor is REQUIRED to
carry min/max, so per-member bounding boxes come straight out of the
JSON and the BIN chunk is never decoded.

WHAT THE SOURCE FILES CONTAIN
One file per panel type, each a flat list of unnamed meshes with no node
transforms -- geometry is baked in world space, so a bounding box is
already a world box. Members are the same 10x10 and 10x20 timber
sections the frame catalog uses.

Every panel measures 330 x 310 cm. The nine differ only in depth and in
how the members are arranged:

    A  292 members  110 deep   solid, upper floor, dense
    B  154 members  110 deep   solid, ground floor
    C   23 members   40 deep   no shading -- simple, applies to anything
    D  218 members  110 deep   one big window   (residential)
    E  250 members  110 deep   two windows      (residential)
    F  148 members  110 deep   three full windows (shared spaces)
    G  129 members  110 deep   two full windows   (shared spaces)
    H  114 members  110 deep   one full window    (shared spaces)
    I  184 members  156 deep   balcony

THE PANEL'S OWN GEOMETRY CONFIRMS THE BRIEF
Every panel carries a 40cm-deep column at its BACK: two rows of 10x10
posts 30cm apart, at local y in [depth-40, depth]. So the wall centre
line sits at y = depth - 20 in every file, and everything in front of it
is shading or balcony. That makes the outward projection depth - 40:

    C     0 cm   -- exactly zero, which is "no need for shading"
    A,B,D,E,F,G,H
         70 cm   -- the shading fins
    I   116 cm   -- a balcony

Nothing here was told to the importer; it falls out of the files, and it
is the check that the depth convention below is right side round.

COORDINATES OUT
Rebased to a panel-local frame, in centimetres, Z-up, matching the
engine:

    x   along the wall, centred:  -165 .. +165
    y   across the wall, ZERO ON THE WALL CENTRE LINE. The column
        occupies -20 .. +20 and the projection runs NEGATIVE, i.e. -y
        is outward. facade.py maps -y onto the wall's outward normal.
    z   above the panel's own floor slab, 0 .. ~310

Run it to regenerate the bundled catalog:

    python -m growth_engine.facade_import "path/to/facade panel glb"

Output goes to facade_exports/facades.json. The GLBs themselves (75MB)
are deliberately NOT committed -- the extracted JSON is ~200KB and is
what the engine actually reads.
"""

from __future__ import annotations

import json
from pathlib import Path

from .glb_import import MIN_SIZE_CM, _mesh_box, _read_gltf_json, _to_engine_cm

_EXPORTS_DIR = Path(__file__).parent / "facade_exports"
CATALOG_PATH = _EXPORTS_DIR / "facades.json"

# Every panel carries the 40cm column at its back; the wall centre line
# is half of that in from the rear face. See the module docstring -- this
# one number is what makes C come out at zero projection.
COLUMN_DEPTH_CM = 40.0

PANEL_KEYS = ("A", "B", "C", "D", "E", "F", "G", "H", "I")


def extract_panel(glb_path: str | Path) -> dict:
    """Parse one panel GLB into a member list in panel-local coordinates."""
    path = Path(glb_path)
    doc = _read_gltf_json(path)

    boxes = []
    for node in doc.get("nodes", []):
        if "mesh" not in node:
            continue
        box = _mesh_box(doc, node["mesh"])
        if box is None:
            continue
        b = _to_engine_cm(*box)
        # Zero-size markers sit at the panel's reference axes; they are
        # not members. Same guard catalog.py and glb_import.py apply.
        if ((b["x1"] - b["x0"]) <= MIN_SIZE_CM
                and (b["y1"] - b["y0"]) <= MIN_SIZE_CM
                and (b["z1"] - b["z0"]) <= MIN_SIZE_CM):
            continue
        boxes.append(b)

    if not boxes:
        raise ValueError(f"{path.name} has no members")

    x_lo = min(b["x0"] for b in boxes)
    x_hi = max(b["x1"] for b in boxes)
    y_hi = max(b["y1"] for b in boxes)
    y_lo = min(b["y0"] for b in boxes)

    ox = (x_lo + x_hi) / 2          # centre the panel on its own width
    oy = y_hi - COLUMN_DEPTH_CM / 2  # wall centre line -> y = 0

    # THE VERTICAL DATUM IS THE COLUMN, NOT THE BOUNDING BOX.
    #
    # Eight of the nine panels model their column at z 0..300 and let the
    # shading fins overhang to 310, which is correct: a fin laps over the
    # floor line of the storey above. D does not -- its whole panel sits
    # 10cm low, column at -10..290. Rebasing on the bounding box would
    # preserve that error and hang every D panel below its slab, with its
    # column stopping 10cm short of the beam it is supposed to meet.
    #
    # So the datum is taken from the members in the column zone (the 40cm
    # band on the wall centre line) rather than from the panel as a
    # whole. That puts every panel's column base on the storey floor, and
    # since a storey is 300 and a column is 300, a stack of panels then
    # runs column-onto-column with no gap and no overlap.
    col = [b for b in boxes if abs((b["y0"] + b["y1"]) / 2 - oy) <= COLUMN_DEPTH_CM / 2]
    oz = min(b["z0"] for b in col) if col else min(b["z0"] for b in boxes)

    members = [
        {
            "c": [round((b["x0"] + b["x1"]) / 2 - ox, 2),
                  round((b["y0"] + b["y1"]) / 2 - oy, 2),
                  round((b["z0"] + b["z1"]) / 2 - oz, 2)],
            "s": [round(b["x1"] - b["x0"], 2),
                  round(b["y1"] - b["y0"], 2),
                  round(b["z1"] - b["z0"], 2)],
        }
        for b in boxes
    ]

    col_z0 = min(b["z0"] for b in col) - oz if col else 0.0
    col_z1 = max(b["z1"] for b in col) - oz if col else 0.0

    # Overall dimensions round to 1dp: these are quoted figures, and the
    # source carries hundredths of a millimetre of modelling noise that
    # would otherwise surface in the UI as a 70.01cm projection. Member
    # geometry keeps its 2dp — that is built, not quoted.
    return {
        "width_cm": round(x_hi - x_lo, 1),
        "height_cm": round(max(b["z1"] for b in boxes)
                           - min(b["z0"] for b in boxes), 1),
        "depth_cm": round(y_hi - y_lo, 1),
        # How far the panel reaches out past the column it sits on. Zero
        # for C, and the number that makes I a balcony.
        "projection_cm": round(y_hi - y_lo - COLUMN_DEPTH_CM, 1),
        # Relative to the column base, which is the storey floor.
        "z0": round(min(b["z0"] for b in boxes) - oz, 2),
        "z1": round(max(b["z1"] for b in boxes) - oz, 2),
        # The structural extent -- what has to meet the panel above and
        # below. 0..300 in every panel once the datum is fixed; if this
        # ever comes out otherwise, the stack has a gap in it.
        "column_z0": round(col_z0, 2),
        "column_z1": round(col_z1, 2),
        "y_out_cm": round(oy - y_lo, 2),   # extent along -y, outward
        "y_in_cm": round(y_hi - oy, 2),    # extent along +y, inward
        "members": members,
    }


def extract(folder: str | Path) -> dict:
    """Parse a folder of A.glb .. I.glb into the bundled catalog."""
    folder = Path(folder)
    panels: dict[str, dict] = {}
    for key in PANEL_KEYS:
        path = folder / f"{key}.glb"
        if not path.exists():
            print(f"warning: {path.name} not found, skipping")
            continue
        panels[key] = extract_panel(path)
        panels[key]["source"] = path.name
    if not panels:
        raise ValueError(f"no panel GLBs found in {folder}")

    # One pitch for the whole set: they are the same module, and a
    # sub-millimetre spread is modelling noise, not a different panel.
    # (I comes out 330.02 -- the balcony's outer rail is a hair proud.)
    # Anything bigger than a centimetre is a real difference and would
    # mis-tile, since facade.py lays them out on a single pitch.
    widths = sorted(p["width_cm"] for p in panels.values())
    if widths[-1] - widths[0] > 1.0:
        print(f"warning: panels are not one module: {widths}")
    pitch = round(sum(widths) / len(widths), 1)

    return {
        "source": str(folder),
        "units": "cm",
        "panel_width_cm": pitch,
        "panels": panels,
    }


# --- J: guarding for the open decks ------------------------------------
#
# DERIVED, NOT SURVEYED. Every other panel here came out of a GLB Adela
# modelled; this one I generated, and it is kept obviously separate so
# nobody later reads it as catalog geometry. Replace it the moment there
# is a real part.
#
# It exists because the deck-access corridors are now left open (see
# facade._choose), and an open walkway three storeys up needs guarding.
# That is not a handrail: a handrail is the graspable rail, guarding is
# the barrier that stops the fall, and it needs infill.
#
# 110cm high with 6.5cm gaps between 10cm slats. UK Approved Document K
# puts external balcony guarding at 1100mm and says a 100mm sphere must
# not pass -- CHECK BOTH against the current edition before this is
# built from, they are here to make the geometry plausible, not to
# certify it.
#
# 20 slats at 16.5cm centres divides 330 exactly, so the gap ACROSS a
# joint between two panels is the same 6.5cm as the gaps within one.
# Getting that wrong is how a compliant panel makes a non-compliant
# balustrade.
GUARD_KEY = "J"
GUARD_HEIGHT_CM = 110.0
_GUARD_SLAT_W = 10.0
_GUARD_SLATS = 20


def derived_guard_panel(width_cm: float = 330.0) -> dict:
    """A simple slatted guard rail, generated rather than surveyed."""
    pitch = width_cm / _GUARD_SLATS
    rail_h = 10.0
    infill_h = GUARD_HEIGHT_CM - rail_h
    members = []
    for k in range(_GUARD_SLATS):
        x = -width_cm / 2 + pitch * (k + 0.5)
        members.append({"c": [round(x, 2), 0.0, round(infill_h / 2, 2)],
                        "s": [_GUARD_SLAT_W, 10.0, infill_h]})
    # The top rail, which is also the handrail.
    members.append({"c": [0.0, 0.0, GUARD_HEIGHT_CM - rail_h / 2],
                    "s": [width_cm, 20.0, rail_h]})
    return {
        "width_cm": width_cm,
        "height_cm": GUARD_HEIGHT_CM,
        "depth_cm": 20.0,
        "projection_cm": 0.0,
        "z0": 0.0, "z1": GUARD_HEIGHT_CM,
        # Deliberately its own height, not 0..300. It carries no column
        # and does not stack, and saying otherwise would make
        # verify_facade's alignment check agree with a fiction.
        "column_z0": 0.0, "column_z1": GUARD_HEIGHT_CM,
        "y_out_cm": 10.0, "y_in_cm": 10.0,
        "members": members,
        "source": "derived — not surveyed, see facade_import.derived_guard_panel",
    }


def load_facades(path: str | Path = CATALOG_PATH) -> dict | None:
    """Load the bundled extraction, or None if it has not been generated.

    The derived guard panel is added here rather than written into
    facades.json, so re-running the extraction from the GLBs never has to
    remember to put it back."""
    path = Path(path)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    data["panels"].setdefault(
        GUARD_KEY, derived_guard_panel(data.get("panel_width_cm", 330.0)))
    return data


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="Extract the facade panel GLBs into the bundled catalog.")
    ap.add_argument("folder", help="folder holding A.glb .. I.glb")
    ap.add_argument("--out", default=str(CATALOG_PATH))
    args = ap.parse_args(argv)

    data = extract(args.folder)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1))

    print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB)")
    print(f"  panel pitch {data['panel_width_cm']} cm")
    for key, p in data["panels"].items():
        print(f"  {key}  {len(p['members']):4d} members  "
              f"{p['width_cm']:.0f} x {p['height_cm']:.0f} cm, "
              f"{p['depth_cm']:.0f} deep, projects {p['projection_cm']:.0f} cm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
