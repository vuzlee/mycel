/**
 * The project, as numbers. No model call, so it answers in a request.
 *
 * Polling, not SSE. This state changes when the sync runs — every fifteen minutes, not by
 * the second — so a stream would cost a producer to save nothing.
 *
 * Seconds arrive on the wire and become man-days here: gold stores what Jira stores, and
 * the unit a person reads is a decision for the screen that shows it.
 *
 * **Scope is a badge, not a paragraph.** Some blocks are whole-project and some are the
 * window, which is invisible from the figures alone — so each carries its scope as one
 * word beside the heading. The long version lives in the API schema's field descriptions,
 * where the person who needs it is already reading.
 *
 * **Blocks tile, they do not stack.** The small ones sit three abreast and the tables take
 * the width; eight blocks in one column means scrolling past seven to reach the last, on a
 * screen with room for three.
 */

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { Dashboard as Board, Item } from "../api";
import { Unauthorized, fetchDashboard, fetchProjects } from "../api";
import { Shell } from "../components/Shell";
import { useAuth } from "../auth";

const WINDOWS = [1, 7, 14, 30];
const EVERY_MS = 30_000;

/** Jira's own working day, the same constant gold converts with. */
const SECONDS_PER_DAY = 8 * 3600;

/** The status categories Jira reduces every workflow to, in the order work moves. The
 *  lede's progress bar is drawn in this order, because a bar that fills left to right is
 *  describing a journey and the journey ends at done. */
const CATEGORIES = ["todo", "doing", "done"] as const;

/** The order the overview tiles read in: finished, moving, not started. A dashboard is
 *  opened to find out how it is going, and the answer to that is on the left. */
const OVERVIEW = ["done", "doing", "todo"] as const;

const CAPTION: Record<(typeof CATEGORIES)[number], string> = {
  todo: "to do",
  doing: "in progress",
  done: "done",
};

/** Jira's scheme, most urgent first, so the block is a ladder rather than whatever order
 *  the counts happened to arrive in. Anything the site added falls in after these. */
const PRIORITY_ORDER = ["Highest", "High", "Medium", "Low", "Lowest"];

/** Priority names get a colour by urgency, not by status: a Highest and a late ticket are
 *  different kinds of alarm and sharing one red would say they were the same. Anything the
 *  site renamed falls through to the neutral tone rather than being dropped. */
const URGENCY: Record<string, string> = {
  Highest: "late",
  High: "doing",
  Medium: "todo",
  Low: "done",
  Lowest: "done",
};

/** Weeks in the heatmap, and the fixed number of rows under them. Twelve weeks is the
 *  shortest span a rhythm shows in; seven rows because a week is how people talk about
 *  their own time, and a grid that does not line up on weekdays cannot be read for one. */
const WEEKS = 12;
const DAYS_IN_WEEK = 7;
const WEEKDAYS = ["Mon", "", "Wed", "", "Fri", "", ""];

const days = (seconds: number | null): string =>
  seconds === null ? "—" : `${(seconds / SECONDS_PER_DAY).toFixed(1)}d`;

const hours = (seconds: number): string => `${(seconds / 3600).toFixed(1)}h`;

const share = (value: number, total: number): string =>
  `${Math.round((100 * value) / Math.max(1, total))}%`;

/** "3h ago", "2d ago". A feed is read for recency, and a timestamp makes the reader do
 *  the subtraction on every row. */
