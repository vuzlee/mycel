/** How the line under an answer writes its numbers. */

/** 8.9K, 1.2M; a small count as it is. */
export function compact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(n < 10_000 ? 1 : 0)}K`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** 850ms, 3s, 1m 05s. */
export function duration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
}

/** Four decimals, since a turn often costs under a cent; "<$0.0001" rather than "$0.0000". */
export function money(usd: string): string {
  const n = Number(usd);
  if (n === 0) return "$0";
  if (n < 0.0001) return "<$0.0001";
  return `$${n.toFixed(4)}`;
}

/** 22:09 today; the date too on any other day. */
export function clock(iso: string, now: Date = new Date()): string {
  const at = new Date(iso);
  const time = at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
  return at.toDateString() === now.toDateString()
    ? time
    : `${at.toLocaleDateString([], { day: "numeric", month: "short" })} ${time}`;
}
