import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

// The engine works in centimetres; three.js is happier around unit
// scale, so everything is divided by 100 on the way into the scene.
const CM_TO_M = 0.01;

const KIND_COLOR = {
  corridor: 0xc9cec7,
  core: 0x9aa196,
  unit: 0xeceee9,
  communal: 0xd7dbd0,
  room: 0xdfe3dc,
};

export default function MassingView({ massing }) {
  const mountRef = useRef(null);
  const stateRef = useRef(null);

  // Scene, camera, renderer and controls are built once and reused --
  // rebuilding them per data change would drop the user's camera
  // position on every regenerate.
  useEffect(() => {
    const mount = mountRef.current;
    if (!mount) return undefined;

    const scene = new THREE.Scene();
    const dark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    scene.background = new THREE.Color(dark ? 0x1a1a19 : 0xfbfcfb);

    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 5000);
    camera.position.set(40, 40, 40);

    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    mount.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;

    scene.add(new THREE.AmbientLight(0xffffff, dark ? 1.5 : 2.1));
    const key = new THREE.DirectionalLight(0xffffff, dark ? 1.6 : 2.0);
    key.position.set(30, 60, 20);
    scene.add(key);
    const rim = new THREE.DirectionalLight(0xffffff, 0.5);
    rim.position.set(-30, 20, -25);
    scene.add(rim);

    const group = new THREE.Group();
    scene.add(group);

    const grid = new THREE.GridHelper(200, 40, dark ? 0x383835 : 0xc3c2b7, dark ? 0x2c2c2a : 0xdfe2df);
    scene.add(grid);

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

    stateRef.current = { scene, camera, controls, group, renderer };

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      controls.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode === mount) mount.removeChild(renderer.domElement);
      stateRef.current = null;
    };
  }, []);

  // Rebuild only the geometry when the massing changes.
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
    const edgeColor = window.matchMedia?.("(prefers-color-scheme: dark)").matches ? 0x000000 : 0x6f6f6a;

    for (const b of massing.blocks) {
      const xs = b.base_corners.map((c) => c[0]);
      const ys = b.base_corners.map((c) => c[1]);
      const w = (Math.max(...xs) - Math.min(...xs)) * CM_TO_M;
      const d = (Math.max(...ys) - Math.min(...ys)) * CM_TO_M;
      const h = (b.z1 - b.z0) * CM_TO_M;
      if (w <= 0 || d <= 0 || h <= 0) continue;

      const geo = new THREE.BoxGeometry(w, h, d);
      const mat = new THREE.MeshLambertMaterial({
        color: KIND_COLOR[b.kind] ?? 0xdddddd,
      });
      const mesh = new THREE.Mesh(geo, mat);
      // three.js is Y-up; the engine is Z-up, so engine y maps to -z.
      mesh.position.set(
        (Math.min(...xs) * CM_TO_M) + w / 2,
        (b.z0 * CM_TO_M) + h / 2,
        -((Math.min(...ys) * CM_TO_M) + d / 2)
      );
      group.add(mesh);

      const edges = new THREE.LineSegments(
        new THREE.EdgesGeometry(geo),
        new THREE.LineBasicMaterial({ color: edgeColor, transparent: true, opacity: 0.35 })
      );
      edges.position.copy(mesh.position);
      group.add(edges);

      box.expandByObject(mesh);
    }

    // Frame the model once per data change, preserving orbit angle.
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
  }, [massing]);

  return (
    <div className="viewport">
      <div ref={mountRef} style={{ width: "100%", height: "min(66vh, 640px)" }} />
      <div className="hint">
        <span>Drag to orbit · scroll to zoom · right-drag to pan</span>
        <span>{massing ? `${massing.blocks.length} blocks` : "…"}</span>
      </div>
    </div>
  );
}
