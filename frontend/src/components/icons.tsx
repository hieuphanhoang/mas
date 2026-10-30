// Small hand-drawn icon set (1.6px strokes on a 24px grid) and the harness glyphs.
// Glyph shapes are the same as in the 3D chart: they encode the harness, never the state.
import type { SVGProps } from "react";

const P: Record<string, string> = {
  projects: "M4 7.5 12 4l8 3.5-8 3.5-8-3.5Z M4 12l8 3.5 8-3.5 M4 16.5 12 20l8-3.5",
  agents: "M12 3v3 M12 18v3 M3 12h3 M18 12h3 M12 7.5a4.5 4.5 0 1 1 0 9 4.5 4.5 0 0 1 0-9Z M12 11v1h1",
  threads: "M5 6h14 M5 10h14 M5 14h9 M5 18h6 M17 15l3 3-3 3",
  inbox: "M4 13l2.5-7h11L20 13 M4 13v5h16v-5 M4 13h4.5l1 2h5l1-2H20",
  harness: "M9 3v5 M15 3v5 M7 8h10v3a5 5 0 0 1-10 0V8Z M12 16v5",
  sun: "M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z M12 2.5v2 M12 19.5v2 M2.5 12h2 M19.5 12h2 M5.3 5.3l1.4 1.4 M17.3 17.3l1.4 1.4 M5.3 18.7l1.4-1.4 M17.3 6.7l1.4-1.4",
  moon: "M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10Z",
  call: "M5 19 19 5 M9 5h10v10",
  chat: "M4 5h16v11H9l-5 4V5Z",
  wake: "M13 3 5 13.5h6L10 21l8-10.5h-6L13 3Z",
  stop: "M7 7h10v10H7z",
  play: "M8 5.5v13l10-6.5-10-6.5Z",
  pause: "M8 5v14 M16 5v14",
  output: "M4 5h16v14H4z M7.5 9.5 10 12l-2.5 2.5 M12 15h4.5",
  recenter: "M12 4v3 M12 17v3 M4 12h3 M17 12h3 M12 9.5a2.5 2.5 0 1 1 0 5 2.5 2.5 0 0 1 0-5Z",
  plus: "M12 5v14 M5 12h14",
  close: "M6 6l12 12 M18 6 6 18",
  check: "M5 12.5 10 17.5 19 7",
};

export type IconName = keyof typeof P;

export function Icon({ name, size = 18, ...rest }: { name: IconName; size?: number } & SVGProps<SVGSVGElement>) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" {...rest}>
      <path d={P[name]} />
    </svg>
  );
}

export type Harness = "claude" | "codex" | "opencode" | "gemini" | "relay" | "owner";

/** Chart symbols: Claude diamond, Codex square, opencode triangle, Gemini CLI hexagon, relay hollow circle. */
export function Glyph({ harness, size = 14, color = "currentColor", title }: { harness: Harness; size?: number; color?: string; title?: string }) {
  const s = size;
  const c = s / 2;
  const r = s / 2 - 1.5;
  let shape;
  switch (harness) {
    case "claude": shape = <polygon points={`${c},${c - r} ${c + r},${c} ${c},${c + r} ${c - r},${c}`} fill={color} />; break;
    case "codex": shape = <rect x={c - r * 0.8} y={c - r * 0.8} width={r * 1.6} height={r * 1.6} fill={color} />; break;
    case "opencode": shape = <polygon points={`${c},${c - r} ${c + r * 0.95},${c + r * 0.75} ${c - r * 0.95},${c + r * 0.75}`} fill={color} />; break;
    case "gemini": {
      const pts = Array.from({ length: 6 }, (_, i) => { const a = Math.PI / 6 + (i * Math.PI) / 3; return `${c + r * Math.cos(a)},${c + r * Math.sin(a)}`; }).join(" ");
      shape = <polygon points={pts} fill={color} />; break;
    }
    case "owner": shape = <g stroke={color} strokeWidth={1.4}><circle cx={c} cy={c} r={r * 0.55} fill="none" /><path d={`M${c} ${c - r}V${c + r}M${c - r} ${c}H${c + r}`} /></g>; break;
    default: shape = <circle cx={c} cy={c} r={r * 0.85} fill="none" stroke={color} strokeWidth={1.6} />;
  }
  return (
    <svg className="glyph" width={s} height={s} viewBox={`0 0 ${s} ${s}`} role={title ? "img" : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      {shape}
    </svg>
  );
}