function ago(stamp: string | null): string {
  if (stamp === null) return "—";
  const seconds = (Date.now() - new Date(stamp).getTime()) / 1000;
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

/** Which of the five steps a day's count sits on.
 *
 *  Against the busiest day in the grid rather than against a fixed count: one team's busy
 *  Tuesday is forty items and another's is four, and a scale that does not know which it
 *  is looking at draws one of them entirely blank. */
function step(items: number, busiest: number): number {
  if (items === 0) return 0;
  return Math.min(4, 1 + Math.floor((3 * (items - 1)) / Math.max(1, busiest)));
}

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

/** One labelled bar in a breakdown. Share of the largest row, not of the total: a set of
 *  bars where the biggest is 40% of the work leaves the block mostly empty. */
function Bar({
  label,
  value,
  peak,
  tone,
  note,
}: {
  label: string;
  value: number;
  peak: number;
  tone?: string;
  note?: string;
}) {
  return (
    <li data-status={tone} data-empty={value === 0}>
      <span className="what">{label}</span>
      <span className="track">
        <span className="fill" style={{ width: `${(value / Math.max(1, peak)) * 100}%` }} />
      </span>
      <span className="n">{value}</span>
      {note !== undefined && <span className="note">{note}</span>}
    </li>
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
        // The project lives in the URL so a board is a link someone can keep.
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

  // The heatmap's calendar, built here rather than on the server: the API sends the days
  // that had activity and this decides what a week looks like, which is a display
  // question. Memoised — a poll every thirty seconds would otherwise rebuild 84 cells.
  const weeks = useMemo(() => {
    const counted = new Map((board?.activity ?? []).map((d) => [d.day, d.items]));
    const end = new Date();
    end.setHours(12, 0, 0, 0);
    // Wind forward to the end of the current week, so the last column is this week with
    // its remaining days blank rather than a column that stops in the middle.
    end.setDate(end.getDate() + ((7 - end.getDay()) % 7));

    const columns: { day: string; items: number; future: boolean }[][] = [];
    const today = new Date().setHours(23, 59, 59, 999);
    for (let w = WEEKS - 1; w >= 0; w -= 1) {
      const column = [];
      for (let d = 0; d < DAYS_IN_WEEK; d += 1) {
        const at = new Date(end);
        at.setDate(end.getDate() - (w * DAYS_IN_WEEK + (DAYS_IN_WEEK - 1 - d)));
        const key = at.toISOString().slice(0, 10);
        column.push({ day: key, items: counted.get(key) ?? 0, future: at.getTime() > today });
      }
      columns.push(column);
    }
    return columns;
  }, [board?.activity]);

  const peak = Math.max(1, ...(board?.effort_by_day ?? []).map((d) => d.seconds));
  const all = board ? CATEGORIES.reduce((n, c) => n + (board.all_totals[c] ?? 0), 0) : 0;
  const win = `${window_} days`;

  // Every priority Jira knows, in its own order, zeroes included. A ladder missing its
  // rungs is not a ladder: "no Highest open" is one of the more useful things this block
  // can say, and dropping the row says it by saying nothing.
  const priorities = Object.entries(board?.priorities ?? {}).sort(
    ([a], [b]) =>
      (PRIORITY_ORDER.indexOf(a) + 1 || 99) - (PRIORITY_ORDER.indexOf(b) + 1 || 99),
  );
  const openWork = priorities.reduce((n, [, count]) => n + count, 0);
  const worst = Math.max(1, ...priorities.map(([, n]) => n));

  const kindPeak = Math.max(1, ...(board?.kinds ?? []).map((k) => k.items));
  const kindTotal = (board?.kinds ?? []).reduce((n, k) => n + k.items, 0);
  const busiest = Math.max(1, ...(board?.activity ?? []).map((d) => d.items));
  const touched = (board?.activity ?? []).reduce((n, d) => n + d.items, 0);

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
                scrolling, and everything below it is either the window or the project. */}
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

            <div className="grid">
              {/* Status overview. The window, and the caption is what stops it being read
                  as "this many moved into done this week". */}
              <section className="block">
                <Head label="Status overview" scope={win} />
                <div className="totals">
                  {OVERVIEW.map((category) => (
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

              {/* Priority breakdown. Unfinished only, and it says so on the face rather
                  than in the caption: a breakdown of everything would be read as backlog
                  pressure when half of it shipped last month. */}
              <section className="block">
                <Head label="Priority breakdown" count={openWork} scope="open work" />
                {priorities.length === 0 ? (
                  <p className="empty">nothing open, or this site hides priorities</p>
                ) : (
                  <ol className="breakdown">
                    {priorities.map(([name, count]) => (
                      <Bar
                        key={name}
                        label={name}
                        value={count}
                        peak={worst}
                        tone={URGENCY[name] ?? "todo"}
                        note={share(count, openWork)}
                      />
                    ))}
                  </ol>
                )}
                <p className="caption">
                  Everything <b>not done</b>, whole project. <b>None</b> is an item with no
                  priority set, which is a configuration rather than an omission.
                </p>
              </section>

              {/* Types of work. Whole project: what a team's work is made of does not
                  change because a week was quiet. */}
              <section className="block">
                <Head label="Types of work" count={kindTotal} scope="whole project" />
                {board.kinds.length === 0 ? (
                  <p className="empty">nothing has synced for this project</p>
                ) : (
                  <ol className="breakdown">
                    {board.kinds.map((kind) => (
                      <Bar
                        key={kind.kind}
                        label={kind.kind}
                        value={kind.items}
                        peak={kindPeak}
                        note={share(kind.items, kindTotal)}
                      />
                    ))}
                  </ol>
                )}
                <p className="caption">
                  Share of every item in the project. The percentages are the distribution,
                  and the bars are each type against the largest.
                </p>
              </section>

              {/* Twelve weeks of whether anything happened at all, which no other block
                  answers: every one of them is a snapshot, and a snapshot cannot show a
                  team that went quiet for a fortnight and came back. */}
              <section className="block wide">
                <Head label="Work heatmap" count={touched} scope="12 weeks" />
                <div className="heatmap">
                  <ol className="weekdays">
                    {WEEKDAYS.map((name, index) => (
                      <li key={index}>{name}</li>
                    ))}
                  </ol>
                  <ol className="weeks">
                    {weeks.map((week, index) => (
                      <li key={index}>
                        <ol>
                          {week.map((cell) => (
                            <li
                              key={cell.day}
                              data-step={cell.future ? undefined : step(cell.items, busiest)}
                              data-future={cell.future}
                              title={
                                cell.future
                                  ? cell.day
                                  : `${cell.day} · ${cell.items} item${cell.items === 1 ? "" : "s"}`
                              }
                            />
                          ))}
                        </ol>
                      </li>
                    ))}
                  </ol>
                  <div className="scale">
                    <span>less</span>
                    {[0, 1, 2, 3, 4].map((n) => (
                      <i key={n} data-step={n} />
                    ))}
                    <span>more</span>
                  </div>
                </div>
                <p className="caption">
                  One cell per day, by the day an item was last <b>touched</b> — not by
                  effort logged, so a team that ships without filling in worklogs still
                  shows. Shaded against this grid's busiest day.
                </p>
              </section>

              {/* From worklogs, not from resolution dates: Jira stamps a resolution with
                  the moment of the API call, so a back-filled project draws a false
                  curve. */}
              <section className="block">
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

              {/* Recent activity. Not windowed, and the block says so: a feed that comes
                  back empty reads as a dead project, when the truth is that the last thing
                  to happen was eight days ago and is worth naming. */}
              <section className="block wide">
                <Head label="Recent activity" scope="latest, any date" />
                {board.recent.length === 0 ? (
                  <p className="empty">nothing has moved in this project yet</p>
                ) : (
                  <ol className="feed">
                    {/* The columns are named. Four short facts in a row is exactly where a
                        reader starts guessing which is which, and the guess is free to be
                        wrong — "Unassigned" and a status both read as a state. */}
                    <li className="heading" aria-hidden="true">
                      <span className="key">issue</span>
                      <span className="title">summary</span>
                      <span className="state">status</span>
                      <span className="who">assignee</span>
                      <span className="when">updated</span>
                    </li>
                    {board.recent.map((item) => (
                      <li key={item.issue_key}>
                        <span className="key">{item.issue_key}</span>
                        <span className="title">{item.title}</span>
                        <span className="state" data-status={item.status_category}>
                          {item.status}
                        </span>
                        <span className="who">{item.assignee_name ?? "Unassigned"}</span>
                        <span className="when">{ago(item.updated_at)}</span>
                      </li>
                    ))}
                  </ol>
                )}
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
                        <th>summary</th>
                        <th className="who">assignee</th>
                        <th className="when">due</th>
                      </tr>
                    </thead>
                    <tbody>
                      {board.overdue.map((item: Item) => (
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
                <Head label="Team workload" scope={win} />
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
            </div>
          </>
        )}
      </div>
    </Shell>
  );
}
