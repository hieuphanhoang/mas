// A deliberately small markdown renderer for .handoff thread files (headings, paragraphs,
// bold/italic/code spans, links, fenced code, tables, lists, horizontal rules). It never emits
// raw HTML from the source: everything goes through React text nodes, so a thread written by
// another agent cannot inject markup (contract: "render markdown as untrusted content").
import type { ReactNode } from "react";

type Block =
  | { kind: "h"; level: number; text: string }
  | { kind: "p"; text: string }
  | { kind: "code"; lang: string; text: string }
  | { kind: "table"; rows: string[][] }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "hr" };

export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") { i++; continue; }
    const fence = /^```\s*(\w*)/.exec(line);
    if (fence) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) buf.push(lines[i++]);
      i++;
      out.push({ kind: "code", lang: fence[1], text: buf.join("\n") });
      continue;
    }
    const h = /^(#{1,6})\s+(.*)$/.exec(line);
    if (h) { out.push({ kind: "h", level: h[1].length, text: h[2] }); i++; continue; }
    if (/^(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { out.push({ kind: "hr" }); i++; continue; }
    if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) rows.push(cells);
        i++;
      }
      out.push({ kind: "table", rows });
      continue;
    }
    const li = /^(\s*)([-*]|\d+[.)])\s+/.exec(line);
    if (li) {
      const ordered = /\d/.test(li[2]);
      const items: string[] = [];
      while (i < lines.length) {
        const m = /^(\s*)([-*]|\d+[.)])\s+(.*)$/.exec(lines[i]);
        if (m) { items.push(m[3]); i++; continue; }
        if (/^\s{2,}\S/.test(lines[i]) && items.length) { items[items.length - 1] += " " + lines[i].trim(); i++; continue; }
        break;
      }
      out.push({ kind: "list", ordered, items });
      continue;
    }
    const buf: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !/^(#{1,6}\s|```|\||\s*([-*]|\d+[.)])\s)/.test(lines[i])) buf.push(lines[i++]);
    out.push({ kind: "p", text: buf.join(" ") });
  }
  return out;
}

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)\s]+\)|_[^_]+_)/g;

export function renderInline(text: string): ReactNode[] {
  const parts = text.split(INLINE);
  return parts.map((part, idx) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={idx}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={idx}>{part.slice(1, -1)}</code>;
    if (part.startsWith("_") && part.endsWith("_") && part.length > 2) return <em key={idx}>{part.slice(1, -1)}</em>;
    const link = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(part);
    if (link) {
      const href = link[2];
      const safe = /^(https?:\/\/|\/|#)/.test(href);
      return safe ? <a key={idx} href={href} target={href.startsWith("http") ? "_blank" : undefined} rel="noreferrer">{link[1]}</a> : <span key={idx}>{link[1]}</span>;
    }
    return <span key={idx}>{part}</span>;
  });
}

export function Markdown({ source }: { source: string }) {
  const blocks = parseBlocks(source);
  return (
    <div className="md">
      {blocks.map((b, i) => {
        switch (b.kind) {
          case "h": {
            const Tag = `h${Math.min(6, b.level + 1)}` as keyof JSX.IntrinsicElements;
            return <Tag key={i} className={`md__h md__h${b.level}`}>{renderInline(b.text)}</Tag>;
          }
          case "p": return <p key={i}>{renderInline(b.text)}</p>;
          case "code": return <pre key={i} className="md__code" data-lang={b.lang}><code>{b.text}</code></pre>;
          case "hr": return <hr key={i} />;
          case "list": return b.ordered
            ? <ol key={i}>{b.items.map((t, j) => <li key={j}>{renderInline(t)}</li>)}</ol>
            : <ul key={i}>{b.items.map((t, j) => <li key={j}>{renderInline(t)}</li>)}</ul>;
          case "table": {
            const [head, ...body] = b.rows;
            return (
              <table key={i} className="md__table">
                {head && <thead><tr>{head.map((c, j) => <th key={j}>{renderInline(c)}</th>)}</tr></thead>}
                <tbody>{body.map((r, j) => <tr key={j}>{r.map((c, k) => <td key={k}>{renderInline(c)}</td>)}</tr>)}</tbody>
              </table>
            );
          }
        }
      })}
    </div>
  );
}
