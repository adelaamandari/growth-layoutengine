import { useEffect, useMemo, useRef, useState } from "react";

// Element fills stay recessive; the colour is spent on the wall
// components, which are the subject of the system and are invisible in
// any numeric output. N renders as a node marker rather than a fourth
// hue -- four hues cannot clear the colour-vision separation floor when
// any pair may appear adjacent, which is the case in a plan drawing.
const COMPONENT_VAR = { SA: "var(--sa)", SB: "var(--sb)", SC: "var(--sc)" };

const fmt = (v, d = 1) =>
  v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export default function PlanView({ plan, layers }) {
  const svgRef = useRef(null);
  const wrapRef = useRef(null);
  const [tip, setTip] = useState(null);
  const [view, setView] = useState(null);
  const drag = useRef(null);

  // World bounds -> initial viewBox. SVG y grows downward, so every
  // y is negated on the way out and north stays up.
  const home = useMemo(() => {
    if (!plan) return null;
    const [minX, minY, maxX, maxY] = plan.extent_cm;
    const pad = Math.max(maxX - minX, maxY - minY) * 0.04;
    return { x: minX - pad, y: -maxY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 };
  }, [plan]);

  useEffect(() => { if (home) setView({ ...home }); }, [home]);

  // Keep labels and node markers a constant size on screen as we zoom.
  const zoom = view && home ? view.w / home.w : 1;

  const shared = useMemo(
    () => (plan?.walls ?? []).filter((w) => w.shared && w.segments.length > 0),
    [plan]
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
        {layers.fills && plan.elements.map((el, i) => (
          <polygon
            key={`f${i}`}
            points={el.corners.map((c) => `${c[0]},${-c[1]}`).join(" ")}
            fill={`var(--fill-${el.kind})`}
            stroke="var(--rule)"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        {layers.rooms && plan.elements.flatMap((el, i) =>
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
        {layers.walls && plan.walls.flatMap((w) =>
          w.segments.filter((s) => s.c !== "N").map((s, j) => (
            <line
              key={`w${w.id}-${j}`}
              x1={s.p[0]} y1={-s.p[1]} x2={s.p[2]} y2={-s.p[3]}
              stroke={COMPONENT_VAR[s.c]} strokeWidth="2.5"
              strokeLinecap="round" vectorEffect="non-scaling-stroke"
            />
          ))
        )}

        {layers.nodes && plan.walls.flatMap((w) =>
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

        {layers.labels && plan.elements.map((el, i) => {
          const cx = el.corners.reduce((s, c) => s + c[0], 0) / 4;
          const cy = el.corners.reduce((s, c) => s + c[1], 0) / 4;
          return (
            <text
              key={`t${i}`} x={cx} y={-cy} textAnchor="middle"
              fontSize={92 * zoom} fontFamily="var(--mono)" fill="var(--ink)"
              paintOrder="stroke" stroke="var(--paper)" strokeWidth={3.5 * zoom}
            >{el.label}</text>
          );
        })}

        {/* hit layer last so it captures the pointer everywhere */}
        {plan.elements.map((el, i) => (
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
          <span className="k">height</span> {fmt(tip.el.height_cm / 100)} m<br />
          <span className="k">walls</span> {tip.el.wall_ids.length}
          {(() => {
            const sh = tip.el.wall_ids.filter((id) => plan.walls[id]?.shared).length;
            return sh > 0 ? ` (${sh} shared)` : "";
          })()}
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
