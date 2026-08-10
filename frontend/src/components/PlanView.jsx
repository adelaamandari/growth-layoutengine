import { useEffect, useMemo, useRef, useState } from "react";

// Element fills stay recessive; the colour is spent on the wall
// components, which are the subject of the system and are invisible in
// any numeric output. N renders as a node marker rather than a fourth
// hue -- four hues cannot clear the colour-vision separation floor when
// any pair may appear adjacent, which is the case in a plan drawing.
const COMPONENT_VAR = { SA: "var(--sa)", SB: "var(--sb)", SC: "var(--sc)" };

const fmt = (v, d = 1) =>
  v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

// How many storeys an element occupies. A duplex is 600cm and so shows
// on two plans: solid on the level it is entered from, ghosted on the
// one above, the way a maisonette's upper part is drawn.
const floorsOf = (el) => Math.max(1, Math.round((el.height_cm ?? 300) / 300));

// One hue per grid family, matching the colours in Adela's grid
// extraction sketch: the orthogonal street grid warm, the diagonal
// Crossfield grid violet, so the two systems are told apart at a glance.
const FAMILY_STROKE = ["#eb6834", "#8a6fd6", "#2a78d6"];

export default function PlanView({ plan, layers, level = 0, site = null, grid = null }) {
  const svgRef = useRef(null);
  const wrapRef = useRef(null);
  const [tip, setTip] = useState(null);
  const [view, setView] = useState(null);
  const drag = useRef(null);

  // The plan now stacks, so one storey is drawn at a time. `above` is
  // the upper half of duplexes reaching into this level; `below` is the
  // storey underneath, kept faint for judging how the stack lines up.
  const here = useMemo(
    () => (plan?.elements ?? []).filter((el) => (el.level ?? 0) === level),
    [plan, level]
  );
  const above = useMemo(
    () => (plan?.elements ?? []).filter((el) => {
      const l = el.level ?? 0;
      return l < level && level < l + floorsOf(el);
    }),
    [plan, level]
  );
  const below = useMemo(
    () => (plan?.elements ?? []).filter((el) => (el.level ?? 0) === level - 1),
    [plan, level]
  );
  const wallsHere = useMemo(
    () => (plan?.walls ?? []).filter((w) => (w.level ?? 0) === level),
    [plan, level]
  );

  // World bounds -> initial viewBox. SVG y grows downward, so every
  // y is negated on the way out and north stays up.
  const home = useMemo(() => {
    if (!plan) return null;
    let [minX, minY, maxX, maxY] = plan.extent_cm;
    // Frame the SITE too when it is shown, or the building fills the
    // view and the plot it stands on is off screen — which is the one
    // thing drawing the boundary is meant to answer.
    if (site && layers.site) {
      for (const [x, y] of site.centreline_cm) {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x);
        minY = Math.min(minY, y); maxY = Math.max(maxY, y);
      }
    }
    const pad = Math.max(maxX - minX, maxY - minY) * 0.04;
    return { x: minX - pad, y: -maxY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
  }, [plan, site, layers.site]);

  useEffect(() => { if (home) setView({ ...home }); }, [home]);

  // Keep labels and node markers a constant size on screen as we zoom.
  const zoom = view && home ? view.w / home.w : 1;

  const shared = useMemo(
    () => wallsHere.filter((w) => w.shared && w.segments.length > 0),
    [wallsHere]
  );

  function onWheel(e) {
    if (!view || !home) return;
    e.preventDefault();
    const box = svgRef.current.getBoundingClientRect();
    const px = (e.clientX - box.left) / box.width;
    const py = (e.clientY - box.top) / box.height;
    const f = e.deltaY > 0 ? 1.12 : 1 / 1.12;
    const w = Math.min(home.w * 3, Math.max(home.w * 0.04, view.w * f));
    const h = w * (view.h / view.w);
    setView({ x: view.x + (view.w - w) * px, y: view.y + (view.h - h) * py, w, h });
  }

  function onPointerDown(e) {
    if (!view) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y };
    svgRef.current.setPointerCapture(e.pointerId);
    svgRef.current.classList.add("dragging");
  }
  function onPointerMove(e) {
    if (!drag.current || !view) return;
    const s = view.w / svgRef.current.clientWidth;
    setView({ ...view, x: drag.current.vx - (e.clientX - drag.current.x) * s,
                       y: drag.current.vy - (e.clientY - drag.current.y) * s });
  }
  function onPointerUp(e) {
    drag.current = null;
    svgRef.current?.classList.remove("dragging");
    try { svgRef.current?.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
  }

  function showTip(e, el) {
    const xs = el.corners.map((c) => c[0]);
    const ys = el.corners.map((c) => c[1]);
    const w = Math.max(...xs) - Math.min(...xs);
    const d = Math.max(...ys) - Math.min(...ys);
    const box = wrapRef.current.getBoundingClientRect();
    setTip({
      el, w, d,
      x: Math.min(e.clientX - box.left + 14, box.width - 250),
      y: Math.min(e.clientY - box.top + 14, box.height - 130),
    });
  }

  if (!plan || !view) return <div className="viewport" style={{ height: 400 }} />;

  return (
    <div className="viewport" ref={wrapRef}>
      <svg
        ref={svgRef}
        viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`}
        role="img"
        aria-label="Generated floor plan"
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {/* The site, under everything. Two outlines: the street
            centrelines OSM actually gives, and the developable boundary
            after the setback — the building has to sit inside the
            second, not the first. */}
        {layers.site && site && (
          <g>
            <polygon
              points={site.centreline_cm.map((p) => `${p[0]},${-p[1]}`).join(" ")}
              fill="var(--fill-outdoor)" fillOpacity="0.18"
              stroke="var(--outdoor-line)" strokeWidth="1"
              strokeOpacity="0.5" strokeDasharray="8 6"
              vectorEffect="non-scaling-stroke"
            >
              <title>{site.address} — {site.area_m2} m² to street centrelines</title>
            </polygon>
            <polygon
              points={site.boundary_cm.map((p) => `${p[0]},${-p[1]}`).join(" ")}
              fill="none" stroke="var(--outdoor-line)" strokeWidth="2"
              vectorEffect="non-scaling-stroke"
            >
              <title>Developable boundary at {site.inset_m} m setback — {site.developable_area_m2} m²</title>
            </polygon>
          </g>
        )}

        {/* The grid the SITE gives, not the one the engine brings: one
            lattice per family, clipped to the plot, plus the cells on
            the seam where one family hands over to the other. Drawn
            above the site fill and below everything built. */}
        {layers.grid && grid && (
          <g>
            {grid.families.map((f, fi) => (
              <g key={`gf${fi}`} stroke={FAMILY_STROKE[fi % FAMILY_STROKE.length]}
                 strokeOpacity="0.5">
                {f.lines_cm.map((l, i) => (
                  // vectorEffect is a per-shape presentation attribute and
                  // does NOT inherit from the group. On the group it is
                  // silently ignored, leaving strokeWidth at 1 USER unit —
                  // one centimetre — which draws an invisible hairline.
                  <line key={i} x1={l[0]} y1={-l[1]} x2={l[2]} y2={-l[3]}
                        strokeWidth="1" vectorEffect="non-scaling-stroke" />
                ))}
              </g>
            ))}
            {/* The seam is the whole point of running two grids, and it
                is where the awkward junction will have to be detailed —
                so it is marked rather than left to be inferred. */}
            {grid.cells.filter((c) => c.seam).map((c, i) => (
              <circle key={`sm${i}`} cx={c.c[0]} cy={-c.c[1]}
                      r={grid.resolution_cm * 0.16}
                      fill="var(--warn)" fillOpacity="0.5" />
            ))}
          </g>
        )}

        {/* The storey below, faint -- drawn first so everything on this
            level reads over it. */}
        {layers.below && below.map((el, i) => (
          <polygon
            key={`b${i}`}
            points={el.corners.map((c) => `${c[0]},${-c[1]}`).join(" ")}
            fill="none" stroke="var(--rule)" strokeWidth="1"
            strokeOpacity="0.35" strokeDasharray="2 6"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {/* An outdoor area builds no walls, so no SA/SB/SC strokes land
            on its boundary. Its own outline is therefore the only edge
            it gets, and it has to carry the weight those strokes carry
            on a room — hence the heavier, green stroke. */}
        {layers.fills && here.map((el, i) => (
          <polygon
            key={`f${i}`}
            points={el.corners.map((c) => `${c[0]},${-c[1]}`).join(" ")}
            fill={`var(--fill-${el.kind})`}
            stroke={el.kind === "outdoor" ? "var(--outdoor-line)" : "var(--rule)"}
            strokeWidth={el.kind === "outdoor" ? 2 : 1}
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {/* Upper half of a duplex entered from the level below. */}
        {layers.fills && above.map((el, i) => (
          <polygon
            key={`a${i}`}
            points={el.corners.map((c) => `${c[0]},${-c[1]}`).join(" ")}
            fill={`var(--fill-${el.kind})`} fillOpacity="0.4"
            stroke="var(--rule)" strokeWidth="1" strokeDasharray="6 4"
            vectorEffect="non-scaling-stroke"
          >
            <title>{el.label} — upper floor, entered from level {el.level}</title>
          </polygon>
        ))}

        {layers.rooms && here.flatMap((el, i) =>
          el.rooms.map((r, j) => (
            <polygon
              key={`r${i}-${j}`}
              points={r.poly.map((p) => `${p[0]},${-p[1]}`).join(" ")}
              fill="none"
              stroke="var(--rule)"
              strokeWidth="1"
              strokeDasharray="4 4"
              vectorEffect="non-scaling-stroke"
            />
          ))
        )}

        {/* Shared walls are now a resolved fact rather than a defect:
            these are the walls carrying two owners, built once. */}
        {layers.shared && shared.map((w) => (
          <line
            key={`s${w.id}`}
            x1={w.segments[0].p[0]} y1={-w.segments[0].p[1]}
            x2={w.segments[w.segments.length - 1].p[2]}
            y2={-w.segments[w.segments.length - 1].p[3]}
            stroke="var(--shared)" strokeWidth="7" strokeOpacity="0.5"
            strokeLinecap="round" vectorEffect="non-scaling-stroke"
          >
            <title>{w.owner_labels.join(" ↔ ")} · {(w.length_cm / 100).toFixed(2)} m, built once</title>
          </line>
        ))}

        {/* Walls come from plan.walls, not per element -- a shared wall
            is stroked once here because it exists once. */}
        {layers.walls && wallsHere.flatMap((w) =>
          w.segments.filter((s) => s.c !== "N").map((s, j) => (
            <line
              key={`w${w.id}-${j}`}
              x1={s.p[0]} y1={-s.p[1]} x2={s.p[2]} y2={-s.p[3]}
              stroke={COMPONENT_VAR[s.c]} strokeWidth="2.5"
              strokeLinecap="round" vectorEffect="non-scaling-stroke"
            />
          ))
        )}

        {layers.nodes && wallsHere.flatMap((w) =>
          w.segments.filter((s) => s.c === "N").map((s, j) => (
            <circle
              key={`n${w.id}-${j}`}
              cx={(s.p[0] + s.p[2]) / 2} cy={-(s.p[1] + s.p[3]) / 2}
              r={26 * zoom}
              fill="var(--node-fill)" stroke="var(--node-line)"
              strokeWidth="1.4" vectorEffect="non-scaling-stroke"
            />
          ))
        )}

        {layers.labels && here.map((el, i) => {
          const cx = el.corners.reduce((s, c) => s + c[0], 0) / 4;
          const cy = el.corners.reduce((s, c) => s + c[1], 0) / 4;
          return (
            <text
              key={`t${i}`} x={cx} y={-cy} textAnchor="middle"
              fontSize={92 * zoom} fontFamily="var(--sans)" fill="var(--ink)"
              paintOrder="stroke" stroke="var(--paper)" strokeWidth={3.5 * zoom}
            >{el.label}</text>
          );
        })}

        {/* hit layer last so it captures the pointer everywhere */}
        {here.map((el, i) => (
          <polygon
            key={`h${i}`}
            points={el.corners.map((c) => `${c[0]},${-c[1]}`).join(" ")}
            fill="transparent"
            onMouseMove={(e) => showTip(e, el)}
            onMouseLeave={() => setTip(null)}
          />
        ))}
      </svg>

      {tip && (
        <div className="tip" style={{ left: tip.x, top: tip.y, opacity: 1 }}>
          <strong>{tip.el.label}</strong>
          <span className="k">kind</span> {tip.el.kind}<br />
          <span className="k">size</span> {fmt(tip.w / 100)} × {fmt(tip.d / 100)} m<br />
          <span className="k">area</span> {fmt((tip.w * tip.d) / 10000)} m²<br />
          {/* Height, storeys and a wall count are all statements about a
              ROOM. On open ground they would read as zeros standing for
              missing data rather than for the thing being ground. */}
          {tip.el.kind === "outdoor" ? (
            <>open ground — no walls, not floor area</>
          ) : (
            <>
              <span className="k">height</span> {fmt(tip.el.height_cm / 100)} m
              {floorsOf(tip.el) > 1 ? ` (${floorsOf(tip.el)} storeys)` : ""}<br />
              <span className="k">level</span> {tip.el.level ?? 0}<br />
              <span className="k">walls</span> {tip.el.wall_ids.length}
              {(() => {
                const sh = tip.el.wall_ids.filter((id) => plan.walls[id]?.shared).length;
                return sh > 0 ? ` (${sh} shared)` : "";
              })()}
            </>
          )}
          {tip.el.rooms.length > 0 && (
            <><br /><span className="k">rooms</span> {tip.el.rooms.map((r) => r.name).join(", ")}</>
          )}
        </div>
      )}

      <div className="hint">
        <span>Drag to pan · scroll to zoom · hover an element for detail</span>
        <button className="icon-btn" onClick={() => setView({ ...home })}>reset view</button>
      </div>
    </div>
  );
}
