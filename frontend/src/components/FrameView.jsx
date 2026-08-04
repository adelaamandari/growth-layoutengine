import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// The engine works in centimetres; three.js is happier around unit
// scale, so everything is divided by 100 on the way into the scene.
const CM_TO_M = 0.01;

// Tones per surveyed part, keyed to the material names in
// components.glb. N is the connector PLATE, which reads pale against
// the timber in Adela's render rather than as another wood tone.
const COMPONENT_COLOR = {
  Column: 0xb08d5c,  // "custom wood" -- the four posts and their rungs
  N: 0xdcdcd4,       // the 60x60 connector plate
  SA: 0xc9a97a,      // "tex1" beam course
  SB: 0x8f6f45,
  SC: 0xd9c49c,
  F1: 0xa8834e,      // "Custom (2)" lacing layer
  F2: 0x6f5433,      // "tex2" lacing layer
  B2: 0xc2a374,      // short verticals inside the capital
};
const DEFAULT_COLOR = 0xb08d5c;

// Growth pacing. Slower than the massing animation: this one is the
// point of the view rather than a flourish on top of it.
const STEP_STRIDE_MS = 340;
const MEMBER_RISE_MS = 620;
// Members in the same step are nudged apart so a course of beams
// arrives raggedly rather than in perfect lockstep.
const JITTER_MS = 130;

const clamp01 = (t) => (t < 0 ? 0 : t > 1 ? 1 : t);
const easeOut = (t) => 1 - (1 - t) ** 3;

const prefersReducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

// Deterministic per-index jitter -- a real random() would reshuffle the
// animation on every replay, which reads as noise rather than as the
// same building growing the same way twice.
const jitter = (i) => ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1;

