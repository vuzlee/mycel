import type { Dashboard as Board } from "../../api";
import { Bar, Head } from "./Parts";
import { CAPTION, CATEGORIES, PRIORITY_ORDER, URGENCY, share } from "./format";

export function StatusOverview({ board, win }: { board: Board; win: string }) {
  return (
    <section className="block">
      <Head label="Status overview" scope={win} />
      <div className="totals">
        {CATEGORIES.map((category) => (
          <div className="total" data-status={category} key={category}>
            <b>{board.totals[category] ?? 0}</b>
            <span>{CAPTION[category]}</span>
          </div>
        ))}
      </div>
      <p className="caption">
        Counted by the status they are in <b>now</b>, not by how many moved into it — Jira dates a
        transition from the API call.
      </p>
    </section>
  );
}

export function PriorityBreakdown({ board }: { board: Board }) {
  // Zero rows stay: "no Highest open" is worth saying.
  const priorities = Object.entries(board.priorities).sort(
    ([a], [b]) => (PRIORITY_ORDER.indexOf(a) + 1 || 99) - (PRIORITY_ORDER.indexOf(b) + 1 || 99),
  );
  const openWork = priorities.reduce((n, [, count]) => n + count, 0);
  const worst = Math.max(1, ...priorities.map(([, n]) => n));
  return (
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
        Everything <b>not done</b>, whole project. <b>None</b> is an item with no priority set,
        which is a configuration rather than an omission.
      </p>
    </section>
  );
}

export function KindBreakdown({ board }: { board: Board }) {
  const kindPeak = Math.max(1, ...board.kinds.map((k) => k.items));
  const kindTotal = board.kinds.reduce((n, k) => n + k.items, 0);
  return (
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
        Share of every item in the project. The percentages are the distribution, and the bars are
        each type against the largest.
      </p>
    </section>
  );
}
