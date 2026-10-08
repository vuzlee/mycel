import type { Dashboard as Board } from "../../api";
import { Head } from "./Parts";
import { TONE } from "./format";

/** Hidden on Kanban projects, where an empty block would read as a fault. */
export function Sprints({ board }: { board: Board }) {
  if (board.sprints.length === 0) return null;
  return (
    <section className="block wide">
      <Head label="Sprint progress" count={board.sprints.length} scope="whole project" />
      <ol className="epics">
        {board.sprints.map((sprint) => (
          <li key={sprint.sprint_id} data-status={TONE[sprint.state] ?? "todo"}>
            <div className="row">
              <span className="key">{sprint.state}</span>
              <span className="title">{sprint.name}</span>
              <span className="tally">
                {sprint.done}/{sprint.items}
              </span>
              <span className="pct">{sprint.percent}%</span>
            </div>
            <div
              className="track"
              role="img"
              aria-label={`${sprint.percent}% of ${sprint.items} done`}
            >
              <span className="fill" style={{ width: `${sprint.percent}%` }} />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function Epics({ board, window_ }: { board: Board; window_: number }) {
  return (
    <section className="block wide">
      <Head label="Epic progress" count={board.epics.length} scope="whole project" />
      {board.epics.length === 0 ? (
        <p className="empty">this project has no epics</p>
      ) : (
        <ol className="epics">
          {board.epics.map((epic) => (
            <li key={epic.issue_key} data-status={epic.status_category}>
              <div className="row">
                <span className="key">{epic.issue_key}</span>
                <span className="title">{epic.title}</span>
                <span className="tally">
                  {epic.done}/{epic.items}
                </span>
                <span className="pct">{epic.percent}%</span>
              </div>
              <div
                className="track"
                role="img"
                aria-label={`${epic.percent}% of ${epic.items} done`}
              >
                <span className="fill" style={{ width: `${epic.percent}%` }} />
              </div>
              <p className="moved">
                {epic.moved === 0
                  ? `untouched in these ${window_} days`
                  : `${epic.moved} moved · ${epic.moved_done} of them done`}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
