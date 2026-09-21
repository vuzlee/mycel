/**
 * The same window as the report, as numbers. No model call, so it answers in a request.
 *
 * Polling, not SSE. This state changes when the sync runs — hourly, not by the second —
 * so a stream would cost a producer to save nothing.
 *
 * Seconds arrive on the wire and become man-days here: gold stores what Jira stores, and
 * the unit a person reads is a decision for the screen that shows it.
 *
 * **Scope is a badge, not a paragraph.** Two of this page's blocks are whole-project and
 * three are the window, which is invisible from the figures alone — so each block carries
 * its scope as one word beside the heading. The long version of why lives in the API
 * schema's field descriptions, where the person who needs it is already reading.
 *
 * **Blocks tile, they do not stack.** Five blocks in one column meant scrolling past four
 * of them to reach the fifth, on a screen with room for two side by side. Only the two
 * that are really tables — past due and per person — take the full width; the rest pair
 * up, so the whole dashboard is one screen rather than a column down the middle of one.
 */

import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Dashboard as Board } from "../api";
import { Unauthorized, fetchDashboard, fetchProjects } from "../api";
import { Shell } from "../components/Shell";
import { useAuth } from "../auth";

const WINDOWS = [1, 7, 14, 30];
const EVERY_MS = 30_000;

/** Jira's own working day, the same constant gold converts with. */
const SECONDS_PER_DAY = 8 * 3600;

/** The status categories Jira reduces every workflow to, in the order work moves. */
const CATEGORIES = ["todo", "doing", "done"] as const;
const CAPTION: Record<(typeof CATEGORIES)[number], string> = {
  todo: "to do",
  doing: "in progress",
  done: "done",
};

const days = (seconds: number | null): string =>
  seconds === null ? "—" : `${(seconds / SECONDS_PER_DAY).toFixed(1)}d`;

const hours = (seconds: number): string => `${(seconds / 3600).toFixed(1)}h`;

/** A block heading with its count and its scope. One line, so the scope is impossible to
 *  read as belonging to the block above it. */
function Head({
  label,
  count,
  scope,
  tone,
}: {
  label: string;
  count?: number;
  scope: string;
  tone?: string;
}) {
  return (
    <h2 className="label">
      <span>{label}</span>
      {count !== undefined && (
        <span className="count" data-status={tone}>
          {count}
        </span>
      )}
      <span className="scope">{scope}</span>
    </h2>
  );
}

