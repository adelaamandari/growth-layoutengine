// frameInstances.js
// How a list of timber members becomes one InstancedMesh, and how that
// mesh animates as the growth front reaches each member.
//
// Shared by the Frame view (timber alone) and the Build view (timber
// colonising the massing). It lives apart from both so the two cannot
// drift into drawing the same members two different ways.

import * as THREE from "three";

// The engine works in centimetres; three.js is happier around unit
// scale, so everything is divided by 100 on the way into the scene.
export const CM_TO_M = 0.01;

// Tones per surveyed part, keyed to the material names in
// components.glb. N is the connector PLATE, which reads pale against
// the timber in Adela's render rather than as another wood tone.
export const COMPONENT_COLOR = {
  Column: 0xb08d5c,  // "custom wood" -- the four posts and their rungs
  N: 0xdcdcd4,       // the 60x60 connector plate
  SA: 0xc9a97a,      // "tex1" beam course
  SB: 0x8f6f45,
  SC: 0xd9c49c,
  F1: 0xa8834e,      // "Custom (2)" lacing layer
  F2: 0x6f5433,      // "tex2" lacing layer
  B2: 0xc2a374,      // short verticals inside the capital
  Deck: 0x9d8f78,    // the storey deck -- greyer than the members, so
                     // the structure still reads against it
};
export const DEFAULT_COLOR = 0xb08d5c;

// Growth pacing. Slower than the massing animation: the spread is the
// point of these views rather than a flourish on top of them.
export const STEP_STRIDE_MS = 340;
export const MEMBER_RISE_MS = 620;
// Members in the same step are nudged apart so a course of beams
// arrives raggedly rather than in perfect lockstep.
export const JITTER_MS = 130;

export const clamp01 = (t) => (t < 0 ? 0 : t > 1 ? 1 : t);
export const easeOut = (t) => 1 - (1 - t) ** 3;

export const prefersReducedMotion = () =>
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

// Deterministic per-index jitter -- a real random() would reshuffle the
// animation on every replay, which reads as noise rather than as the
// same building growing the same way twice.
const jitter = (i) => ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1;

/**
 * One InstancedMesh for the whole frame, plus the per-member animation
 * records. At a few thousand members, a Mesh each would cost a draw
 * call each; instanced, the entire building is one.
 *
 * `box`, if given, is expanded to the FINISHED extent of the frame so a
 * caller can frame the camera on where the building ends up rather than
 * chasing it as it grows.
 */
export function buildFrameInstances(members, box) {
  const geo = new THREE.BoxGeometry(1, 1, 1);
  const mat = new THREE.MeshLambertMaterial();
  const mesh = new THREE.InstancedMesh(geo, mat, members.length);
  mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);

  const colour = new THREE.Color();
  const items = new Array(members.length);

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
      // Only members that SPAN extend sideways -- primary grid beams
      // and the wall infill between the bays. Everything else (posts,
      // rungs, the connector plate, the capital lacing, the floor deck)
      // rises in place.
      post: m.kind !== "beam" && m.kind !== "infill",
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

    if (box) {
      const half = Math.max(sx, sy) * CM_TO_M / 2;
      box.expandByPoint(new THREE.Vector3(items[i].x - half, items[i].yBase, items[i].z - half));
      box.expandByPoint(new THREE.Vector3(
        items[i].x + half, items[i].yBase + items[i].tall, items[i].z + half));
    }
  }
  if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;

  return { mesh, items };
}

/** How long a frame of `stepCount` growth steps takes end to end. */
export function frameDuration(stepCount) {
  return Math.max(1, (stepCount - 1) * STEP_STRIDE_MS + MEMBER_RISE_MS + JITTER_MS);
}

/**
 * Write every instance matrix for the given elapsed time. Posts rise
 * from their underside; beams EXTEND along their own axis away from the
 * column that is already standing, which is what makes the spread read
 * as reaching outward rather than as members switching on.
 */
export function applyMembers(mesh, items, dummy, elapsed) {
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
