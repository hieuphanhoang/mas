// The team chart: an interactive 3D (WebGL) chart of one project's agents.
// The Owner is the compass rose at the centre, each level is a tick-marked ring, each agent is a
// round station coloured by its state, allowed call routes are dashed
// arcs and live calls are magenta tracers flying along their arc. Drag to turn, scroll to zoom,
// click a station (or its label) to open that agent. Plain WebGL 1, no library.
import { useEffect, useMemo, useRef, useState } from "react";
import { Glyph, Icon, type Harness } from "./icons";
import { OWNER_ID, OWNER_POS, arc, hexToRgb, layout, lookAt, multiply, perspective, pointOnArc, project, ringRadius, type Vec3 } from "../lib/chartMath";

export type ChartState = "offline" | "starting" | "busy" | "needs_input" | "idle" | "stopping" | "error" | "unknown";
export interface ChartAgent { id: string; name: string; model: string; harness: Harness; state: ChartState; levelIndex: number }
export interface ChartCall { from: string | null; to: string; live: boolean }

interface Props {
  title: string;
  subtitle?: string;
  agents: ChartAgent[];
  levelCount: number;
  edges: { from_agent_id: string; to_agent_id: string }[];
  calls: ChartCall[];
  selected: string | null;
  onSelect: (id: string) => void;
}

const STATE_VAR: Record<ChartState, string> = {
  idle: "--ok", busy: "--amber", starting: "--amber", stopping: "--amber",
  needs_input: "--alert", error: "--alert", offline: "--offline", unknown: "--chart",
};
const BEARINGS = [["000", 0], ["090", Math.PI / 2], ["180", Math.PI], ["270", Math.PI * 1.5]] as const;

const LINE_VS = `
attribute vec3 a_pos; attribute float a_t;
uniform mat4 u_mvp; varying float v_t; varying float v_w;
void main(){ vec4 p = u_mvp * vec4(a_pos, 1.0); gl_Position = p; v_t = a_t; v_w = p.w; }`;
const LINE_FS = `
precision mediump float;
uniform vec4 u_color; uniform float u_dash; uniform float u_phase; uniform vec2 u_fog;
varying float v_t; varying float v_w;
void main(){
  if (u_dash > 0.0 && fract(v_t * u_dash - u_phase) > 0.55) discard;
  float f = 1.0 - 0.32 * clamp((v_w - u_fog.x) / (u_fog.y - u_fog.x), 0.0, 1.0);
  gl_FragColor = vec4(u_color.rgb, u_color.a * f);
}`;
const POINT_VS = `
attribute vec3 a_pos; attribute float a_size; attribute vec4 a_color; attribute float a_shape;
uniform mat4 u_mvp; uniform float u_scale; varying vec4 v_color; varying float v_shape;
void main(){
  vec4 p = u_mvp * vec4(a_pos, 1.0); gl_Position = p;
  gl_PointSize = a_size * u_scale / p.w; v_color = a_color; v_shape = a_shape;
}`;
// shapes: 0 dot, 1 diamond (Claude), 2 square (Codex), 3 triangle (opencode), 4 hexagon (Gemini CLI),
// 5 hollow ring (relay, Owner, selection), 6 soft halo
const POINT_FS = `
precision mediump float;
uniform vec3 u_rim; varying vec4 v_color; varying float v_shape;
float sdf(vec2 c, float s){
  if (s < 0.5) return length(c);
  if (s < 1.5) return abs(c.x) + abs(c.y);
  if (s < 2.5) return max(abs(c.x), abs(c.y)) * 1.15;
  if (s < 3.5) { vec2 q = vec2(c.x, -c.y + 0.22) / 0.92; return max(-2.0 * q.y, 1.732 * abs(q.x) + q.y); }
  if (s < 4.5) { vec2 q = abs(c); return max(q.x * 0.866 + q.y * 0.5, q.y) * 1.12; }
  return length(c);
}
void main(){
  vec2 c = gl_PointCoord * 2.0 - 1.0;
  float d = sdf(c, v_shape);
  if (v_shape > 5.5) { gl_FragColor = vec4(v_color.rgb, v_color.a * (1.0 - smoothstep(0.35, 1.0, d))); return; }
  if (d > 1.0) discard;
  float aa = 1.0 - smoothstep(0.9, 1.0, d);
  if (v_shape > 4.5) { if (d < 0.7) discard; gl_FragColor = vec4(v_color.rgb, v_color.a * aa); return; }
  vec3 col = d > 0.74 ? u_rim : v_color.rgb;
  gl_FragColor = vec4(col, v_color.a * aa);
}`;

