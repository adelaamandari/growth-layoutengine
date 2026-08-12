# growth-engine

Generative floor plan and massing engine for the LinX timber joinery system.
Grows a building the way it would actually be built — entrance, corridor, core,
branching corridors, then real surveyed residential units attached flush to the
corridor edge — and extrudes the result to 3D.

Rooms are not abstract graph nodes. A room is the physical space enclosed by
built wall components (`N`, `SA`, `SB`, `SC`), walked in the mirrored sequence
`N-SA-SB-SC-SB-SA-N`. Both that sequence and the 360 cm bay it spans are
surveyed, not chosen: the Beam A assembly is 359.99 × 359.99 and its arm runs
SA·SB·SC out to 180, so `70 + 80 + 60 + 80 + 70 = 360` closes on catalog parts
with nothing left over. Unit geometry is real, exported per room from Rhino, for
all ten unit types.

Alongside the units, the program can carry **shared spaces** — lobby, gym,
library, workspace, shared kitchen and shared living — and **outdoor ground** —
garden and playground. These have no survey, so each is a size *range* the
generator picks inside; that range is the only thing the seed varies. Outdoor
areas are ground rather than rooms: they build no walls, take no timber frame,
are not counted as floor area, and draw green.

The envelope is clad from a surveyed set of **nine facade panels** (A–I), each a
fixed 330 × 310 cm module of the same 10×10 and 10×20 timber the frame uses,
plus a tenth — **J**, a 110 cm guard rail for the open decks, which is derived
rather than surveyed and is marked as such. The
engine picks one per exterior bay from what is behind it — circulation, ground or
upper dwelling, shared space — and reports how much wall the set cannot cover
rather than stretching a panel to fit. **Deck-access corridors are left open**:
an outdoor walkway wrapped in solid panels stops being a walkway, so it takes no
cladding, and that length is reported as `open_cm` — a decision — separately
from `unclad_cm`, which is a shortfall. Cores and stairs stay enclosed.

The module is anchored per *elevation* rather than per storey, so panels stack
column-on-column up the building; `/api/facade` returns a `connection_check`
proving it on every response. See `facade.py`.

`solar.py` computes clear-sky irradiation on each panel — real sun geometry over
132 positions across the year, direct beam by incidence angle plus isotropic
diffuse, with a shadow ray tested against the building's own massing. It drives
the Facade view's sun heatmap. Not a certified daylight study: no neighbours, no
weather, no panel-on-panel shading.

## Structure

The building has a real timber frame, not an extrusion. Columns stand on an
independent **360 cm structural grid** — deliberately independent of the rooms,
so the grid is a vertical system rather than a set of room outlines — and run
unbroken from the ground. Primary spans are exact catalog parts; only the last
bay of a wall run adapts, because a wall is rarely a whole number of bays.

Vertical circulation is two different things, because they are two different
problems. A **core** is 7.2 × 3.6 m holding a lift and an emergency stair, and
is capped at two per storey — a firefighting core is expensive and should be
rare. **Stairs** are 3.6 × 3.6 m and distributed, and they are what actually
carries escape distance. Both are decided once and repeated up the building: a
shaft rediscovered per storey is a lift that moves sideways between floors.

`frame.support_report` measures how far each floor plate sits from the nearest
column and says so, rather than assuming the grid reaches everything. Where an
element holds no column — a 170 cm corridor can fall entirely between grid
lines — transfer beams span from its edge to the nearest columns.

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
does this by default (`constrain_to_site`).

How much that constraint actually does depends on the strategy, and it is worth
being straight about it. The `branch` strategy stacks rather than spreads — it
starts a new storey when no run can take the next unit inside `max_branch_cm` —
so on this plot it stays inside the boundary whether or not it is asked to: at
seed 42, the 18-entry program tripled gives 10 levels and 69 elements, 100%
inside, with or without the constraint. The constraint earns its keep on
`spine`, which deliberately spreads across the plot and would otherwise walk off
the acute corners.

The entrance run and the core are laid down *before* any test can run, so
"constrained" is audited rather than assumed: `plan.off_site` lists anything the
constraint could not stop. It is empty on all ten site seeds tested.

The spine strategy on this plot, seed 42, program ×2: **1,169 m² of ground** out
of 2,797 m² developable, 34.3% of it green, a worst walk of 11.2 m to a stair,
2 lift cores and 6 stairs per storey, and nothing off site.

## Three ways to grow

`strategy=` picks how the plan is laid out. All three are kept because they
produce genuinely different buildings and the older one is what a lot of
verified behaviour was measured against.

| strategy | what it does |
|---|---|
| `branch` | the original: entrance, entry run, core, three orthogonal arms, rooms hung off both sides. Axis-aligned. |
| `spine` | the same growth logic turned onto a grid read off the site's own edges, entered from the street. **The one in use.** |
| `site` | perimeter blocks around courtyards, entered from the street. |

