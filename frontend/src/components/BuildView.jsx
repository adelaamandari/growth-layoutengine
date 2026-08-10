import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  CM_TO_M,
  STEP_STRIDE_MS,
  applyMembers,
  buildFrameInstances,
  clamp01,
  easeOut,
  frameDuration,
  prefersReducedMotion,
} from "./frameInstances";
import { KIND_COLOR, KIND_FALLBACK, applySceneTheme, sceneTheme } from "../theme";
import { prismGeometry } from "./prism";

// The whole point of this view: the massing volume arrives FIRST, then
// the real timber components colonise it. Both are drawn in one scene
// on one clock, so what you see is the same building twice over --
// what it occupies, then what it is built of.
//
//   phase 1  blocks rise in program order (entrance -> corridor -> core
//            -> branch corridors -> rooms), exactly as the massing tab
//   phase 2  they fade to a ghost, staying as the volume being filled
//   phase 3  timber spreads out from the entrance AND climbs, ring by
//            ring, until the walls are filled with courses
//
// Massing pacing is quicker than the massing tab's own: here it is the
// prologue, not the subject.
const MASS_STRIDE_MS = 160;
const BLOCK_RISE_MS = 520;
const GHOST_MS = 600;

// What the volume fades to. Low enough to read the timber through it,
// high enough that the envelope is still legible as a volume.
const GHOST_OPACITY = 0.12;

const pad = (n) => String(n).padStart(2, "0");

// Set one block to a growth progress of p (0 = not yet built, 1 = full
// height), keeping its underside pinned at z0 -- a building grows up
// from its slab rather than scaling about its own centre.
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

// Fade the volume from solid to ghost. depthWrite goes off as soon as
// the fade starts: a translucent box that still writes depth would hide
// the timber growing inside it, which is the one thing this view exists
// to show.
//
// Outdoor pads do NOT fade. The ghost means "this volume is about to be
// replaced by the timber that fills it" — and nothing fills a garden,
// so fading it would just delete the open space from the finished view
// with no member arriving to take its place.
function applyGhost(item, g) {
  if (item.solid) return;
  item.mesh.material.opacity = 1 - (1 - GHOST_OPACITY) * g;
  item.mesh.material.depthWrite = g <= 0.001;
  item.edges.material.opacity = 0.35 - 0.07 * g;
}

