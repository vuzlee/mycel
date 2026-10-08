import type { Dashboard as Board } from "../../api";
import { CAPTION, CATEGORIES } from "./format";

/** "How far are we", answered before scrolling. */
export function Lede({ board, all }: { board: Board; all: number }) {
  return (
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
  );
}
