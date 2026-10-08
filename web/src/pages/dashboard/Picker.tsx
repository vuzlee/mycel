import { WINDOWS } from "./format";

export function Picker({
  projects,
  project,
  window_,
  pick,
}: {
  projects: string[] | null;
  project: string | null;
  window_: number;
  pick: (next: { project?: string; days?: number }) => void;
}) {
  return (
    <div className="picker">
      <label>
        <span className="label">Project</span>
        <select
          value={project ?? ""}
          disabled={projects === null || projects.length === 0}
          onChange={(event) => pick({ project: event.target.value })}
        >
          {projects === null && <option>loading…</option>}
          {projects?.length === 0 && <option value="">no projects yet</option>}
          {projects?.map((key) => (
            <option key={key} value={key}>
              {key}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span className="label">Window</span>
        <div className="windows">
          {WINDOWS.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={option === window_}
              onClick={() => pick({ days: option })}
            >
              {option}d
            </button>
          ))}
        </div>
      </label>
    </div>
  );
}
