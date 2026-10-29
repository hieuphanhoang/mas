import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ProjectEditor } from "./ProjectEditor";
import type { ProjectConfig } from "../api/types";
// Read-only use of the backend's fixture (agreed in AGENT-003): the UI must edit what the service registers.
import fixture from "../../../backend/tests/fixtures/self-project.json";

function renderEditor(onSave = vi.fn()) {
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("offline in tests"))));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ProjectEditor initial={fixture as unknown as ProjectConfig} onSave={onSave} onCancel={() => {}} saving={false} error={null} />
    </QueryClientProvider>,
  );
  return onSave;
}

afterEach(() => vi.unstubAllGlobals());

test("lists the fixture's agents and saves a normalised config", () => {
  const onSave = renderEditor();
  expect(screen.getByText("Fable")).toBeInTheDocument();
  expect(screen.getByText("Codex")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  const saved = onSave.mock.calls[0][0] as ProjectConfig;
  expect(saved.logs[0].members.sort()).toEqual(["codex", "fable"]);
  expect(saved.agents).toHaveLength(2);
});

test("call policy matrix toggles an edge", () => {
  const onSave = renderEditor();
  fireEvent.click(screen.getByRole("button", { name: "Call policy" }));
  const box = screen.getByRole("checkbox", { name: "Fable may call Codex" }) as HTMLInputElement;
  const before = box.checked;
  fireEvent.click(box);
  fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
  const edges = (onSave.mock.calls[0][0] as ProjectConfig).call_policy.allowed_edges;
  const has = edges.some((e) => e.from_agent_id === "fable" && e.to_agent_id === "codex");
  expect(has).toBe(!before);
});