export default function BuildView({ massing, frame, animate = true, theme = "light" }) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);
  const animRef = useRef(null);
  const fillRef = useRef(null);
  const [phase, setPhase] = useState(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    camera.position.set(40, 30, 40);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    // Base intensities, i.e. what these are at lightScale 1 -- the theme
    // effect scales them and cannot recover the base from the light.
    const ambient = new THREE.AmbientLight(0xffffff, 1.9);
    scene.add(ambient);
    const key = new THREE.DirectionalLight(0xfff3e2, 2.0);
    key.position.set(30, 60, 20);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xdfe6ff, 0.55);
    rim.position.set(-30, 20, -25);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);

    let raf;
    const tick = () => {
      const a = animRef.current;
      if (a?.playing) {
        const elapsed = performance.now() - a.t0;
        applyAt(a, elapsed, setPhase);
        if (fillRef.current) {
          fillRef.current.style.width = `${clamp01(elapsed / a.total) * 100}%`;
        }
        if (elapsed >= a.total) {
          a.playing = false;
          applyAt(a, Infinity, setPhase);
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
        { light: ambient, base: 1.9 },
        { light: key, base: 2.0 },
        { light: rim, base: 0.55 },
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
  // after the effect above so it runs after it on mount, in the same
  // flush -- the first composited frame already has the right colours.
  useEffect(() => {
    if (stateRef.current) applySceneTheme(THREE, stateRef.current, theme);
  }, [theme]);

  useEffect(() => {
    const st = stateRef.current;
    if (!st || !massing || !frame) return;
    const { group, controls, camera } = st;

    for (const child of [...group.children]) {
      group.remove(child);
      child.geometry?.dispose();
      child.material?.dispose();
    }

    const box = new THREE.Box3();
    const edgeColor = sceneTheme(theme).edge;

    // --- the volume ---------------------------------------------------
    const blocks = [];
    const massLabels = [];
    for (const b of massing.blocks ?? []) {
      const xs = b.base_corners.map((c) => c[0]);
      const ys = b.base_corners.map((c) => c[1]);
      const w = (Math.max(...xs) - Math.min(...xs)) * CM_TO_M;
      const d = (Math.max(...ys) - Math.min(...ys)) * CM_TO_M;
      const h = (b.z1 - b.z0) * CM_TO_M;
      if (w <= 0 || d <= 0 || h <= 0) continue;

      // Real corners, not a bounding box -- see prism.js.
      const geo = prismGeometry(b.base_corners, b.z1 - b.z0);
      // transparent from the outset even while opaque: switching a
      // material to transparent mid-animation recompiles its shader and
      // drops a frame right at the moment the fade should be smooth.
      const mat = new THREE.MeshLambertMaterial({
        color: KIND_COLOR[b.kind] ?? KIND_FALLBACK,
        transparent: true,
        opacity: 1,
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

      const step = b.growth_step ?? 0;
      blocks.push({
        mesh, edges, y0, h, start: step * MASS_STRIDE_MS,
        solid: b.kind === "outdoor",
      });
      // A duplex's rooms share their unit's step, so the first label
      // seen for a step is the thing that step actually builds.
      if (massLabels[step] === undefined) massLabels[step] = b.label;

      box.expandByObject(mesh);
    }
    for (let i = 0; i < massLabels.length; i += 1) {
      if (massLabels[i] === undefined) massLabels[i] = "—";
    }

    // --- the timber ---------------------------------------------------
    const members = frame.members ?? [];
    const { mesh, items } = buildFrameInstances(members, box);
    group.add(mesh);

    const frameLabels = frame.step_labels?.length ? frame.step_labels : ["growing"];
    const massTotal = massLabels.length
      ? (massLabels.length - 1) * MASS_STRIDE_MS + BLOCK_RISE_MS
      : 0;
    const frameAt = massTotal + GHOST_MS;
    const frameTotal = members.length ? frameDuration(frameLabels.length) : 0;

    const play = animate && !prefersReducedMotion() && (blocks.length > 0 || members.length > 0);
    animRef.current = {
      blocks, massLabels, massTotal, frameAt,
      mesh, items, frameLabels,
      total: frameAt + frameTotal,
      dummy: new THREE.Object3D(),
      t0: performance.now(), playing: play, lastKey: null,
    };

    applyAt(animRef.current, play ? 0 : Infinity, setPhase);
    if (fillRef.current) fillRef.current.style.width = play ? "0%" : "100%";
    if (!play) setPhase(null);

    // Frame on the FINISHED extent -- volume and timber together -- so
    // the camera holds still while the building grows into it.
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
  }, [massing, frame, animate]);

  const replay = useCallback(() => {
    const a = animRef.current;
    if (!a) return;
    a.t0 = performance.now();
    a.lastKey = null;
    a.playing = true;
    applyAt(a, 0, setPhase);
    if (fillRef.current) fillRef.current.style.width = "0%";
  }, []);

  const summary = frame?.summary;

  return (
    <div className="viewport">
      <div ref={mountRef} className="canvas-mount" />
      <div className="hint">
        <span>Drag to orbit · scroll to zoom · right-drag to pan</span>
        <span className="growth">
          <span className="phase">
            {phase
              ? phase.label
              : massing && summary
                ? `${massing.blocks.length} blocks · ${summary.member_count} members · ${summary.courses_per_storey ?? 1} course${(summary.courses_per_storey ?? 1) === 1 ? "" : "s"}/storey`
                : "…"}
          </span>
          <span className="track" aria-hidden="true"><span className="fill" ref={fillRef} /></span>
          <button className="btn mini" onClick={replay} disabled={!massing || !frame}>
            Replay growth
          </button>
        </span>
      </div>
    </div>
  );
}

// Drive the whole sequence from one elapsed time: volume, ghost, timber.
function applyAt(a, elapsed, setPhase) {
  const { blocks, mesh, items, dummy } = a;

  for (const it of blocks) {
    applyGrowth(it, easeOut(clamp01((elapsed - it.start) / BLOCK_RISE_MS)));
  }
  const ghost = clamp01((elapsed - a.massTotal) / GHOST_MS);
  for (const it of blocks) applyGhost(it, ghost);

  if (items.length) applyMembers(mesh, items, dummy, elapsed - a.frameAt);

  // The readout is a single string across all three phases; only push it
  // into React when it actually changes, or this re-renders ~60x a second.
  let key;
  if (elapsed < a.massTotal && a.massLabels.length) {
    const step = Math.min(a.massLabels.length - 1, Math.floor(elapsed / MASS_STRIDE_MS));
    key = `${pad(step + 1)}/${a.massLabels.length} · volume · ${a.massLabels[step]}`;
  } else if (elapsed < a.frameAt) {
    key = "volume complete · timber taking hold";
  } else {
    const step = Math.min(
      a.frameLabels.length - 1,
      Math.floor((elapsed - a.frameAt) / STEP_STRIDE_MS)
    );
    key = `${pad(step + 1)}/${a.frameLabels.length} · timber · ${a.frameLabels[step]}`;
  }
  if (key !== a.lastKey) {
    a.lastKey = key;
    setPhase({ label: key });
  }
}
