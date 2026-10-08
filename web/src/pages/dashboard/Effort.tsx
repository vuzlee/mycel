import { useMemo } from "react";
import type { Dashboard as Board } from "../../api";
import { Head } from "./Parts";
import { DAYS_IN_WEEK, WEEKDAYS, WEEKS, hours, step } from "./format";

type Cell = { day: string; seconds: number; future: boolean };

/** Twelve weekly columns of seven days, ending with the current week. */
function useWeeks(calendar: Board["calendar"]): Cell[][] {
  return useMemo(() => {
    const logged = new Map(calendar.map((d) => [d.day, d.seconds]));
    const end = new Date();
    end.setHours(12, 0, 0, 0);
    // Wind forward to the end of this week so the last column is whole.
    end.setDate(end.getDate() + ((7 - end.getDay()) % 7));

    const columns: Cell[][] = [];
    const today = new Date().setHours(23, 59, 59, 999);
    for (let w = WEEKS - 1; w >= 0; w -= 1) {
      const column = [];
      for (let d = 0; d < DAYS_IN_WEEK; d += 1) {
        const at = new Date(end);
        at.setDate(end.getDate() - (w * DAYS_IN_WEEK + (DAYS_IN_WEEK - 1 - d)));
        const key = at.toISOString().slice(0, 10);
        column.push({
          day: key,
          seconds: logged.get(key) ?? 0,
          future: at.getTime() > today,
        });
      }
      columns.push(column);
    }
    return columns;
  }, [calendar]);
}

/** A month name over the first column of each month only. */
function useMonths(weeks: Cell[][]): string[] {
  return useMemo(() => {
    let previous = -1;
    return weeks.map((week) => {
      const start = week[0];
      if (start === undefined) return "";
      const at = new Date(`${start.day}T12:00:00`);
      if (at.getMonth() === previous) return "";
      previous = at.getMonth();
      return at.toLocaleDateString(undefined, { month: "short" });
    });
  }, [weeks]);
}

function Heatmap({ board }: { board: Board }) {
  const weeks = useWeeks(board.calendar);
  const months = useMonths(weeks);
  const busiest = Math.max(1, ...board.calendar.map((d) => d.seconds));
  return (
    <div>
      <h3 className="sub">Hours logged · twelve weeks</h3>
      <div className="heatmap">
        <ol className="months" aria-hidden="true">
          {months.map((name, index) => (
            <li key={index}>{name}</li>
          ))}
        </ol>
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
                    data-step={cell.future ? undefined : step(cell.seconds, busiest)}
                    data-future={cell.future}
                    title={
                      cell.future
                        ? cell.day
                        : `${cell.day} · ${cell.seconds === 0 ? "nothing logged" : hours(cell.seconds)}`
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
        One cell per day, by the day the work was logged <b>for</b> — so a project filled in
        retroactively still lands on the right days. Shaded against this grid's busiest day.
      </p>
    </div>
  );
}

function WindowEffort({ board, win }: { board: Board; win: string }) {
  const peak = Math.max(1, ...board.effort_by_day.map((d) => d.seconds));
  return (
    <div>
      <h3 className="sub">Hours logged · last {win}</h3>
      {board.effort_by_day.length === 0 ? (
        <p className="empty">no effort logged in this window</p>
      ) : (
        <ol className="effort">
          {board.effort_by_day.map((day) => (
            <li key={day.day}>
              <span className="when">{day.day.slice(5)}</span>
              <span className="bar" style={{ width: `${(day.seconds / peak) * 100}%` }} />
              <span className="n">{hours(day.seconds)}</span>
            </li>
          ))}
        </ol>
      )}
      <p className="caption">
        The window's slice of the same worklogs. It measures effort <b>inside</b> the window, so it
        will not match the lifetime totals in Team workload.
      </p>
    </div>
  );
}

export function Effort({ board, win }: { board: Board; win: string }) {
  const logged = board.calendar.reduce((n, d) => n + d.seconds, 0);
  return (
    <section className="block wide effort-pair">
      <Head label="Effort logged" count={Math.round(logged / 3600)} scope="hours, 12 weeks" />
      <div className="two-up">
        <Heatmap board={board} />
        <WindowEffort board={board} win={win} />
      </div>
    </section>
  );
}