type GLX = WebGLRenderingContext;
interface Batch { buf: WebGLBuffer; count: number; mode: number; color: string; alpha: number; dash: number; flow: boolean }

function compile(gl: GLX, vs: string, fs: string) {
  const mk = (type: number, src: string) => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) ?? "shader");
    return s;
  };
  const p = gl.createProgram()!;
  gl.attachShader(p, mk(gl.VERTEX_SHADER, vs));
  gl.attachShader(p, mk(gl.FRAGMENT_SHADER, fs));
  gl.linkProgram(p);
  if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) ?? "link");
  return p;
}

function readPalette() {
  const cs = getComputedStyle(document.documentElement);
  const get = (v: string) => hexToRgb(cs.getPropertyValue(v) || "#808080");
  const vars = ["--ink", "--ink-2", "--line", "--line-strong", "--chart", "--magenta", "--surface", "--ok", "--amber", "--alert", "--offline"];
  return Object.fromEntries(vars.map((v) => [v, get(v)])) as Record<string, [number, number, number]>;
}

export function AgentChart({ title, subtitle, agents, levelCount, edges, calls, selected, onSelect }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const labelRefs = useRef(new Map<string, HTMLElement>());
  const reduced = useMemo(() => typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches, []);
  const [glOk, setGlOk] = useState(true);
  const [paused, setPaused] = useState(reduced);
  const [hovered, setHovered] = useState<string | null>(null);

  const positions = useMemo(() => layout(agents), [agents]);
  const outer = ringRadius(Math.max(0, levelCount - 1)) + 0.7;
  const live = useRef({ agents, edges, calls, selected, positions, outer, paused, hovered, onSelect, dirty: true });
  live.current = { ...live.current, agents, edges, calls, selected, positions, outer, paused, hovered, onSelect, dirty: true };
  const cam = useRef({ yaw: 0.55, pitch: 0.58, zoom: 1, dragging: false, moved: 0, lastX: 0, lastY: 0, touched: 0 });

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    let gl: GLX | null = null;
    try { gl = canvas.getContext("webgl", { antialias: true, premultipliedAlpha: false }) as GLX | null; } catch { gl = null; }
    if (!gl) { setGlOk(false); return; }
    const g = gl;
    let lineProg: WebGLProgram, pointProg: WebGLProgram;
    try { lineProg = compile(g, LINE_VS, LINE_FS); pointProg = compile(g, POINT_VS, POINT_FS); } catch { setGlOk(false); return; }
    const L = { pos: g.getAttribLocation(lineProg, "a_pos"), t: g.getAttribLocation(lineProg, "a_t"), mvp: g.getUniformLocation(lineProg, "u_mvp"), color: g.getUniformLocation(lineProg, "u_color"), dash: g.getUniformLocation(lineProg, "u_dash"), phase: g.getUniformLocation(lineProg, "u_phase"), fog: g.getUniformLocation(lineProg, "u_fog") };
    const P = { pos: g.getAttribLocation(pointProg, "a_pos"), size: g.getAttribLocation(pointProg, "a_size"), color: g.getAttribLocation(pointProg, "a_color"), shape: g.getAttribLocation(pointProg, "a_shape"), mvp: g.getUniformLocation(pointProg, "u_mvp"), scale: g.getUniformLocation(pointProg, "u_scale"), rim: g.getUniformLocation(pointProg, "u_rim") };
    const pointBuf = g.createBuffer()!;
    let batches: Batch[] = [];
    let palette = readPalette();
    let width = 1, height = 1, dpr = 1;

    const upload = (verts: number[]) => { const b = g.createBuffer()!; g.bindBuffer(g.ARRAY_BUFFER, b); g.bufferData(g.ARRAY_BUFFER, new Float32Array(verts), g.STATIC_DRAW); return b; };
    const pushLine = (out: number[], p: Vec3, t = 0) => out.push(p[0], p[1], p[2], t);

    const rebuild = () => {
      for (const b of batches) g.deleteBuffer(b.buf);
      batches = [];
      const s = live.current;
      const add = (verts: number[], mode: number, color: string, alpha: number, dash = 0, flow = false) => {
        if (verts.length) batches.push({ buf: upload(verts), count: verts.length / 4, mode, color, alpha, dash, flow });
      };
      // polar grid: 12 bearings
      const grid: number[] = [];
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2;
        pushLine(grid, [Math.cos(a) * 0.55, 0, Math.sin(a) * 0.55]);
        pushLine(grid, [Math.cos(a) * s.outer, -0.12 * (levelCount - 1), Math.sin(a) * s.outer]);
      }
      add(grid, g.LINES, "--line-strong", 0.55);
      // rings with ticks (major every 30 degrees)
      for (let lv = 0; lv < Math.max(1, levelCount); lv++) {
        const r = ringRadius(lv), y = -0.12 * lv, ticks: number[] = [];
        for (const off of [-0.008, 0, 0.008]) {
          const ring: number[] = [];
          for (let i = 0; i < 144; i++) { const a = (i / 144) * Math.PI * 2; pushLine(ring, [Math.cos(a) * (r + off), y, Math.sin(a) * (r + off)]); }
          add(ring, g.LINE_LOOP, "--chart", off === 0 ? 0.95 : 0.45);
        }
        for (let i = 0; i < 144; i++) {
          const a = (i / 144) * Math.PI * 2;
          if (i % 2 === 0) {
            const len = i % 12 === 0 ? 0.16 : 0.06;
            pushLine(ticks, [Math.cos(a) * r, y, Math.sin(a) * r]);
            pushLine(ticks, [Math.cos(a) * (r + len), y, Math.sin(a) * (r + len)]);
          }
        }
        add(ticks, g.LINES, "--chart", 0.8);
      }
      // compass rose at the Owner
      const rose: number[] = [];
      const o = OWNER_POS;
      for (let i = 0; i < 8; i++) {
        const a = (i / 8) * Math.PI * 2, len = i % 2 === 0 ? 0.55 : 0.28;
        pushLine(rose, [o[0], o[1], o[2]]);
        pushLine(rose, [o[0] + Math.cos(a) * len, o[1], o[2] + Math.sin(a) * len]);
      }
      add(rose, g.LINES, "--ink", 0.95);
      // allowed routes
      for (const e of s.edges) {
        const a = s.positions.get(e.from_agent_id), b = s.positions.get(e.to_agent_id);
        if (!a || !b) continue;
        const { points, t } = arc(a, b, 64);
        for (const off of [0, 0.012]) {
          const v: number[] = [];
          points.forEach((p, i) => pushLine(v, [p[0], p[1] + off, p[2]], t[i]));
          add(v, g.LINE_STRIP, "--chart", off === 0 ? 0.85 : 0.5, 22);
        }
      }
      // calls in flight (Owner calls start at the rose)
      for (const c of s.calls) {
        const a = c.from ? s.positions.get(c.from) : OWNER_POS, b = s.positions.get(c.to);
        if (!a || !b) continue;
        const { points, t } = arc(a, b, 64);
        for (const off of [-0.012, 0, 0.012]) {
          const v: number[] = [];
          points.forEach((p, i) => pushLine(v, [p[0], p[1] + off, p[2]], t[i]));
          add(v, g.LINE_STRIP, "--magenta", off === 0 ? 1 : 0.6, c.live ? 0 : 14, !c.live);
        }
      }
      live.current.dirty = false;
    };

    const resize = () => {
      const r = wrap.getBoundingClientRect();
      dpr = Math.min(2, window.devicePixelRatio || 1);
      width = Math.max(1, r.width); height = Math.max(1, r.height);
      canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(wrap);
    const mo = new MutationObserver(() => { palette = readPalette(); });
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    const mq = typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null;
    const onScheme = () => { palette = readPalette(); };
    mq?.addEventListener("change", onScheme);

    g.enable(g.BLEND);
    g.blendFunc(g.SRC_ALPHA, g.ONE_MINUS_SRC_ALPHA);

    let raf = 0, last = performance.now(), time = 0;
    let viewProj: Float32Array = new Float32Array(16);

    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const s = live.current;
      const c = cam.current;
      if (!reduced) time += dt;
      if (!s.paused && !c.dragging && now - c.touched > 3500) c.yaw += dt * 0.07;
      if (s.dirty) rebuild();

      const dist = (s.outer * 1.85 + 1.0) / c.zoom;
      const eye: Vec3 = [dist * Math.cos(c.pitch) * Math.sin(c.yaw), dist * Math.sin(c.pitch), dist * Math.cos(c.pitch) * Math.cos(c.yaw)];
      viewProj = multiply(perspective(0.72, width / height, 0.1, 200), lookAt(eye, [0, -0.15, 0], [0, 1, 0]));

      g.viewport(0, 0, canvas.width, canvas.height);
      g.clearColor(0, 0, 0, 0);
      g.clear(g.COLOR_BUFFER_BIT);

      // lines
      g.useProgram(lineProg);
      g.uniformMatrix4fv(L.mvp, false, viewProj);
      g.uniform2f(L.fog, dist - s.outer, dist + s.outer);
      g.enableVertexAttribArray(L.pos); g.enableVertexAttribArray(L.t);
      for (const b of batches) {
        const col = palette[b.color];
        g.uniform4f(L.color, col[0], col[1], col[2], b.alpha);
        g.uniform1f(L.dash, b.dash);
        g.uniform1f(L.phase, b.flow ? time * 1.6 : b.dash ? time * 0.25 : 0);
        g.bindBuffer(g.ARRAY_BUFFER, b.buf);
        g.vertexAttribPointer(L.pos, 3, g.FLOAT, false, 16, 0);
        g.vertexAttribPointer(L.t, 1, g.FLOAT, false, 16, 12);
        g.drawArrays(b.mode, 0, b.count);
      }

      // points: stations, halos, selection rings, tracers
      type Pt = { p: Vec3; size: number; col: [number, number, number]; a: number; shape: number };
      const pts: Pt[] = [];
      pts.push({ p: OWNER_POS, size: 28, col: palette["--ink"], a: 0.95, shape: 5 });
      pts.push({ p: OWNER_POS, size: 10, col: palette["--magenta"], a: 1, shape: 0 });
      for (const a of s.agents) {
        const p = s.positions.get(a.id);
        if (!p) continue;
        const col = palette[STATE_VAR[a.state] ?? "--chart"];
        const active = a.state === "busy" || a.state === "starting" || a.state === "needs_input" || a.state === "error";
        if (active) {
          const k = reduced ? 0.5 : 0.5 + 0.5 * Math.sin(time * 4 + p[0]);
          pts.push({ p, size: 62 + 22 * k, col, a: 0.32 - 0.14 * k, shape: 6 });
        }
        if (a.id === s.selected || a.id === s.hovered) pts.push({ p, size: 54, col: palette["--chart"], a: a.id === s.selected ? 0.95 : 0.5, shape: 5 });
        pts.push({ p, size: 34, col, a: a.state === "offline" ? 0.7 : 1, shape: 0 });
      }
      for (const [i, cl] of s.calls.entries()) {
        const a = cl.from ? s.positions.get(cl.from) : OWNER_POS, b = s.positions.get(cl.to);
        if (!a || !b) continue;
        const head = reduced ? 0.5 : (time * 0.45 + i * 0.37) % 1;
        for (let k = 0; k < (cl.live ? 7 : 1); k++) {
          const tt = head - k * 0.025;
          if (tt < 0) continue;
          pts.push({ p: pointOnArc(a, b, tt), size: k === 0 ? 20 : 15 - k, col: palette["--magenta"], a: k === 0 ? 1 : 0.6 - k * 0.08, shape: k === 0 ? 0 : 6 });
        }
      }
      // far to near
      const depth = (p: Vec3) => project(viewProj, p, 1, 1)?.depth ?? 0;
      pts.sort((x, y) => depth(y.p) - depth(x.p));
      const data = new Float32Array(pts.length * 9);
      pts.forEach((q, i) => data.set([q.p[0], q.p[1], q.p[2], q.size, q.col[0], q.col[1], q.col[2], q.a, q.shape], i * 9));
      g.useProgram(pointProg);
      g.uniformMatrix4fv(P.mvp, false, viewProj);
      g.uniform1f(P.scale, dpr * 6.5);
      const rim = palette["--surface"];
      g.uniform3f(P.rim, rim[0], rim[1], rim[2]);
      g.bindBuffer(g.ARRAY_BUFFER, pointBuf);
      g.bufferData(g.ARRAY_BUFFER, data, g.DYNAMIC_DRAW);
      for (const [loc, n, off] of [[P.pos, 3, 0], [P.size, 1, 12], [P.color, 4, 16], [P.shape, 1, 32]] as const) {
        g.enableVertexAttribArray(loc);
        g.vertexAttribPointer(loc, n, g.FLOAT, false, 36, off);
      }
      g.drawArrays(g.POINTS, 0, pts.length);
      for (const loc of [P.pos, P.size, P.color, P.shape]) g.disableVertexAttribArray(loc);

      // HTML labels follow their stations
      for (const [id, el] of labelRefs.current) {
        const p = id === OWNER_ID ? OWNER_POS : id.startsWith("bearing:") ? bearingPos(id, s.outer, levelCount) : s.positions.get(id);
        const q = p ? project(viewProj, p, width, height) : null;
        const out = !q || q.x < 4 || q.y < 4 || q.x > width - 4 || q.y > height - 4;
        // A station turned out of view is not a keyboard stop (AGENT-004 #2); the list below keeps it reachable.
        if (el instanceof HTMLButtonElement) { el.tabIndex = out ? -1 : 0; el.setAttribute("aria-hidden", out ? "true" : "false"); }
        if (out || !q) { el.style.transform = "translate(-9999px,-9999px)"; continue; }
        const dx = id.startsWith("bearing:") ? -10 : id === OWNER_ID ? -14 : 14;
        const dy = id.startsWith("bearing:") ? -6 : id === OWNER_ID ? 14 : -12;
        el.style.transform = `translate(${Math.round(q.x + dx)}px, ${Math.round(q.y + dy)}px)`;
        el.style.zIndex = String(1000 - Math.round(q.depth * 10));
      }
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);

    // interaction
    const pick = (x: number, y: number) => {
      let best: string | null = null, bestD = 22;
      for (const a of live.current.agents) {
        const p = live.current.positions.get(a.id);
        const q = p ? project(viewProj, p, width, height) : null;
        if (!q) continue;
        const d = Math.hypot(q.x - x, q.y - y);
        if (d < bestD) { bestD = d; best = a.id; }
      }
      return best;
    };
    const local = (e: PointerEvent | WheelEvent) => { const r = canvas.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top] as const; };
    const onDown = (e: PointerEvent) => { const c = cam.current; c.dragging = true; c.moved = 0; c.lastX = e.clientX; c.lastY = e.clientY; c.touched = performance.now(); canvas.setPointerCapture(e.pointerId); };
    const onMove = (e: PointerEvent) => {
      const c = cam.current;
      if (c.dragging) {
        const dx = e.clientX - c.lastX, dy = e.clientY - c.lastY;
        c.moved += Math.abs(dx) + Math.abs(dy);
        c.yaw -= dx * 0.008;
        c.pitch = Math.min(1.38, Math.max(0.12, c.pitch + dy * 0.006));
        c.lastX = e.clientX; c.lastY = e.clientY; c.touched = performance.now();
      } else {
        const [x, y] = local(e);
        const h = pick(x, y);
        canvas.style.cursor = h ? "pointer" : "grab";
        if (h !== live.current.hovered) setHovered(h);
      }
    };
    const onUp = (e: PointerEvent) => {
      const c = cam.current;
      c.dragging = false;
      if (c.moved < 5) { const [x, y] = local(e); const id = pick(x, y); if (id) live.current.onSelect(id); }
    };
    const onWheel = (e: WheelEvent) => { e.preventDefault(); const c = cam.current; c.zoom = Math.min(2.6, Math.max(0.55, c.zoom * (e.deltaY > 0 ? 0.92 : 1.08))); c.touched = performance.now(); };
    canvas.addEventListener("pointerdown", onDown);
    canvas.addEventListener("pointermove", onMove);
    canvas.addEventListener("pointerup", onUp);
    canvas.addEventListener("wheel", onWheel, { passive: false });

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect(); mo.disconnect(); mq?.removeEventListener("change", onScheme);
      canvas.removeEventListener("pointerdown", onDown);
      canvas.removeEventListener("pointermove", onMove);
      canvas.removeEventListener("pointerup", onUp);
      canvas.removeEventListener("wheel", onWheel);
      for (const b of batches) g.deleteBuffer(b.buf);
      g.deleteBuffer(pointBuf);
      g.deleteProgram(lineProg); g.deleteProgram(pointProg);
    };
  }, [levelCount, reduced]);

  const recenter = () => { cam.current = { ...cam.current, yaw: 0.55, pitch: 0.58, zoom: 1, touched: performance.now() }; };
  const setLabel = (id: string) => (el: HTMLElement | null) => { if (el) labelRefs.current.set(id, el); else labelRefs.current.delete(id); };

  return (
    <div className="chart" ref={wrapRef} role="group" aria-label={`Team chart for ${title}`}>
      <canvas ref={canvasRef} aria-hidden="true" />
      {glOk ? (
        <div className="chart__labels">
          {BEARINGS.map(([b]) => <span key={b} className="chart__bearing" ref={setLabel(`bearing:${b}`)}>{b}</span>)}
          <span className="chart__label" ref={setLabel(OWNER_ID)} style={{ cursor: "default" }}>You<small>owner</small></span>
          {agents.map((a) => (
            <button key={a.id} type="button" ref={setLabel(a.id)}
              className={`chart__label ${a.id === selected ? "chart__label--on" : ""}`}
              aria-label={`${a.name}, ${a.harness}, ${a.state.replace("_", " ")}`}
              onMouseEnter={() => setHovered(a.id)} onMouseLeave={() => setHovered(null)}
              onClick={() => onSelect(a.id)}>
              {a.name}<small>{a.model}</small>
            </button>
          ))}
        </div>
      ) : (
        <div className="chart__fallback">This browser has no WebGL, so the 3D chart is off. The agent list below has everything.</div>
      )}
      <div className="chart__hud">
        <div className="chart__title">Team chart<strong>{title}</strong>{subtitle ? <span>{subtitle}</span> : null}</div>
        {glOk && (
          <div className="chart__tools">
            <button type="button" className="btn btn--icon" onClick={() => { setPaused((p) => !p); cam.current.touched = 0; }} aria-label={paused ? "Turn the chart" : "Stop turning"} title={paused ? "Turn the chart" : "Stop turning"}>
              <Icon name={paused ? "play" : "pause"} size={16} />
            </button>
            <button type="button" className="btn btn--icon" onClick={recenter} aria-label="Reset view" title="Reset view"><Icon name="recenter" size={16} /></button>
          </div>
        )}
      </div>
      <div className="chart__legend" aria-label="Legend">
        <span><Glyph harness="owner" size={13} /> you</span>
        <span><i className="lamp lamp--ok" /> idle</span>
        <span><i className="lamp lamp--warn" /> busy</span>
        <span><i className="lamp lamp--bad" /> needs you</span>
        <span><i className="chart__swatch" /> call in flight</span>
        <span><i className="chart__swatch chart__swatch--route" /> allowed route</span>
      </div>
      {glOk && <div className="chart__hint">drag to turn - scroll to zoom - click a station</div>}
    </div>
  );
}

function bearingPos(id: string, outer: number, levelCount: number): Vec3 {
  const b = BEARINGS.find(([name]) => `bearing:${name}` === id);
  const a = b ? b[1] : 0;
  const r = outer + 0.25;
  return [Math.cos(a) * r, -0.12 * Math.max(0, levelCount - 1), Math.sin(a) * r];
}
