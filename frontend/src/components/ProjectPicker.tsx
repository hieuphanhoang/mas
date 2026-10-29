import { useEffect } from "react";
import { useProjects } from "../api/queries";

/** Select among registered projects; picks the first one when nothing is selected yet. */
export function ProjectPicker({ value, onChange }: { value: string | undefined; onChange: (id: string) => void }) {
  const q = useProjects();
  const items = q.data?.items ?? [];
  useEffect(() => {
    if (!value && items.length) onChange(items[0].project_id);
  }, [value, items, onChange]);
  return (
    <label className="field field--inline">
      <span className="muted">Project</span>
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} disabled={!items.length}>
        {!items.length && <option value="">none registered</option>}
        {items.map((p) => <option key={p.project_id} value={p.project_id}>{p.name} ({p.project_id})</option>)}
      </select>
    </label>
  );
}
