import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { KIND_COLOR, KIND_FALLBACK, applySceneTheme, sceneTheme } from "../theme";
import { addSiteOutline, prismGeometry } from "./prism";

// The engine works in centimetres; three.js is happier around unit
// scale, so everything is divided by 100 on the way into the scene.
const CM_TO_M = 0.01;

// Growth animation timing. STEP_STRIDE is the gap between consecutive
// growth steps STARTING; BLOCK_RISE is how long one step takes to reach
// full height. Stride is deliberately shorter than rise so consecutive
// steps overlap and the building reads as growing continuously, rather
// than as a sequence of separate pops.
const STEP_STRIDE_MS = 200;
const BLOCK_RISE_MS = 560;

const clamp01 = (t) => (t < 0 ? 0 : t > 1 ? 1 : t);
const easeOut = (t) => 1 - (1 - t) ** 3;

const prefersReducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

// Set one block to a growth progress of p (0 = not yet built, 1 = full
// height). Scaling about the box centre would sink the block into the
// ground, so position.y is lifted in step with the scale to keep its
// underside pinned at z0 -- a building grows up from its slab.
function applyGrowth(item, p) {
  // Exactly 0 makes the normal matrix degenerate and three.js warns, so
  // the floor is a hair above zero and visibility does the real hiding.
  const s = Math.max(p, 1e-4);
  // No position correction: the prism's base is already at its slab, so
  // scaling y grows it upward from there. The old box was centred on
  // itself and had to be lifted every frame to keep its underside put.
  item.mesh.scale.y = s;
  item.edges.scale.y = s;
  const on = p > 0.001;
  item.mesh.visible = on;
  item.edges.visible = on;
}

