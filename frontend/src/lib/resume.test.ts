import { resumeCommand } from "./resume";

const base = { sessionId: "abc-123", model: "claude-opus-5-5", workingFolder: "D:/temp/mas-levels" };

test("each harness gets its own resume command in the agent's folder", () => {
  expect(resumeCommand({ ...base, harness: "claude" })).toBe('Set-Location "D:\\temp\\mas-levels"; claude --resume abc-123 --model claude-opus-5-5');
  expect(resumeCommand({ ...base, harness: "codex", model: "gpt-6-astra" })).toBe('Set-Location "D:\\temp\\mas-levels"; codex resume abc-123');
  expect(resumeCommand({ ...base, harness: "opencode", model: "google/gemini-3.5-flash" })).toBe('Set-Location "D:\\temp\\mas-levels"; opencode --session abc-123 --model google/gemini-3.5-flash');
});

test("nothing to resume without a session, a folder, or for a relay", () => {
  expect(resumeCommand({ ...base, harness: "claude", sessionId: null })).toBeNull();
  expect(resumeCommand({ ...base, harness: "claude", workingFolder: null })).toBeNull();
  expect(resumeCommand({ ...base, harness: "relay" })).toBeNull();
});
