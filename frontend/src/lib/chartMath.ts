// Geometry for the 3D team chart: tiny column-major mat4 helpers and the chart layout.
// The Owner sits at the centre; each level is a ring further out; agents are spaced on their ring.

export type Vec3 = [number, number, number];
export type Mat4 = Float32Array;

export function perspective(fovy: number, aspect: number, near: number, far: number): Mat4 {
  const f = 1 / Math.tan(fovy / 2);
  const nf = 1 / (near - far);
  return new Float32Array([f / aspect, 0, 0, 0, 0, f, 0, 0, 0, 0, (far + near) * nf, -1, 0, 0, 2 * far * near * nf, 0]);
}

export function lookAt(eye: Vec3, target: Vec3, up: Vec3): Mat4 {
  const z = norm(sub(eye, target));
  const x = norm(cross(up, z));
  const y = cross(z, x);
  return new Float32Array([
    x[0], y[0], z[0], 0,
    x[1], y[1], z[1], 0,
    x[2], y[2], z[2], 0,
    -dot(x, eye), -dot(y, eye), -dot(z, eye), 1,
  ]);
}

export function multiply(a: Mat4, b: Mat4): Mat4 {
  const o = new Float32Array(16);
  for (let c = 0; c < 4; c++)
    for (let r = 0; r < 4; r++) {
      let s = 0;
      for (let k = 0; k < 4; k++) s += a[k * 4 + r] * b[c * 4 + k];
      o[c * 4 + r] = s;
    }
  return o;
}

/** Project a world point to CSS pixels. Returns null when behind the camera. */
export function project(m: Mat4, p: Vec3, width: number, height: number): { x: number; y: number; depth: number } | null {
  const x = m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12];
  const y = m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13];
  const w = m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15];
  if (w <= 0.0001) return null;
  return { x: ((x / w) * 0.5 + 0.5) * width, y: (1 - ((y / w) * 0.5 + 0.5)) * height, depth: w };
}

const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: Vec3): Vec3 => { const l = Math.hypot(a[0], a[1], a[2]) || 1; return [a[0] / l, a[1] / l, a[2] / l]; };

export const OWNER_ID = "__owner__";
export const OWNER_POS: Vec3 = [0, 0.35, 0];
export const ringRadius = (levelIndex: number) => 1.5 + levelIndex * 1.2;

/** Agents grouped by level index -> positions on their ring. Deterministic for the same input. */
export function layout(agents: { id: string; levelIndex: number }[]): Map<string, Vec3> {
  const byLevel = new Map<number, string[]>();
  for (const a of agents) byLevel.set(a.levelIndex, [...(byLevel.get(a.levelIndex) ?? []), a.id]);
  const out = new Map<string, Vec3>([[OWNER_ID, OWNER_POS]]);
  for (const [level, ids] of byLevel) {
    const r = ringRadius(level);
    const offset = level * 0.7 + 0.35;
    ids.forEach((id, i) => {
      const a = offset + (i / ids.length) * Math.PI * 2;
      out.set(id, [Math.cos(a) * r, -0.12 * level, Math.sin(a) * r]);
    });
  }
  return out;
}

/** A lifted quadratic arc between two points (a call route), as `segments + 1` points with t in [0,1]. */
export function pointOnArc(a: Vec3, b: Vec3, s: number): Vec3 {
  const d = Math.hypot(a[0] - b[0], a[2] - b[2]);
  const c: Vec3 = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 + 0.35 + d * 0.22, (a[2] + b[2]) / 2];
  const u = 1 - s;
  return [u * u * a[0] + 2 * u * s * c[0] + s * s * b[0], u * u * a[1] + 2 * u * s * c[1] + s * s * b[1], u * u * a[2] + 2 * u * s * c[2] + s * s * b[2]];
}

export function arc(a: Vec3, b: Vec3, segments = 40): { points: Vec3[]; t: number[] } {
  const points: Vec3[] = [];
  const t: number[] = [];
  for (let i = 0; i <= segments; i++) {
    points.push(pointOnArc(a, b, i / segments));
    t.push(i / segments);
  }
  return { points, t };
}

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.trim().replace("#", "");
  const v = h.length === 3 ? h.split("").map((c) => c + c).join("") : h.slice(0, 6);
  const n = parseInt(v, 16);
  if (Number.isNaN(n)) return [0.5, 0.5, 0.5];
  return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
}
