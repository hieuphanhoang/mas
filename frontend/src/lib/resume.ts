// The exact command that opens an agent's own session in a terminal, for the Owner to paste into
// PowerShell. Same session id the service resumes, so the Owner continues the agent's conversation.

export interface ResumeTarget {
  harness: string;
  sessionId: string | null;
  model: string;
  workingFolder: string | null;
}

export type ResumeCommand = { command: string } | { reason: string };

/** A PowerShell literal: single quotes never expand $, $() or backticks. PowerShell also treats the
 *  curly single quotes as quote marks, so every one of them is doubled (AGENT-004, Codex P1). */
export const psLiteral = (s: string) => `'${s.replace(/['‘’‚‛]/g, "$&$&")}'`;

/** Returns null when there is nothing to resume (no session yet, or a relay / planned harness), and a
 *  reason when a session exists but a pasted command could not open it correctly. */
export function resumeCommand(t: ResumeTarget): ResumeCommand | null {
  if (!t.sessionId || !t.workingFolder) return null;
  const cd = `Set-Location -LiteralPath ${psLiteral(t.workingFolder.replace(/\//g, "\\"))}; `;
  switch (t.harness) {
    case "claude": return { command: `${cd}claude --resume ${psLiteral(t.sessionId)} --model ${psLiteral(t.model)}` };
    case "codex": return { command: `${cd}codex resume ${psLiteral(t.sessionId)}` };
    // MAS hands opencode its provider settings per run (OPENCODE_CONFIG_CONTENT); a bare command in a
    // normal terminal would not find the model (AGENT-004, Codex P2).
    case "opencode": return { reason: "An opencode session needs the provider settings MAS passes on each run, so a plain command cannot open it. Use Open in terminal." };
    default: return null;
  }
}
