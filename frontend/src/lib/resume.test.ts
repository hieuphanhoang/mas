import { psLiteral, resumeCommand } from "./resume";

const base = { sessionId: "abc-123", model: "claude-opus-5-5", workingFolder: "D:/temp/mas-levels" };

test("each harness gets its own resume command in the agent's folder", () => {
  expect(resumeCommand({ ...base, harness: "claude" })).toEqual({ command: "Set-Location -LiteralPath 'D:\\temp\\mas-levels'; claude --resume 'abc-123' --model 'claude-opus-5-5'" });
  expect(resumeCommand({ ...base, harness: "codex", model: "gpt-6-astra" })).toEqual({ command: "Set-Location -LiteralPath 'D:\\temp\\mas-levels'; codex resume 'abc-123'" });
});

test("opencode gets a reason instead of a command that would miss its provider settings", () => {
  const r = resumeCommand({ ...base, harness: "opencode", model: "ollama/qwen3.5:latest" });
  expect(r && "reason" in r).toBe(true);
});

test("nothing to resume without a session, a folder, or for a relay", () => {
  expect(resumeCommand({ ...base, harness: "claude", sessionId: null })).toBeNull();
  expect(resumeCommand({ ...base, harness: "claude", workingFolder: null })).toBeNull();
  expect(resumeCommand({ ...base, harness: "relay" })).toBeNull();
});

test("folder and model are literal text, never PowerShell code", () => {
  const r = resumeCommand({ ...base, harness: "claude", workingFolder: "D:/temp/$(1+1)/[a]", model: "x; Write-Output INJECTED" });
  expect(r).toEqual({ command: "Set-Location -LiteralPath 'D:\\temp\\$(1+1)\\[a]'; claude --resume 'abc-123' --model 'x; Write-Output INJECTED'" });
  expect(psLiteral("it's")).toBe("'it''s'");
  expect(psLiteral("a\u2019b")).toBe("'a\u2019\u2019b'");
  expect(psLiteral("`$x")).toBe("'`$x'");
});