export function Dashboard() {
  const [params, setParams] = useSearchParams();
  const { forget } = useAuth();

  const [projects, setProjects] = useState<string[] | null>(null);
  const [board, setBoard] = useState<Board | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const project = params.get("project");
  // A hand-edited `?days=` is a number this page puts straight into a fetch, so anything
  // that is not one of the offered windows falls back rather than requesting NaN days.
  const asked = Number(params.get("days"));
  const window_ = WINDOWS.includes(asked) ? asked : 7;

  useEffect(() => {
    void fetchProjects()
      .then((found) => {
        setProjects(found);
        // The project lives in the URL so a dashboard is a link someone can keep.
        if (project === null && found[0]) {
          setParams({ project: found[0], days: String(window_) }, { replace: true });
        }
      })
      .catch((error: unknown) => {
        if (error instanceof Unauthorized) forget();
        else setProjects([]);
      });
    // Only on mount: re-picking a default every time the window changes would fight the URL.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (project === null) return;
    let live = true;

    const load = (): void => {
      void fetchDashboard(project, window_)
        .then((found) => {
          if (!live) return;
          setBoard(found);
          setFailure(null);
        })
        .catch((error: unknown) => {
          if (!live) return;
          if (error instanceof Unauthorized) forget();
          else setFailure(error instanceof Error ? error.message : String(error));
        });
    };

    load();
    const timer = globalThis.setInterval(load, EVERY_MS);
    return () => {
      live = false;
      globalThis.clearInterval(timer);
    };
  }, [project, window_, forget]);

  const pick = (next: { project?: string; days?: number }): void =>
    setParams({
      project: next.project ?? project ?? "",
      days: String(next.days ?? window_),
    });

  const peak = Math.max(1, ...(board?.effort_by_day ?? []).map((d) => d.seconds));
  const all = board ? CATEGORIES.reduce((n, c) => n + (board.all_totals[c] ?? 0), 0) : 0;
  const win = `${window_} days`;

  return (
    <Shell>
      <div className="page board">
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

        {failure && <p className="failure">{failure}</p>}

        {projects?.length === 0 && (
          <p className="note">
            Nothing has synced yet. Fill the Jira variables in <code>.env</code>, then run{" "}
            <code>scripts/stack.sh sync</code>.
          </p>
        )}

        {board && (
          <>
            {/* The lede. A reader who came to ask "how far are we" is answered before
                scrolling, and everything below it is the window rather than the project. */}
            <header className="lede">
              <div className="figure">
                <b>{board.percent}%</b>
                <div className="of">
                  <span className="big">
                    {board.all_totals.done ?? 0} <i>of</i> {all} done
                  </span>
                  <span className="sub">whole project · refreshes every 30s</span>
                </div>
                {board.overdue.length > 0 && (
                  <div className="flag">
                    <b>{board.overdue.length}</b>
                    <span>past due</span>
                  </div>
                )}
              </div>
              <div className="track" role="img" aria-label={`${board.percent}% done`}>
                {CATEGORIES.map((category) => {
                  const n = board.all_totals[category] ?? 0;
                  return n === 0 ? null : (
                    <span
                      key={category}
                      className="fill"
                      data-status={category}
                      style={{ width: `${(n / Math.max(1, all)) * 100}%` }}
                      title={`${n} ${CAPTION[category]}`}
                    />
                  );
                })}
              </div>
              <div className="legend">
                {CATEGORIES.map((category) => (
                  <span key={category} data-status={category}>
                    <i />
                    {board.all_totals[category] ?? 0} {CAPTION[category]}
                  </span>
                ))}
              </div>
            </header>

            {/* Two columns where a block fits one, full width where it is a table.
                `wide` is the exception and says so. */}
            <div className="grid">
              <section className="block">
                {/* The overdue count used to sit as a fourth tile here. It does not
                    belong: these three are the window, that one is the whole project,
                    and standing them in a row said they were the same kind of number. */}
                <Head label="Work touched" scope={win} />
                <div className="totals">
                  {CATEGORIES.map((category) => (
                    <div className="total" data-status={category} key={category}>
                      <b>{board.totals[category] ?? 0}</b>
                      <span>{CAPTION[category]}</span>
                    </div>
                  ))}
                </div>
                <p className="caption">
                  Counted by the status they are in <b>now</b>, not by how many moved into
                  it — Jira dates a transition from the API call.
                </p>
              </section>

              <section className="block">
                {/* From worklogs, not from resolution dates: Jira stamps a resolution with
                    the moment of the API call, so a back-filled project draws a false
                    curve. */}
                <Head label="Effort logged" scope={win} />
                {board.effort_by_day.length === 0 ? (
                  <p className="empty">no effort logged in this window</p>
                ) : (
                  <ol className="effort">
                    {board.effort_by_day.map((day) => (
                      <li key={day.day}>
                        <span className="when">{day.day.slice(5)}</span>
                        <span
                          className="bar"
                          style={{ width: `${(day.seconds / peak) * 100}%` }}
                        />
                        <span className="n">{hours(day.seconds)}</span>
                      </li>
                    ))}
                  </ol>
                )}
                <p className="caption">
                  Dated by the day they were logged <b>for</b>. The only block measuring
                  effort <b>inside</b> the window, so it will not match spent below.
                </p>
              </section>

              {/* First among the tables, because a late ticket you have to go looking for
                  is a late ticket nobody finds. */}
              <section className="block wide">
                <Head
                  label="Past due"
                  count={board.overdue.length}
                  scope="whole project"
                  tone="late"
                />
                {board.overdue.length === 0 ? (
                  <p className="empty">nothing is past its due date</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th className="key">issue</th>
                        <th>title</th>
                        <th className="who">who</th>
                        <th className="when">due</th>
                      </tr>
                    </thead>
                    <tbody>
                      {board.overdue.map((item) => (
                        <tr key={item.issue_key}>
                          <td className="key" data-status="late">
                            {item.issue_key}
                          </td>
                          <td>{item.title}</td>
                          <td className="who">{item.assignee_name ?? "Unassigned"}</td>
                          <td className="when">
                            {item.due_at ? new Date(item.due_at).toLocaleDateString() : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>

              {/* Estimated against spent, per person. The gap is the number nobody has
                  today, and it is the reason this screen reads Jira rather than a chat. */}
              <section className="block wide">
                <Head label="Per person" scope={win} />
                {board.assignees.length === 0 ? (
                  <p className="empty">nobody has work in this window</p>
                ) : (
                  <table>
                    <thead>
                      <tr>
                        <th>person</th>
                        <th className="n">items</th>
                        <th className="n">done</th>
                        <th className="n">est</th>
                        <th className="n">spent</th>
                        <th className="n">gap</th>
                      </tr>
                    </thead>
                    <tbody>
                      {board.assignees.map((person) => (
                        <tr key={person.name}>
                          <td>{person.name}</td>
                          <td className="n">{person.items}</td>
                          <td className="n" data-status="done">
                            {person.done}
                          </td>
                          <td className="n">{days(person.estimated_seconds)}</td>
                          <td className="n">{days(person.spent_seconds)}</td>
                          <td
                            className="n"
                            data-status={person.gap_seconds > 0 ? "late" : "done"}
                          >
                            {days(person.gap_seconds)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
                <p className="caption">
                  The window picks <b>which tickets</b>; the figures are Jira's totals for
                  each ticket's whole life. <b>Gap is spent minus estimated</b> — positive
                  is over.
                </p>
              </section>

              {/* The level a plan is discussed at, which a flat list of tickets never is.
                  A bar rather than two numbers: "4 of 5" is arithmetic the reader has to
                  do on every row, and doing it five times is how a table stops being
                  read. */}
              <section className="block wide">
                <Head label="Epics" count={board.epics.length} scope="whole project" />
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
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}
