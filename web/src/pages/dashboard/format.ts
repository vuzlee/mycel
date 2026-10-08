export const WINDOWS = [1, 7, 14, 30];

/** Jira's own working day, the same constant gold converts with. */
const SECONDS_PER_DAY = 8 * 3600;

/** Finished first, so every bar fills from the left and every legend reads in one order. */
export const CATEGORIES = ["done", "doing", "todo"] as const;

export const CAPTION: Record<(typeof CATEGORIES)[number], string> = {
  todo: "to do",
  doing: "in progress",
  done: "done",
};

/** Most urgent first; anything the site added falls in after these. */
export const PRIORITY_ORDER = ["Highest", "High", "Medium", "Low", "Lowest"];

/** Colored by urgency, not status: a Highest and a late ticket are different alarms. */
export const URGENCY: Record<string, string> = {
  Highest: "late",
  High: "doing",
  Medium: "todo",
  Low: "done",
  Lowest: "done",
};

/** A sprint state borrows the status palette. */
export const TONE: Record<string, string> = {
  closed: "done",
  active: "doing",
  future: "todo",
};

export const WEEKS = 12;
export const DAYS_IN_WEEK = 7;
export const WEEKDAYS = ["Mon", "", "Wed", "", "Fri", "", ""];

export const days = (seconds: number | null): string =>
  seconds === null ? "—" : `${(seconds / SECONDS_PER_DAY).toFixed(1)}d`;

export const hours = (seconds: number): string => `${(seconds / 3600).toFixed(1)}h`;

export const share = (value: number, total: number): string =>
  `${Math.round((100 * value) / Math.max(1, total))}%`;

/** "3h ago", "2d ago": a feed is read for recency. */
export function ago(stamp: string | null): string {
  if (stamp === null) return "—";
  const seconds = (Date.now() - new Date(stamp).getTime()) / 1000;
  if (seconds < 90) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86_400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86_400)}d ago`;
}

/** Heatmap step 0–4, against the grid's busiest day so any team's scale shows. */
export function step(seconds: number, busiest: number): number {
  if (seconds === 0) return 0;
  return Math.min(4, 1 + Math.floor((3 * (seconds - 1)) / Math.max(1, busiest)));
}