export default function FrameView({ frame, animate = true }) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);
  const animRef = useRef(null);
  const fillRef = useRef(null);
  const [phase, setPhase] = useState(null);

  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    scene.background = new THREE.Color(dark ? 0x1a1a19 : 0xfbfcfb);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    camera.position.set(40, 30, 40);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    scene.add(new THREE.AmbientLight(0xffffff, dark ? 1.4 : 1.9));
    const key = new THREE.DirectionalLight(0xfff3e2, dark ? 1.7 : 2.0);
    key.position.set(30, 60, 20);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xdfe6ff, 0.55);
    rim.position.set(-30, 20, -25);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);

    const grid = new THREE.GridHelper(200, 40, dark ? 0x383835 : 0xc3c2b7, dark ? 0x2c2c2a : 0xdfe2df);
    scene.add(grid);

    let raf;
    const tick = () => {
      const a = animRef.current;
      if (a?.playing) {
        const elapsed = performance.now() - a.t0;
        applyAll(a, elapsed);
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
          applyAll(a, Infinity);
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

    stateRef.current = { scene, camera, controls, group, renderer };

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

  useEffect(() => {
    const st = stateRef.current;
    if (!st || !frame) return;
    const { group, controls, camera } = st;

    for (const child of [...group.children]) {
      group.remove(child);
      child.geometry?.dispose();
      child.material?.dispose();
    }

    const members = frame.members ?? [];
    if (!members.length) return;

    // One InstancedMesh for the whole frame. At a couple of thousand
    // members, a Mesh each would cost a draw call each; instanced, the
    // entire building is one.
    const geo = new THREE.BoxGeometry(1, 1, 1);
    const mat = new THREE.MeshLambertMaterial();
    const mesh = new THREE.InstancedMesh(geo, mat, members.length);
    mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    group.add(mesh);

    const colour = new THREE.Color();
    const items = new Array(members.length);
    const box = new THREE.Box3();

    for (let i = 0; i < members.length; i += 1) {
      const m = members[i];
      const [cx, cy, cz] = m.c;
      const [sx, sy, sz] = m.s;
      colour.setHex(COMPONENT_COLOR[m.component] ?? DEFAULT_COLOR);
      mesh.setColorAt(i, colour);

      // Engine is Z-up (x, y in plan, z height); three.js is Y-up, so
      // engine y maps to -z. The member's own axis is local x, rotated
      // about the vertical by `angle`.
      items[i] = {
        // Only beams extend sideways. Everything else -- posts, rungs,
        // the connector plate, the capital lacing -- rises in place.
        post: m.kind !== "beam",
        x: cx * CM_TO_M,
        z: -cy * CM_TO_M,
        yBase: (cz - sz / 2) * CM_TO_M,   // underside, the end that stays put
        len: sx * CM_TO_M,
        wide: sy * CM_TO_M,
        tall: sz * CM_TO_M,
        angle: m.angle,
        sign: m.grow_sign,
        start: m.growth_step * STEP_STRIDE_MS + jitter(i) * JITTER_MS,
      };

      const half = Math.max(sx, sy) * CM_TO_M / 2;
      box.expandByPoint(new THREE.Vector3(items[i].x - half, items[i].yBase, items[i].z - half));
      box.expandByPoint(new THREE.Vector3(items[i].x + half, items[i].yBase + items[i].tall, items[i].z + half));
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;

    const labels = frame.step_labels?.length ? frame.step_labels : ["growing"];
    const total = Math.max(
      1,
      (labels.length - 1) * STEP_STRIDE_MS + MEMBER_RISE_MS + JITTER_MS
    );
    const play = animate && !prefersReducedMotion();
    animRef.current = {
      mesh, items, labels, total,
      t0: performance.now(), playing: play, lastStep: -1,
      dummy: new THREE.Object3D(),
    };

    applyAll(animRef.current, play ? 0 : Infinity);
    if (fillRef.current) fillRef.current.style.width = play ? "0%" : "100%";
    if (!play) setPhase(null);

    // Frame on the FINISHED extent so the camera holds still while the
    // structure grows into it rather than chasing a moving box.
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
  }, [frame, animate]);

  const replay = useCallback(() => {
    const a = animRef.current;
    if (!a) return;
    a.t0 = performance.now();
    a.lastStep = -1;
    a.playing = true;
    applyAll(a, 0);
    if (fillRef.current) fillRef.current.style.width = "0%";
  }, []);

  return (
    <div className="viewport">
      <div ref={mountRef} style={{ width: "100%", height: "min(66vh, 640px)" }} />
      <div className="hint">
        <span>Drag to orbit · scroll to zoom · right-drag to pan</span>
        <span className="growth">
          <span className="phase">
            {phase
              ? `${String(phase.step + 1).padStart(2, "0")}/${phase.total} · ${phase.label}`
              : frame
                ? `${frame.summary?.member_count ?? 0} members · ${frame.summary?.junction_count ?? 0} capitals`
                : "…"}
          </span>
          <span className="track" aria-hidden="true"><span className="fill" ref={fillRef} /></span>
          <button className="btn mini" onClick={replay} disabled={!frame}>Replay growth</button>
        </span>
      </div>
    </div>
  );
}

// Write every instance matrix for the given elapsed time. Posts rise
// from their underside; beams EXTEND along their own axis away from the
// column that is already standing, which is what makes the spread read
// as reaching outward rather than as members switching on.
function applyAll(a, elapsed) {
  const { mesh, items, dummy } = a;
  for (let i = 0; i < items.length; i += 1) {
    const it = items[i];
    const p = easeOut(clamp01((elapsed - it.start) / MEMBER_RISE_MS));
    if (p <= 0) {
      // Zero scale collapses the instance to a point rather than
      // needing a separate visibility flag, which InstancedMesh has no
      // per-instance equivalent of.
      dummy.position.set(it.x, it.yBase, it.z);
      dummy.rotation.set(0, it.angle, 0);
      dummy.scale.set(0, 0, 0);
    } else if (it.post) {
      dummy.position.set(it.x, it.yBase + (it.tall * p) / 2, it.z);
      dummy.rotation.set(0, it.angle, 0);
      dummy.scale.set(it.len, it.tall * p, it.wide);
    } else {
      // Local-x offset that keeps the anchored end pinned as the beam
      // lengthens; rotated into world by the member's own angle.
      const off = it.sign * (it.len / 2) * (1 - p);
      dummy.position.set(
        it.x + off * Math.cos(it.angle),
        it.yBase + it.tall / 2,
        it.z - off * Math.sin(it.angle)
      );
      dummy.rotation.set(0, it.angle, 0);
      dummy.scale.set(it.len * p, it.tall, it.wide);
    }
    dummy.updateMatrix();
    mesh.setMatrixAt(i, dummy.matrix);
  }
  mesh.instanceMatrix.needsUpdate = true;
}
