import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { CM_TO_M, buildFrameInstances } from "./frameInstances";
import { KIND_COLOR, KIND_FALLBACK, applySceneTheme, sceneTheme } from "../theme";

// Heatmap ramp for sun received: cool blue (least) through to a warm
// yellow (most). Sequential and monotonic in lightness, so it still
// reads as an ordering in greyscale and to a colour-blind viewer -- the
// usual rainbow ramp does neither.
const HEAT = [
  [0.00, [0x1b, 0x3a, 0x6b]],
  [0.25, [0x2a, 0x76, 0x9c]],
  [0.50, [0x54, 0xa8, 0x8e]],
  [0.75, [0xc2, 0xb2, 0x50]],
  [1.00, [0xf5, 0xe0, 0x8a]],
];

export function heatColor(t) {
  const v = t < 0 ? 0 : t > 1 ? 1 : t;
  let i = 0;
  while (i < HEAT.length - 2 && v > HEAT[i + 1][0]) i += 1;
  const [t0, c0] = HEAT[i];
  const [t1, c1] = HEAT[i + 1];
  const f = t1 === t0 ? 0 : (v - t0) / (t1 - t0);
  const ch = (k) => Math.round(c0[k] + (c1[k] - c0[k]) * f);
  return (ch(0) << 16) | (ch(1) << 8) | ch(2);
}

// One hue per panel type, ordered blank -> most open, so the elevation
// reads as a gradient of openness rather than as nine arbitrary colours.
// Warm ochres for the solid end (the timber it is made of), cooling and
// lightening as the panel opens up, with the balcony given the one
// saturated tone because it is the only type that projects.
export const PANEL_COLOR = {
  A: 0x6f5433,  // solid, upper
  B: 0x8f6f45,  // solid, ground
  C: 0xb3a288,  // simple, no shading
  D: 0xc9a97a,  // one big window
  E: 0xd9c49c,  // two windows
  H: 0xa9b7bd,  // one full window   (shared)
  G: 0xc0ccd1,  // two full windows  (shared)
  F: 0xdae3e7,  // three full windows(shared)
  I: 0xc4703f,  // balcony — the one that sticks out
};

const ORDER = ["A", "B", "C", "D", "E", "H", "G", "F", "I"];

/**
 * Expand panel instances into one InstancedMesh.
 *
 * A panel is ~150 members and a building carries ~90 panels, so this is
 * on the order of 14,000 boxes. Instanced, that is one draw call; a Mesh
 * each would be 14,000.
 *
 * The panel catalog gives each member in PANEL-LOCAL cm: +x along the
 * wall, y across it with 0 on the wall centre line and -y outward, z up
 * from the panel's own slab. Each instance rotates that by the panel's
 * angle about the vertical and drops it at the panel's position.
 */
function buildPanelInstances(catalog, panels, box, only, heat) {
  const byKey = Object.fromEntries(catalog.panels.map((p) => [p.key, p]));
  const shown = panels.filter((p) => !only || only === p.panel);
  let total = 0;
  for (const p of shown) total += byKey[p.panel]?.members.length ?? 0;

  const mesh = new THREE.InstancedMesh(
    new THREE.BoxGeometry(1, 1, 1),
    new THREE.MeshLambertMaterial(),
    total
  );

  const dummy = new THREE.Object3D();
  const colour = new THREE.Color();
  let i = 0;

  for (const p of shown) {
    const type = byKey[p.panel];
    if (!type) continue;
    // Heatmap replaces the type colour rather than tinting it: two
    // colour scales on one object read as neither.
    colour.setHex(heat ? heatColor(p.sun_norm ?? 0) : (PANEL_COLOR[p.panel] ?? 0xb08d5c));
    const cos = Math.cos(p.angle);
    const sin = Math.sin(p.angle);

    for (const m of type.members) {
      const [mx, my, mz] = m.c;
      const [sx, sy, sz] = m.s;
      // Rotate the member's local plan position about the vertical, then
      // offset by the panel's own position on the wall.
      const wx = p.c[0] + mx * cos - my * sin;
      const wy = p.c[1] + mx * sin + my * cos;
      const wz = p.z0 + mz;

      // Engine is Z-up; three.js is Y-up, so engine y maps to -z. The
      // rotation angle carries through unchanged: the two handedness
      // flips cancel. Same convention as frameInstances.
      dummy.position.set(wx * CM_TO_M, wz * CM_TO_M, -wy * CM_TO_M);
      dummy.rotation.set(0, p.angle, 0);
      dummy.scale.set(sx * CM_TO_M, sz * CM_TO_M, sy * CM_TO_M);
      dummy.updateMatrix();
      mesh.setMatrixAt(i, dummy.matrix);
      mesh.setColorAt(i, colour);
      i += 1;

      if (box) box.expandByPoint(new THREE.Vector3(
        wx * CM_TO_M, wz * CM_TO_M, -wy * CM_TO_M));
    }
  }
  mesh.instanceMatrix.needsUpdate = true;
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  return { mesh, count: i, panelCount: shown.length };
}