export default function MassingView({ massing, animate = true, theme = "light", site = null }) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);
  const animRef = useRef(null);
  const fillRef = useRef(null);
  const [phase, setPhase] = useState(null);

  // Scene, camera, renderer and controls are built once and reused --
  // rebuilding them per data change would drop the user's camera
  // position on every regenerate.
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    camera.position.set(40, 40, 40);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    // Base intensities, i.e. what these are at lightScale 1. The theme
    // effect below scales them; it cannot read them back off the lights
    // afterwards without compounding, so they are recorded here.
    const ambient = new THREE.AmbientLight(0xffffff, 2.1);
    scene.add(ambient);
    const key = new THREE.DirectionalLight(0xffffff, 2.0);
    key.position.set(30, 60, 20);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xffffff, 0.5);
    rim.position.set(-30, 20, -25);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);

    let raf;
    const tick = () => {
      const a = animRef.current;
      if (a?.playing) {
        const elapsed = performance.now() - a.t0;
        for (const it of a.items) {
          applyGrowth(it, easeOut(clamp01((elapsed - it.start) / BLOCK_RISE_MS)));
        }
        // The progress bar is written straight to the DOM: driving it
        // through React state would re-render this component ~60 times
        // a second for a purely visual readout.
        if (fillRef.current) {
          fillRef.current.style.width = `${clamp01(elapsed / a.total) * 100}%`;
        }
        const step = Math.min(a.labels.length - 1, Math.floor(elapsed / STEP_STRIDE_MS));
        if (step !== a.lastStep) {
          a.lastStep = step;
          setPhase({ step, label: a.labels[step], total: a.labels.length });
        }
        if (elapsed >= a.total) {
          a.playing = false;
          for (const it of a.items) applyGrowth(it, 1);
          if (fillRef.current) fillRef.current.style.width = "100%";
          setPhase(null);
        }
      }
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
        { light: ambient, base: 2.1 },
        { light: key, base: 2.0 },
        { light: rim, base: 0.5 },
      ],
    };

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      stateRef.current = null;
      animRef.current = null;
    };
  }, []);

  // Background, ground grid and light levels follow the theme. Declared
  // AFTER the effect above so it runs after it on mount -- both are in
  // the same flush, so the first composited frame already has the right
  // colours and a dark user sees no white flash.
  useEffect(() => {
    if (stateRef.current) applySceneTheme(THREE, stateRef.current, theme);
  }, [theme]);

  // Rebuild only the geometry when the massing changes. Deliberately NOT
  // on `theme`: a theme change recolours the edges in place, above, so
  // toggling light/dark does not restart the growth animation.
  useEffect(() => {
    const st = stateRef.current;
    if (!st || !massing) return;
    const { group, controls, camera } = st;

    for (const child of [...group.children]) {
      group.remove(child);
      child.geometry?.dispose();
      child.material?.dispose();
    }

    const box = new THREE.Box3();
    const edgeColor = sceneTheme(theme).edge;

    // The plot, on the ground. Two loops: the developable boundary the
    // building actually has to sit inside, and the street centrelines
    // faint behind it -- so the massing can be read against the plot it
    // stands on rather than floating in an empty grid.
    addSiteOutline(THREE, group, site, box);

    const items = [];
    // growth_step, not array order: a branch corridor is appended after
    // the units on it (its length isn't known until they're placed) but
    // structurally grows before them. See growth._assign_growth_steps.
    const labels = [];

    for (const b of massing.blocks) {
      const xs = b.base_corners.map((c) => c[0]);
      const ys = b.base_corners.map((c) => c[1]);
      const w = (Math.max(...xs) - Math.min(...xs)) * CM_TO_M;
      const d = (Math.max(...ys) - Math.min(...ys)) * CM_TO_M;
      const h = (b.z1 - b.z0) * CM_TO_M;
      if (w <= 0 || d <= 0 || h <= 0) continue;

      // Extruded from the REAL corners, not a bounding box: elements are
      // rotated under the site strategy and a box would draw them
      // overlapping when they do not. See prism.js.
      const geo = prismGeometry(b.base_corners, b.z1 - b.z0);
      const mat = new THREE.MeshLambertMaterial({
        color: KIND_COLOR[b.kind] ?? KIND_FALLBACK,
      });
      const mesh = new THREE.Mesh(geo, mat);
      // The prism's base is at local y = 0, so this is the only place
      // its height above ground is set -- and the growth animation can
      // then scale y without correcting position.
      const y0 = b.z0 * CM_TO_M;
      mesh.position.y = y0;
      group.add(mesh);

      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: edgeColor, transparent: true, opacity: 0.35 })
      );
      edges.position.y = y0;
      group.add(edges);

      // Older API responses have no growth_step; fall back to one step
      // for everything, which just means the whole model rises at once.
      const step = b.growth_step ?? 0;
      items.push({ mesh, edges, y0, h, start: step * STEP_STRIDE_MS });
      // A duplex's rooms share their unit's step, so the first label
      // seen for a step is the thing that step actually builds.
      if (labels[step] === undefined) labels[step] = b.label;

      box.expandByObject(mesh);
    }

    for (let i = 0; i < labels.length; i += 1) if (labels[i] === undefined) labels[i] = "—";

    const total = Math.max(1, (labels.length - 1) * STEP_STRIDE_MS + BLOCK_RISE_MS);
    const play = animate && !prefersReducedMotion() && items.length > 0;
    animRef.current = { items, labels, total, t0: performance.now(), playing: play, lastStep: -1 };

    if (!play) {
      for (const it of items) applyGrowth(it, 1);
      if (fillRef.current) fillRef.current.style.width = "100%";
      setPhase(null);
    } else {
      for (const it of items) applyGrowth(it, 0);
      if (fillRef.current) fillRef.current.style.width = "0%";
    }

    // Frame the model once per data change, preserving orbit angle.
    // Deliberately framed on the FINISHED extent, computed above from
    // full-height meshes, so the camera holds still while the building
    // grows into it instead of chasing a moving bounding box.
    if (!box.isEmpty()) {
      const centre = box.getCenter(new THREE.Vector3());
      const size = box.getSize(new THREE.Vector3()).length();
      controls.target.copy(centre);
      const dir = camera.position.clone().sub(controls.target).normalize();
      camera.position.copy(centre).add(dir.multiplyScalar(size * 0.85));
      camera.far = size * 12;
      camera.updateProjectionMatrix();
      controls.update();
    }
  }, [massing, animate, site, theme]);

  const replay = useCallback(() => {
    const a = animRef.current;
    if (!a || !a.items.length) return;
    for (const it of a.items) applyGrowth(it, 0);
    a.t0 = performance.now();
    a.lastStep = -1;
    a.playing = true;
    if (fillRef.current) fillRef.current.style.width = "0%";
  }, []);

  return (
    <div className="viewport">
      <div ref={mountRef} className="canvas-mount" />
      <div className="hint">
        <span>Drag to orbit · scroll to zoom · right-drag to pan</span>
        <span className="growth">
          <span className="phase">
            {phase
              ? `${String(phase.step + 1).padStart(2, "0")}/${phase.total} · ${phase.label}`
              : massing
                ? `${massing.blocks.length} blocks · ${massing.growth_steps ?? "—"} steps`
                : "…"}
          </span>
          <span className="track" aria-hidden="true"><span className="fill" ref={fillRef} /></span>
          <button className="btn mini" onClick={replay} disabled={!massing}>Replay growth</button>
        </span>
      </div>
    </div>
  );
}
