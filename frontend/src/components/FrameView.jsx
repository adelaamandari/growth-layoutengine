import { useCallback, useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import {
  STEP_STRIDE_MS,
  applyMembers,
  buildFrameInstances,
  clamp01,
  frameDuration,
  prefersReducedMotion,
} from "./frameInstances";

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
        applyMembers(a.mesh, a.items, a.dummy, elapsed);
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
          applyMembers(a.mesh, a.items, a.dummy, Infinity);
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

    const box = new THREE.Box3();
    const { mesh, items } = buildFrameInstances(members, box);
    group.add(mesh);

    const labels = frame.step_labels?.length ? frame.step_labels : ["growing"];
    const total = frameDuration(labels.length);
    const play = animate && !prefersReducedMotion();
    animRef.current = {
      mesh, items, labels, total,
      t0: performance.now(), playing: play, lastStep: -1,
      dummy: new THREE.Object3D(),
    };

    applyMembers(mesh, items, animRef.current.dummy, play ? 0 : Infinity);
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
    applyMembers(a.mesh, a.items, a.dummy, 0);
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
                ? `${frame.summary?.member_count ?? 0} members · ${frame.summary?.node_count ?? 0} columns`
                : "…"}
          </span>
          <span className="track" aria-hidden="true"><span className="fill" ref={fillRef} /></span>
          <button className="btn mini" onClick={replay} disabled={!frame}>Replay growth</button>
        </span>
      </div>
    </div>
  );
}