export default function FacadeView({
  catalog, facade, massing, frame, theme = "light",
  showMassing = true, showFrame = true, heat = false, only = null,
}) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);
  const [count, setCount] = useState(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    camera.position.set(45, 28, 45);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    const ambient = new THREE.AmbientLight(0xffffff, 1.8);
    scene.add(ambient);
    const key = new THREE.DirectionalLight(0xfff3e2, 2.1);
    key.position.set(30, 60, 20);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xdfe6ff, 0.6);
    rim.position.set(-30, 20, -25);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);

    let raf;
    const tick = () => {
      controls.update();
      renderer.render(scene, camera);
      raf = requestAnimationFrame(tick);
    };
    tick();

    const resize = () => {
      const w = mount.clientWidth;
      const h = mount.clientHeight;
      if (!w || !h) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h, false);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(mount);

    stateRef.current = {
      scene, camera, controls, group, renderer, grid: null,
      lights: [
        { light: ambient, base: 1.8 },
        { light: key, base: 2.1 },
        { light: rim, base: 0.6 },
      ],
    };

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      stateRef.current = null;
    };
  }, []);

  // Declared after the mount effect so it runs after it on mount, in the
  // same flush — the first composited frame already has the right ground.
  useEffect(() => {
    if (stateRef.current) applySceneTheme(THREE, stateRef.current, theme);
  }, [theme]);

  useEffect(() => {
    const st = stateRef.current;
    if (!st || !catalog || !facade) return;
    const { group, controls, camera } = st;

    for (const child of [...group.children]) {
      group.remove(child);
      child.geometry?.dispose();
      child.material?.dispose();
    }

    const box = new THREE.Box3();

    // The massing behind the panels, faint. Without it the facade floats
    // as a set of loose screens and you cannot tell what it is cladding;
    // with it the panels read as the outside of a building.
    if (showMassing && massing) {
      for (const b of massing.blocks ?? []) {
        const xs = b.base_corners.map((c) => c[0]);
        const ys = b.base_corners.map((c) => c[1]);
        const w = (Math.max(...xs) - Math.min(...xs)) * CM_TO_M;
        const d = (Math.max(...ys) - Math.min(...ys)) * CM_TO_M;
        const h = (b.z1 - b.z0) * CM_TO_M;
        if (w <= 0 || d <= 0 || h <= 0) continue;
        const mesh = new THREE.Mesh(
          new THREE.BoxGeometry(w, h, d),
          new THREE.MeshLambertMaterial({
            color: KIND_COLOR[b.kind] ?? KIND_FALLBACK,
            transparent: true, opacity: b.kind === "outdoor" ? 1 : 0.22,
            depthWrite: b.kind === "outdoor",
          })
        );
        mesh.position.set(
          Math.min(...xs) * CM_TO_M + w / 2,
          b.z0 * CM_TO_M + h / 2,
          -(Math.min(...ys) * CM_TO_M + d / 2)
        );
        group.add(mesh);
        box.expandByObject(mesh);
      }
    }

    // The timber frame behind the panels, ghosted. This is the whole
    // point of showing it: the panel module is 330 and the structural
    // grid is 360, so the two do NOT line up, and the only way to judge
    // how a panel meets a column is to see both at once. Kept
    // translucent and depth-write-off so the frame reads through the
    // cladding rather than z-fighting with it.
    if (showFrame && frame?.members?.length) {
      const { mesh: fmesh, items } = buildFrameInstances(frame.members, box);
      fmesh.material.transparent = true;
      fmesh.material.opacity = 0.3;
      fmesh.material.depthWrite = false;
      // buildFrameInstances leaves the instances at zero scale for the
      // growth animation to drive. There is no animation here, so they
      // are written once at full size.
      const dummy = new THREE.Object3D();
      for (let i = 0; i < items.length; i += 1) {
        const it = items[i];
        dummy.position.set(it.x, it.yBase + it.tall / 2, it.z);
        dummy.rotation.set(0, it.angle, 0);
        dummy.scale.set(it.len, it.tall, it.wide);
        dummy.updateMatrix();
        fmesh.setMatrixAt(i, dummy.matrix);
      }
      fmesh.instanceMatrix.needsUpdate = true;
      fmesh.renderOrder = -1;
      group.add(fmesh);
    }

    const { mesh, count: n, panelCount } = buildPanelInstances(
      catalog, facade.panels ?? [], box, only, heat);
    group.add(mesh);
    setCount({ members: n, panels: panelCount });

    if (!box.isEmpty()) {
      const centre = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3()).length();
      controls.target.copy(centre);
      const dir = camera.position.clone().sub(controls.target).normalize();
      camera.position.copy(centre).add(dir.multiplyScalar(size * 0.8));
      camera.far = size * 12;
      camera.updateProjectionMatrix();
      controls.update();
    }
  }, [catalog, facade, massing, frame, showMassing, showFrame, heat, only, theme]);

  const legend = useMemo(() => {
    if (!catalog) return [];
    const counts = facade?.summary?.counts ?? {};
    const byKey = Object.fromEntries(catalog.panels.map((p) => [p.key, p]));
    return ORDER.filter((k) => byKey[k]).map((k) => ({
      key: k, ...byKey[k], count: counts[k] ?? 0,
    }));
  }, [catalog, facade]);

  return (
    <>
      <div className="viewport">
        <div ref={mountRef} className="canvas-mount" />
        <div className="hint">
          <span>Drag to orbit · scroll to zoom · right-drag to pan</span>
          <span>
            {count
              ? `${count.panels} panels · ${count.members.toLocaleString()} members`
              : "…"}
          </span>
        </div>
      </div>

      {heat && facade?.solar && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h2>Sun received</h2>
          <div style={{
            height: 12, borderRadius: 2, marginBottom: 6,
            background: `linear-gradient(to right, ${HEAT.map(
              ([t, c]) => `rgb(${c[0]},${c[1]},${c[2]}) ${t * 100}%`
            ).join(", ")})`,
          }} />
          {/* Laid out here rather than with .hint: that class is scoped
              to .viewport, so borrowing it outside one silently drops
              the flex layout and the three labels pile up on the left. */}
          <div style={{
            display: "flex", justifyContent: "space-between", gap: 12,
            fontSize: 11, color: "var(--ink-3)", fontVariantNumeric: "tabular-nums",
          }}>
            <span>{facade.solar.min_kwh} kWh/m²·yr</span>
            <span>mean {facade.solar.mean_kwh}</span>
            <span>{facade.solar.max_kwh}</span>
          </div>
          <p className="note" style={{ marginTop: 10 }}>
            Clear-sky irradiation on each panel&rsquo;s own plane at{" "}
            <b>{facade.solar.latitude}°N</b>, walked over{" "}
            <b>{facade.solar.samples}</b> sun positions across the year — direct
            beam by incidence angle plus an isotropic diffuse component, with a
            shadow ray tested against the building&rsquo;s own massing. The
            building shades itself on <b>{facade.solar.self_shaded_pct}%</b> of
            the panel-hours where the sun was in front of a panel at all; that
            is what separates two panels of the same orientation.
          </p>
          <p className="note" style={{ marginTop: 8, fontSize: 11, color: "var(--ink-3)" }}>
            Not a certified daylight study. No neighbouring buildings, no
            weather, and no panel-on-panel shading — a balcony does not shade
            the window below it here, so balconied elevations read slightly
            warm. Comparable panel to panel, which is what a heatmap is for.
          </p>
        </div>
      )}

      <div className="panel" style={{ marginTop: 16 }}>
        <h2>Panel types</h2>
        <table>
          <thead>
            <tr>
              <th>Panel</th><th>Use</th><th className="n">Projects</th>
              <th className="n">Members</th><th className="n">Placed</th>
            </tr>
          </thead>
          <tbody>
            {legend.map((p) => (
              <tr key={p.key} style={{ opacity: only && only !== p.key ? 0.35 : 1 }}>
                <td>
                  <span
                    className="swatch"
                    style={{
                      background: `#${(PANEL_COLOR[p.key] ?? 0).toString(16).padStart(6, "0")}`,
                      height: 9, borderRadius: 2,
                    }}
                  />
                  <b>{p.key}</b> · {p.label}
                </td>
                <td>{p.use}</td>
                <td className="n">{p.projection_cm} cm</td>
                <td className="n">{p.members.length}</td>
                <td className="n">{p.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
