/** One chart in an answer: bars or a line, from labels and values the server checked. */

export interface ChartSpec {
  type: "bar" | "line";
  title: string;
  unit: string;
  labels: string[];
  values: number[];
}

/** A chart from untrusted JSON, or null when it is not the one shape the server sends. */
export function parseChart(raw: unknown): ChartSpec | null {
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Record<string, unknown>;
  const labels = Array.isArray(c.labels) ? c.labels.map(String) : [];
  const values = Array.isArray(c.values) ? c.values.map(Number) : [];
  if ((c.type !== "bar" && c.type !== "line") || labels.length < 2) return null;
  if (labels.length !== values.length || values.some((v) => !Number.isFinite(v))) return null;
  return {
    type: c.type,
    title: String(c.title ?? ""),
    unit: String(c.unit ?? ""),
    labels,
    values,
  };
}

const fmt = (v: number, unit: string): string => `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`;

export function Chart({ spec }: { spec: ChartSpec }) {
  const top = Math.max(...spec.values, 0) || 1;
  return (
    <figure className="answer-chart">
      {spec.title && <figcaption>{spec.title}</figcaption>}
      {spec.type === "bar" ? <Bars spec={spec} top={top} /> : <Line spec={spec} top={top} />}
    </figure>
  );
}

/** Horizontal bars: labels read left to right, and long ones never collide. */
function Bars({ spec, top }: { spec: ChartSpec; top: number }) {
  return (
    <ul className="chart-bars">
      {spec.labels.map((label, i) => {
        const v = spec.values[i] ?? 0;
        return (
          <li key={`${label}-${i}`}>
            <span className="name" title={label}>
              {label}
            </span>
            <span className="track">
              <span className="fill" style={{ width: `${Math.max(0, (v / top) * 100)}%` }} />
            </span>
            <span className="value">{fmt(v, spec.unit)}</span>
          </li>
        );
      })}
    </ul>
  );
}

const W = 560;
const H = 160;
const PAD = 8;

function Line({ spec, top }: { spec: ChartSpec; top: number }) {
  const n = spec.values.length;
  const x = (i: number): number => PAD + (i * (W - 2 * PAD)) / Math.max(1, n - 1);
  const y = (v: number): number => H - PAD - (v / top) * (H - 2 * PAD);
  const points = spec.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <div className="chart-line">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={spec.title}>
        <polyline points={points} />
        {spec.values.map((v, i) => (
          <circle key={i} cx={x(i)} cy={y(v)} r={3}>
            <title>{`${spec.labels[i]}: ${fmt(v, spec.unit)}`}</title>
          </circle>
        ))}
      </svg>
      <div className="axis">
        <span>{spec.labels[0]}</span>
        <span>{spec.labels[n - 1]}</span>
      </div>
    </div>
  );
}
