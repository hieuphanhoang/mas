import { useCapabilities } from "../api/queries";
import type { AdapterCapability } from "../api/types";
import { Empty, ErrorNote, Loading, Pill, fmtTime } from "../components/ui";

type Level = AdapterCapability["guard_coverage"]["tool_paths"];

function levelTone(l: Level): "ok" | "warn" | "bad" | "off" {
  return l === "verified" ? "ok" : l === "partial" ? "warn" : l === "unsupported" ? "bad" : "off";
}

function availTone(a: AdapterCapability["availability"]): "ok" | "warn" | "bad" | "off" | "info" {
  return a === "available" ? "ok" : a === "manual" ? "info" : a === "planned" ? "off" : "bad";
}

const yes = (b: boolean) => (b ? "yes" : "no");

/** What each harness can do on this PC, and how far the guards actually reach. Shown as reported:
 *  "unknown" stays unknown; the page never upgrades a level the service did not verify. */
export function CapabilitiesPage() {
  const q = useCapabilities();
  return (
    <section>
      <div className="row row--between">
        <h1 className="h1">Harnesses on this PC</h1>
        {q.data && <span className="muted small">observed {fmtTime(q.data.observed_at)} - at most {q.data.global_max_parallel} agents run at once</span>}
      </div>
      <p className="muted small">Guards are workflow checks (tool paths, shell commands) plus the harness sandbox where verified. They are not isolation: an agent running as your user can still reach what your user can.</p>
      <ErrorNote error={q.error} />
      {q.isLoading && <Loading />}
      {q.data && q.data.adapters.length === 0 && <Empty>No harness reported.</Empty>}
      {q.data && q.data.adapters.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Harness</th><th>Status</th><th>Version</th><th>Modes</th><th>Resume</th><th>Live message</th><th>Attach</th><th>Stop</th><th>Tool paths</th><th>Shell</th><th>Sandbox</th></tr>
          </thead>
          <tbody>
            {q.data.adapters.map((a) => (
              <tr key={a.harness}>
                <td><strong>{a.harness}</strong>{a.reason && <div className="muted small">{a.reason}</div>}</td>
                <td><Pill tone={availTone(a.availability)}>{a.availability}</Pill></td>
                <td><code>{a.version ?? "-"}</code></td>
                <td>{a.modes.join(", ") || "-"}</td>
                <td>{yes(a.resume)}</td><td>{yes(a.live_delivery)}</td><td>{yes(a.attach)}</td><td>{yes(a.stop)}</td>
                <td><Pill tone={levelTone(a.guard_coverage.tool_paths)}>{a.guard_coverage.tool_paths}</Pill></td>
                <td><Pill tone={levelTone(a.guard_coverage.shell_commands)}>{a.guard_coverage.shell_commands}</Pill></td>
                <td><Pill tone={levelTone(a.guard_coverage.sandbox)}>{a.guard_coverage.sandbox}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {q.data && q.data.adapters.some((a) => a.guard_coverage.limitations.length) && (
        <>
          <h2 className="h2">Known limitations</h2>
          <ul>
            {q.data.adapters.flatMap((a) => a.guard_coverage.limitations.map((l, i) => <li key={`${a.harness}-${i}`}><strong>{a.harness}:</strong> {l}</li>))}
          </ul>
        </>
      )}
      {q.data && (
        <>
          <h2 className="h2">Permission profiles</h2>
          {q.data.permission_profiles.length === 0 ? <Empty>None offered.</Empty> : (
            <table className="table">
              <thead><tr><th>Harness</th><th>Profile</th><th>What it allows</th></tr></thead>
              <tbody>
                {q.data.permission_profiles.map((p) => (
                  <tr key={`${p.harness}/${p.id}`}><td>{p.harness}</td><td>{p.label} <code className="muted">{p.id}</code></td><td>{p.description}</td></tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}
