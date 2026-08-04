"""
glb_import.py
Read Adela's components.glb into the component catalog, standard
library only -- no trimesh, no pygltflib, no numpy.

WHY THIS IS PARSEABLE WITHOUT A GLTF LIBRARY
GLB is a 12-byte header followed by chunks: a JSON chunk holding the
glTF document and a BIN chunk holding vertex data. The spec REQUIRES
every POSITION accessor to carry min/max, so per-part bounding boxes
come straight out of the JSON -- the BIN chunk never has to be decoded.
That is the same shape as the Rhino unit_exports: named part -> box.

WHAT THE SOURCE FILE CONTAINS
Four top-level assemblies, all authored on a 100mm grid with NO node
transforms (geometry is baked in world space, so a bounding box is
already a world box):

  Joints    240x240x100  the woven capital: Con/N connector plate,
                         F1/F2 lacing layers, B2 short verticals
  Beam A    360x360      four orthogonal arms of SA/SB/SC
  Column A   40x 40x300  four 10x10 posts on 30cm centres
  Default                a zero-size marker, skipped like the
                         degenerate groups catalog.py filters

Run it to regenerate the bundled catalog:

    python -m growth_engine.glb_import path/to/components.glb

Output goes to component_exports/components.json, which frame.py loads.
The 13MB GLB itself is deliberately NOT committed -- the extracted
JSON is a few tens of KB and is what the engine actually reads.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

MAGIC = 0x46546C67          # 'glTF'
CHUNK_JSON = 0x4E4F534A     # 'JSON'

M_TO_CM = 100.0
# Anything thinner than this in every axis is a marker, not a member --
# same guard catalog.py applies to the Rhino exports.
MIN_SIZE_CM = 0.5

_EXPORTS_DIR = Path(__file__).parent / "component_exports"
CATALOG_PATH = _EXPORTS_DIR / "components.json"

# Which top-level node becomes which assembly.
_ROOTS = {"Joints": "joint", "Beam...": "beam", "column...": "column"}


def _read_gltf_json(path: Path) -> dict:
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from("<III", raw, 0)
    if magic != MAGIC:
        raise ValueError(f"{path.name} is not a GLB file")
    if version != 2:
        raise ValueError(f"unsupported glTF version {version}")
    pos = 12
    while pos < length:
        clen, ctype = struct.unpack_from("<II", raw, pos)
        if ctype == CHUNK_JSON:
            return json.loads(raw[pos + 8: pos + 8 + clen].decode("utf-8"))
        pos += 8 + clen
    raise ValueError("no JSON chunk found")


def _mesh_box(doc: dict, mesh_index: int):
    """Bounding box of one mesh, from accessor min/max only."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for prim in doc["meshes"][mesh_index].get("primitives", []):
        ai = prim.get("attributes", {}).get("POSITION")
        if ai is None:
            continue
        acc = doc["accessors"][ai]
        for k in range(3):
            lo[k] = min(lo[k], acc["min"][k])
            hi[k] = max(hi[k], acc["max"][k])
    if lo[0] == float("inf"):
        return None
    return lo, hi


def _to_engine_cm(lo, hi) -> dict:
    """glTF is Y-up, right-handed, metres. The engine is Z-up and
    centimetres, so engine x = gltf x, engine y = -gltf z (the near
    bound maps to y_max -- getting this backwards mirrors the model),
    engine z = gltf y."""
    return {
        "x0": lo[0] * M_TO_CM, "x1": hi[0] * M_TO_CM,
        "y0": -hi[2] * M_TO_CM, "y1": -lo[2] * M_TO_CM,
        "z0": lo[1] * M_TO_CM, "z1": hi[1] * M_TO_CM,
    }


def _leaves(doc: dict, root: int, inherited: str):
    """Every mesh-bearing descendant, carrying down the nearest named
    ancestor -- Column A's and Sub-Beam A's members are unnamed in the
    source, so without this they would all read as '<unnamed>'."""
    node = doc["nodes"][root]
    name = node.get("name") or inherited
    out = []
    if "mesh" in node:
        box = _mesh_box(doc, node["mesh"])
        if box is not None:
            out.append((name, _to_engine_cm(*box)))
    for child in node.get("children", []):
        out.extend(_leaves(doc, child, name))
    return out


