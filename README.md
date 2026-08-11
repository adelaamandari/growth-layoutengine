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

Alongside the units, the program can carry **shared spaces** — lobby, gym,
library, workspace, shared kitchen and shared living — and **outdoor ground** —
garden and playground. These have no survey, so each is a size *range* the
generator picks inside; that range is the only thing the seed varies. Outdoor
areas are ground rather than rooms: they build no walls, take no timber frame,
are not counted as floor area, and draw green.

The envelope is clad from a surveyed set of **nine facade panels** (A–I), each a
fixed 330 × 310 cm module of the same 10×10 and 10×20 timber the frame uses. The
engine picks one per exterior bay from what is behind it — circulation, ground or
upper dwelling, shared space — and reports how much wall the set cannot cover
rather than stretching a panel to fit. The module is anchored per *elevation*
rather than per storey, so panels stack column-on-column up the building;
`/api/facade` returns a `connection_check` proving it on every response. See
`facade.py`.

`solar.py` computes clear-sky irradiation on each panel — real sun geometry over
132 positions across the year, direct beam by incidence angle plus isotropic
diffuse, with a shadow ray tested against the building's own massing. It drives
the Facade view's sun heatmap. Not a certified daylight study: no neighbours, no
weather, no panel-on-panel shading.

## Site

The project has a real one: the triangle bounded by **Coffey Street, Deptford
Church Street and Crossfield Street, London SE8** — 51.479058, −0.023964. Its
three corners are the actual OSM intersection nodes of those streets (each pair
shares a node, so the corners are exact), giving **4,588 m²** to the street
centrelines and **2,797 m²** after a 6 m setback. `site/location.py` holds it,
`--fetch` re-derives it, and `/api/site` serves the boundary in centimetres
relative to the entrance so it draws straight over the plan.

Two things follow. The sun study now runs at the real latitude instead of a
placeholder. And the plot is within 4° of cardinal (Coffey St bears 87°, Deptford
Church St 176°), so the engine's own axes are already street-aligned — the
placement search returns rotation 0.

**Growth is constrained to it.** `generate_floorplan(..., boundary=…)` places
nothing that does not lie wholly inside the polygon, at any level, and the API
does this by default (`constrain_to_site`). On the default program the effect is
the one you want: the building stops spreading and starts stacking, because that
is the only direction left.

| | levels | elements | on site | footprint area on site |
|---|---|---|---|---|
| unconstrained | 6 | 36 | 35 | 95.9% |
| constrained | 5 | 33 | **33** | **100%** |

The entrance run and the core are laid down *before* any test can run, so
"constrained" is audited rather than assumed: `plan.off_site` lists anything the
constraint could not stop, and it is empty here.

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
    program=["Lobby", "Studio_A", "1Bed_B", "SK", "2Bed_A",
             "Gym", "3Bed_A", "Garden", "Playground"],
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
    shared_spaces.py  the flexible program: shared rooms + outdoor ground
    facade.py         picks a facade panel for every exterior bay
    facade_import.py  reads the A..I panel GLBs into facade_exports/
    solar.py          clear-sky irradiation per panel, with self-shading
    growth.py         generate_floorplan() — the growth logic
    massing.py        extrusion, element-level and real per-room
    preview.py        SVG renderer
    export.py         OBJ export (metres)
    diagnostics.py    measurements about a plan, incl. shared-wall detection
    site/             the real site, OSM lookup, daylight/circulation grid
      location.py     Deptford Church St — boundary, latitude, placement
    unit_exports/     real per-room JSON for all 10 unit types
  app/                FastAPI adapter over the engine
frontend/             React + Vite viewer
```

## API

| Method | Path | Returns |
|---|---|---|
| `GET` | `/api/health` | liveness + catalog size |
| `GET` | `/api/catalog` | unit types with per-room breakdown, plus shared/outdoor spaces with their size ranges |
| `POST` | `/api/plan` | elements, wall components, rooms, stats, shared boundaries |
| `POST` | `/api/massing` | extruded blocks (`per_room` toggles room vs element) |
| `GET` | `/api/facade/catalog` | the nine panel types (A–I) with their member geometry |
| `POST` | `/api/facade` | which panel clads which exterior bay, and why |
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

Proof of concept, and honest about it. Placement, real unit geometry, shared
and outdoor spaces, massing, and export work. Shared walls resolve properly —
each physical wall is built once and referenced by both elements on it, which
on the default 18-entry program takes 807.9 m of drawn wall down to 600.9 m
across 112 walls, 38 of them shared. Turn on the *shared walls* layer in the
plan view to see them, and note that `/api/plan` returns a `wall_check`
verifying the deduplication on every response.

Shared-space and outdoor sizes are a brief rather than a survey — ranges in
`shared_spaces.py`, sized against the real unit catalog. Outdoor entries are
also laid out in a separate ground-floor pass, so their position among the
rooms in the program order is not honoured; only their order relative to each
other is.

Not yet wired in: the adjacency matrix beyond a single rule, and a site boundary
constraint on growth (`site/` already computes the daylight/circulation field
such a constraint would need — only the wiring into `growth.py` is missing).
There is also no fabrication-length step yet: OBJ export writes full-precision
metres, which is not the same as a real-world cut length. See
[PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for the full list and the reasoning
behind each.
