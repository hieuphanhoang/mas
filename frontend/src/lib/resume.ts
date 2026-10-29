// The exact command that opens an agent's own session in a terminal, for the Owner to paste into
// PowerShell. Same session id the service resumes, so the Owner continues the agent's conversation.

export interface ResumeTarget {
  harness: string;
  sessionId: string | null;
  model: string;
  workingFolder: string | null;
}

const ps = (s: string) => `"${s.replace(/"/g, '`"')}"`;

/** Returns null when there is nothing to resume (no session yet, or a relay / planned harness). */
export function resumeCommand(t: ResumeTarget): string | null {
  if (!t.sessionId || !t.workingFolder) return null;
  const cd = `Set-Location ${ps(t.workingFolder.replace(/\//g, "\\"))}; `;
  switch (t.harness) {
    case "claude": return `${cd}claude --resume ${t.sessionId} --model ${t.model}`;
    case "codex": return `${cd}codex resume ${t.sessionId}`;
    case "opencode": return `${cd}opencode --session ${t.sessionId} --model ${t.model}`;
    default: return null;
  }
}