def extract(glb_path: str | Path) -> dict:
    """Parse a components GLB into the catalog dict frame.py consumes."""
    doc = _read_gltf_json(Path(glb_path))
    named = {n.get("name"): i for i, n in enumerate(doc["nodes"])}

    assemblies: dict[str, dict] = {}
    for root_name, key in _ROOTS.items():
        if root_name not in named:
            continue
        parts = [
            (nm, b) for nm, b in _leaves(doc, named[root_name], root_name)
            if (b["x1"] - b["x0"]) > MIN_SIZE_CM
            and (b["y1"] - b["y0"]) > MIN_SIZE_CM
            and (b["z1"] - b["z0"]) > MIN_SIZE_CM
        ]
        if not parts:
            continue
        xs = [b["x0"] for _, b in parts] + [b["x1"] for _, b in parts]
        ys = [b["y0"] for _, b in parts] + [b["y1"] for _, b in parts]
        zs = [b["z0"] for _, b in parts] + [b["z1"] for _, b in parts]
        # Local origin: centred in plan. Z is left absolute here and
        # rebased by frame.py, which knows the storey height.
        ox, oy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        assemblies[key] = {
            "footprint_cm": [round(max(xs) - min(xs), 2), round(max(ys) - min(ys), 2)],
            "z0": round(min(zs), 2), "z1": round(max(zs), 2),
            "members": [
                {
                    "name": nm,
                    "c": [round((b["x0"] + b["x1"]) / 2 - ox, 2),
                          round((b["y0"] + b["y1"]) / 2 - oy, 2),
                          round((b["z0"] + b["z1"]) / 2, 2)],
                    "s": [round(b["x1"] - b["x0"], 2),
                          round(b["y1"] - b["y0"], 2),
                          round(b["z1"] - b["z0"], 2)],
                }
                for nm, b in parts
            ],
        }

    # The wall components, measured off the Beam A arms. These are FIXED
    # real lengths on a 100mm grid -- not the rescalable ratios in
    # components.py. See PROJECT_SUMMARY for that open question.
    catalog: dict[str, dict] = {}
    for nm, b in _leaves(doc, named["Beam..."], "beam") if "Beam..." in named else []:
        if nm not in ("SA", "SB", "SC"):
            continue
        w, d, t = b["x1"] - b["x0"], b["y1"] - b["y0"], b["z1"] - b["z0"]
        catalog.setdefault(nm, {
            "length_cm": round(max(w, d), 1),
            "width_cm": round(min(w, d), 1),
            "thickness_cm": round(t, 1),
        })
    if "joint" in assemblies:
        plate = next((m for m in assemblies["joint"]["members"] if m["name"] == "N"), None)
        if plate:
            catalog["N"] = {
                "length_cm": plate["s"][0], "width_cm": plate["s"][1],
                "thickness_cm": plate["s"][2],
            }

    return {
        "source": Path(glb_path).name,
        "units": "cm",
        "grid_cm": 10,
        "catalog": catalog,
        "assemblies": assemblies,
    }


def load_catalog(path: str | Path = CATALOG_PATH) -> dict | None:
    """Load the bundled extraction, or None if it has not been generated."""
    path = Path(path)
    if not path.exists():
        return None
    return json.loads(path.read_text())


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Extract components.glb into the component catalog.")
    ap.add_argument("glb", help="path to components.glb")
    ap.add_argument("--out", default=str(CATALOG_PATH))
    args = ap.parse_args(argv)

    data = extract(args.glb)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2))

    print(f"wrote {out}")
    for key, asm in data["assemblies"].items():
        print(f"  {key:8s} {asm['footprint_cm'][0]:6.1f} x {asm['footprint_cm'][1]:6.1f} cm, "
              f"z {asm['z0']:.1f}..{asm['z1']:.1f}, {len(asm['members'])} members")
    print("  catalog:")
    for name, c in sorted(data["catalog"].items()):
        print(f"    {name}: {c['length_cm']} x {c['width_cm']} x {c['thickness_cm']} cm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