`site_grid.py` extracts the candidate grids from the plot's edges rather than
imposing one. On the Deptford triangle, Coffey St bears 87° and Deptford Church
St 176° — 89° apart, so they form a single family — and Crossfield 121.9° gives
a second. Cells are assigned to the family of their nearest edge, so the seam
between them falls out of the geometry instead of being drawn by hand.

Whatever the building does not take becomes **green**. That is what makes the
diagonal cheap: outdoor areas build no walls, carry no frame and are not floor
area, so a trapezoid costs nothing and no non-90° joint is needed anywhere.
`generate_spine_floorplan` closes a loop on the 30–40% green target — grow,
measure, adjust the reserved courtyard area, keep the best of four — and when
that lever is spent it perturbs the layout instead of pulling harder on a lever
that cannot move.

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
    walls.py          resolves each physical wall once, per occupied storey
    growth.py         generate_floorplan() — the branch strategy
    growth_site.py    the spine and site strategies, and the green loop
    site_grid.py      reads candidate grids off the site's own edges
    frame.py          the timber frame: columns, spans, decks, support report
    massing.py        extrusion, element-level and real per-room
    preview.py        SVG renderer
    export.py         OBJ export (metres)
    diagnostics.py    measurements about a plan, incl. shared-wall detection
    site/             the real site, OSM lookup, daylight/circulation grid
      location.py     Deptford Church St — boundary, latitude, placement
    unit_exports/     real per-room JSON for all 10 unit types
    facade_exports/   the extracted A..I panel geometry
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
| `POST` | `/api/frame` | timber members, columns, and the support report |
| `GET` | `/api/site` | the real plot, in cm relative to the entrance |
| `GET` | `/api/site/grid` | the grid families read off the site's edges |
| `GET` | `/api/facade/catalog` | the panel types (A–I surveyed, J derived) with their member geometry |
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

## What is measured, not asserted

Several of the things this engine aims at are targets rather than invariants,
so it **reports** them on every response instead of quietly failing or quietly
pretending. That distinction is the point, and it is worth knowing which is
which before reading a number.

**Invariants** — these must hold, and a failure is a bug:

- `wall_check` (`/api/plan`) — each physical wall built exactly once.
  `resolved + dropped == naive - shared`, to within one sliver.
- `plan.off_site` — nothing placed outside the plot. Empty.
- `connection_check` (`/api/facade`) — panels meet their neighbours, no gaps.

**Targets** — reported so a seed that misses is visible:

- `access_report` — the walk to the nearest core or stair (brief: 20 m), and
  green as a share of the ground floor (brief: 30–40%).
- `support_report` (`/api/frame`) — how far a floor plate sits from the nearest
  column, since a 170 cm corridor can fall between grid lines.
- `unclad_cm` / `open_cm` — wall the panel set cannot cover, kept apart from
  wall left open on purpose.

On the default 18-entry program **at seed 42**, the branch strategy resolves
715.6 m of drawn wall down to **572.2 m across 112 walls, 33 of them shared —
1,716.5 m²**. The seed belongs in that figure: shared spaces draw their size
from a range, so an unseeded plan totals differently every run, and figures in
this repo were once quoted unseeded and could never be reproduced. What holds on
any run is `delta_m == 0.00`.

## Status

Working, and honest about what is not. Placement, real unit geometry, shared and
outdoor spaces, the timber frame, the facade, the site constraint, massing and
export all work, on all three strategies.

Shared-space and outdoor sizes are a brief rather than a survey — ranges in
`shared_spaces.py`, sized against the real unit catalog. Outdoor entries are
laid out in a separate ground-floor pass, so their position among the rooms in
the program order is not honoured; only their order relative to each other is.

Known gaps, each with the reason it is still open:

- **Green misses its band on most seeds** (20–52% against 30–40). Circulation
  displaces the units that spread the footprint, and the courtyard lever cannot
  reach *residual* ground — reserving less does not make the building bigger.
- **The guard panel is derived, not surveyed.** Nine of the ten panels came out
  of Adela's GLBs; **J**, the 110 cm balustrade on the open decks, was generated
  by `facade_import.derived_guard_panel` and says so in its own `source` field.
  Its 1100 mm height and 65 mm gaps were aimed at Approved Document K but are
  not certified. Replace it the moment a real component exists — it is added at
  load time, so that is a one-function change.
- **A fifth of the skin is remainder.** 20.8% of exterior wall is what is left
  at the ends of clad runs, because the panel is a fixed 330 and runs are not
  multiples of it — 85 exterior lines on the test plan, 29 exactly one bay long.
  A further 3.3% sits on walls narrower than a single panel. Neither closes
  without a filler piece or a narrower type.
- **No fabrication-length step.** OBJ export writes full-precision metres, which
  is not a real-world cut length.
- **The adjacency matrix is one rule.** `SL-SK = 2.0` and nothing else.

See [PROJECT_SUMMARY.md](PROJECT_SUMMARY.md) for the full list and the reasoning
behind each.
