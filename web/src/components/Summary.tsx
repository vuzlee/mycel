/**
 * The finished progress summary: a verdict, a sentence, then tables.
 *
 * Tables rather than bullet lists. Every row here has the same parts — key, title, epic,
 * who, estimate, spent, due — and a bullet list makes the reader find each one in a
 * different place on every line. Columns put them in the same place twice.
 *
 * **Seven columns, and the last three are numbers.** Estimate, spent and due are what a
 * standup argues about; leaving them out meant the table said what moved without saying
 * whether it moved on time. They sit right-aligned at the end because a column of figures
 * is compared down, not read across.
 *
 * At risk leads. The rest of a standup is a record of what happened; the late ticket is
 * the only part somebody has to do something about today, and an empty At risk table is
 * itself the answer rather than a section worth hiding.
 */

import type { Health, LoadLine, ProgressSummary, WorkLine } from "../api";

const VERDICT: Record<Health, { label: string; tone: string }> = {
  on_track: { label: "On track", tone: "done" },
  at_risk: { label: "At risk", tone: "doing" },
  off_track: { label: "Off track", tone: "late" },
};

const GROUPS = [
  { key: "at_risk", label: "At risk", tone: "late", empty: "nothing is late or over" },
  { key: "in_flight", label: "In flight", tone: "doing", empty: "nothing is underway" },
  { key: "shipped", label: "Shipped", tone: "done", empty: "nothing finished in this window" },
] as const;

function Rows({ lines, tone }: { lines: WorkLine[]; tone: string }) {
  return (
    <table className="lines">
      <thead>
        <tr>
          <th className="key">issue</th>
          <th>title</th>
          <th className="epic">epic</th>
          <th className="who">who</th>
          <th className="n">est</th>
          <th className="n spent">spent</th>
          <th className="when">due</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => (
          <tr key={line.key || line.title}>
            <td className="key">{line.key}</td>
            <td>
              <span className="title">{line.title}</span>
              {/* The note rides under the title rather than in a column of its own: it is
                  present on perhaps one row in ten, and a column that is empty most of
                  the time is a column of whitespace down the middle of the table. */}
              {line.note && (
                <span className="note" data-tone={tone}>
                  {line.note}
                </span>
              )}
            </td>
            <td className="epic">{line.epic || "—"}</td>
            <td className="who">{line.who || "Unassigned"}</td>
            <td className="n">{line.estimated || "—"}</td>
            <td className="n spent">{line.spent || "—"}</td>
            <td className="when">{line.due || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Load({ lines }: { lines: LoadLine[] }) {
  return (
    <table className="lines load">
      <thead>
        <tr>
          <th>person</th>
          <th className="n">items</th>
          <th className="n">done</th>
          <th className="n">est</th>
          <th className="n">spent</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((line) => (
          <tr key={line.person}>
            <td>
              <span className="title">{line.person}</span>
              {line.note && <span className="note">{line.note}</span>}
            </td>
            <td className="n">{line.items}</td>
            <td className="n" data-status="done">
              {line.done}
            </td>
            <td className="n">{line.estimated || "—"}</td>
            <td className="n">{line.spent || "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Summary({
  summary,
  scope,
  spent,
}: {
  summary: Partial<ProgressSummary>;
  /** Project and window, from the form that started the run. Shown when the model left
   *  `period` empty, so a report always says what it covers. */
  scope?: string | null;
  spent?: string | null;
}) {
  const verdict = VERDICT[summary.health ?? "on_track"];
  const counts = [
    { n: summary.shipped?.length ?? 0, label: "shipped", tone: "done" },
    { n: summary.in_flight?.length ?? 0, label: "in flight", tone: "doing" },
    { n: summary.at_risk?.length ?? 0, label: "at risk", tone: "late" },
  ];

  return (
    <section className="answer summary">
      {/* The lede. Everything below it is the evidence for these three lines, and a
          reader who goes no further has still been answered. */}
      <header className="lede" data-tone={verdict.tone}>
        <div className="verdict">
          <span className="dot" />
          <b>{verdict.label}</b>
          {(summary.period ?? scope) && (
            <span className="period">{summary.period ?? scope}</span>
          )}
        </div>
        {summary.headline && <p className="headline">{summary.headline}</p>}
        <div className="counts">
          {counts.map(({ n, label, tone }) => (
            <div className="count" data-tone={tone} key={label}>
              <b>{n}</b>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </header>

      {GROUPS.map(({ key, label, tone, empty }) => {
        const lines = summary[key] ?? [];
        return (
          <div className="group" key={key} data-tone={tone}>
            <div className="head">
              <span className="label">{label}</span>
              <span className="tally">{lines.length}</span>
            </div>
            {lines.length === 0 ? (
              <p className="empty">{empty}</p>
            ) : (
              <Rows lines={lines} tone={tone} />
            )}
          </div>
        );
      })}

      <div className="group" data-tone="todo">
        <div className="head">
          <span className="label">Per person</span>
          <span className="tally">{summary.load?.length ?? 0}</span>
          <span className="scope">lifetime totals</span>
        </div>
        {!summary.load || summary.load.length === 0 ? (
          <p className="empty">nobody has work in this window</p>
        ) : (
          <Load lines={summary.load} />
        )}
      </div>

      {/* Not a fifth group. This is where a truncated window declares itself, and a limit
          rendered as one more list of bullet points is a limit that gets skimmed past. */}
      {summary.notes && summary.notes.length > 0 && (
        <div className="limits">
          <span className="label">Limits of this summary</span>
          <ul>
            {summary.notes.map((note, index) => (
              <li key={index}>{note}</li>
            ))}
          </ul>
        </div>
      )}

      {spent && <p className="spend">${spent}</p>}
    </section>
  );
}
