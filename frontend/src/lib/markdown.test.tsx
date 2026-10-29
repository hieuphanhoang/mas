import { render, screen } from "@testing-library/react";
import { Markdown, parseBlocks } from "./markdown";

const sample = `# \`AGENT-004\` - Backend environment

| | |
|---|---|
| **From -> To** | Opus -> Sol |
| **Status** | answered |

---

**[Opus, 2508, 0724]**

Opening comment with \`code\` and a [link](https://example.com).

\`\`\`bash
git status
\`\`\`

- one
- two
`;

test("parses headings, tables, rules, paragraphs, code and lists", () => {
  const kinds = parseBlocks(sample).map((b) => b.kind);
  expect(kinds).toEqual(["h", "table", "hr", "p", "p", "code", "list"]);
});

test("renders without emitting raw html", () => {
  render(<Markdown source={"<script>alert(1)</script> **bold** text"} />);
  expect(screen.getByText(/<script>alert\(1\)<\/script>/)).toBeInTheDocument();
  expect(screen.getByText("bold").tagName).toBe("STRONG");
  expect(document.querySelector("script")).toBeNull();
});

test("drops unsafe link schemes", () => {
  render(<Markdown source={"[x](javascript:alert(1)) [ok](https://a.b)"} />);
  expect(screen.getByText("x").tagName).toBe("SPAN");
  expect(screen.getByText("ok").tagName).toBe("A");
});
