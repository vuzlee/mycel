/**
 * Three panels off one week's data.
 *
 * This used to be a picture of the pipeline: three fake Jira rows on the left, an arrow,
 * two grey sheets on the right. It read as a diagram of the plumbing, which is the one
 * thing the page had already decided not to talk about.
 *
 * Now it is the product's own output — a donut, a bar chart and a heatmap — because a
 * reader deciding whether they want this is deciding whether they want the figures, and
 * a figure shown is worth a paragraph promising one.
 *
 * Drawn, not screenshotted: a screenshot is out of date the next time the layout moves
 * and unreadable at this size anyway. Every colour is a token — the four Jira status
 * categories and the accent — so the panels are the app's palette, not a chart library's.
 */

/** Twelve weeks of logged hours, Monday to Sunday. Small cells and a long run, because a
 *  heatmap only reads as one when there is somewhere sparse to compare the dense part to:
 *  weekends empty, a dead fortnight in the middle, a crunch at the end. */
const LOGGED = [
  [2, 5, 3, 1, 0, 0, 0],
  [4, 6, 5, 3, 1, 0, 0],
  [1, 2, 2, 0, 1, 0, 0],
  [0, 1, 0, 0, 0, 0, 0],
  [3, 6, 7, 4, 2, 0, 0],
  [5, 8, 8, 6, 3, 1, 0],
  [2, 3, 4, 2, 1, 0, 0],
  [0, 0, 1, 0, 0, 0, 0],
  [4, 7, 6, 5, 2, 0, 0],
  [6, 8, 9, 8, 5, 2, 0],
  [7, 9, 9, 7, 4, 1, 0],
  [3, 5, 4, 2, 1, 0, 0],
];

const HOURS = [
  { who: "Ada", h: 47, of: 47 },
  { who: "Grace", h: 38, of: 47 },
  { who: "Alan", h: 29, of: 47 },
  { who: "Edsger", h: 18, of: 47 },
];

/** The donut, as four arcs on one circle. `stroke-dasharray` over a fixed circumference
 *  is the whole trick — no path maths, and each arc is one number. */
/** Four steps down one violet ramp, not four colours. Green/amber/red would be a second
 *  palette on a page that has exactly one, and it would say "alarm" about a sprint that
 *  is fine. Depth carries the order instead: closed is solid, late is barely there. */
const SPLIT = [
  { label: "Done", value: 9, step: 1 },
  { label: "In flight", value: 4, step: 2 },
  { label: "To do", value: 3, step: 3 },
  { label: "Late", value: 1, step: 4 },
];

const TOTAL = SPLIT.reduce((sum, part) => sum + part.value, 0);
const C = 2 * Math.PI * 42;

export function Flow() {
  let offset = 0;

  return (
    <div className="panels" aria-label="Three panels off one week of work">
      <article className="panel">
        <header>
          <span className="kind">Where the sprint stands</span>
          <b>17 issues</b>
        </header>

        <div className="donut">
          <svg viewBox="0 0 100 100" aria-hidden>
            {SPLIT.map((part) => {
              const length = (part.value / TOTAL) * C;
              const dash = `${length} ${C - length}`;
              const rotation = (offset / TOTAL) * 360 - 90;
              offset += part.value;
              return (
                <circle
                  key={part.label}
                  cx="50"
                  cy="50"
                  r="42"
                  data-step={part.step}
                  strokeDasharray={dash}
                  style={{ rotate: `${rotation}deg` }}
                />
              );
            })}
          </svg>
          <p className="middle">
            <b>53%</b>
            done
          </p>
        </div>

        <ul className="legend">
          {SPLIT.map((part) => (
            <li key={part.label}>
              <span className="swatch" data-step={part.step} />
              {part.label}
              <b>{part.value}</b>
            </li>
          ))}
        </ul>
      </article>

      <article className="panel">
        <header>
          <span className="kind">Hours logged, this month</span>
          <b>132h</b>
        </header>

        <ul className="bars">
          {HOURS.map((row) => (
            <li key={row.who}>
              <span className="who">{row.who}</span>
              <span className="track">
                <span className="fill" style={{ width: `${(row.h / row.of) * 100}%` }} />
              </span>
              <span className="amount">{row.h}h</span>
            </li>
          ))}
        </ul>

        <p className="foot">
          Up <b>12%</b> on last month
        </p>
      </article>

      <article className="panel">
        <header>
          <span className="kind">When the work happens</span>
          <b>12 weeks</b>
        </header>

        <div className="heat">
          {LOGGED.map((week, w) => (
            <div className="week" key={w}>
              {week.map((hours, d) => (
                <span key={d} className="cell" data-level={level(hours)} title={`${hours}h`} />
              ))}
            </div>
          ))}
          <div className="scale" aria-hidden>
            <span>Less</span>
            {[0, 1, 2, 3, 4].map((n) => (
              <i key={n} className="cell" data-level={n} />
            ))}
            <span>More</span>
          </div>
        </div>

        <p className="foot">
          Midweek carries it. Weekends are <b>nobody</b>.
        </p>
      </article>
    </div>
  );
}

/** Five buckets, because a continuous scale at this size is five shades nobody can tell
 *  apart and one that reads as empty. */
function level(hours: number): number {
  if (hours === 0) return 0;
  if (hours <= 2) return 1;
  if (hours <= 4) return 2;
  if (hours <= 6) return 3;
  return 4;
}
