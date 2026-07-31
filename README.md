# growth-engine

On development for generating massing system.

Generative floor plan and massing engine for the LinX timber joinery system.
Grows a building the way it would actually be built — entrance, corridor, core,
branching corridors, then real surveyed residential units attached flush to the
corridor edge — and extrudes the result to 3D.

Rooms are not abstract graph nodes. A room is the physical space enclosed by
built wall components (`N`, `SA`, `SB`, `SC`), walked in the mirrored sequence
`N-SA-SB-SB-SC-SB-SB-SA-N`. Unit geometry is real, exported per room from Rhino,
for all ten unit types.

**[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) is the authoritative design
document** — the geometric reasoning, the decisions already settled, and an
honest list of what isn't solved yet. Read it before changing the engine.

## Quickstart

Two processes. The API on 8000, the UI on 5173.

```bash
# 1. backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 2. frontend, in a second terminal
cd frontend
npm install
npm run dev          # http://localhost:5173
```

The frontend proxies `/api` to port 8000, so the browser only ever talks to one
origin and there is no CORS step in development.

## Using the engine on its own

The engine is a plain Python package with **no dependency beyond the standard
library** — no Rhino, no Grasshopper, no numpy, not even the web stack. That is
deliberate: it stays testable in a REPL and portable to a GHPython adapter
later. The API is a thin layer on top, not part of it.

```python
from growth_engine import generate_floorplan, generate_room_massing, plan_to_obj

plan = generate_floorplan(
    program=["Studio_A", "1Bed_B", "SK", "2Bed_A", "SL", "3Bed_A"],
    seed=42,
)
blocks = generate_room_massing(plan)   # real rooms where available
open("massing.obj", "w").write(plan_to_obj(plan))
```

Render a plan to SVG without the server at all:

```bash
cd backend
python -m growth_engine.preview --seed 42 --out plan.svg
```

## Layout

```
backend/
  growth_engine/      the engine — pure stdlib, no web dependency
    geometry.py       vectors, SAT overlap with the flush-touch epsilon
    components.py     the N-SA-SB-SB-SC-SB-SB-SA-N sequence, per-wall rescaling
    catalog.py        UnitType / RoomComponent, loads the Rhino exports
    growth.py         generate_floorplan() — the growth logic
    massing.py        extrusion, element-level and real per-room
    preview.py        SVG renderer
    export.py         OBJ export (metres)
    diagnostics.py    measurements about a plan, incl. shared-wall detection
    site/             OSM infill-site finding, daylight/circulation grid
    unit_exports/     real per-room JSON for all 10 unit types
  app/                FastAPI adapter over the engine
frontend/             React + Vite viewer
```

## API

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/health` | liveness + catalog size |
| `GET` | `/api/catalog` | all unit types, dimensions, per-room breakdown |
| `POST` | `/api/plan` | elements, wall components, rooms, stats, shared boundaries |
| `POST` | `/api/massing` | extruded blocks (`per_room` toggles room vs element) |
| `POST` | `/api/export/{obj,svg,json}` | file download |

All geometry crosses the wire in **centimetres**, matching the engine. OBJ is
the one exception — it converts to metres on the way out, since that is what
Blender and Rhino expect.

## Units

Everything internal is centimetres. This is worth stating loudly because it has
already gone wrong once: the circulation constants were transcribed off the
drawings in millimetres and stored in `_CM` fields, which made the corridor 17 m
wide and the core a 17×17 m room. Anything sourced from Rhino was always correct.
If you add a hand-typed dimension, it is in **cm**.

## Status

Proof of concept, and honest about it. Placement, real unit geometry, massing,
and export work. Not yet wired in: the adjacency matrix beyond a single rule, a
site boundary constraint on growth, and shared-wall deduplication — the engine
currently builds each shared boundary twice, once from each side, which the plan
view will show you if you turn on the *shared walls* layer. See
[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for the full list and the reasoning
behind each.
