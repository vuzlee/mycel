/** A block heading with its count and scope on one line. */
export function Head({
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

/** One breakdown bar, scaled to the largest row rather than the total. */
export function Bar({
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
