/** What a tool call says it is doing and what it found, in words, never its raw input. */

type Args = Record<string, unknown>;
type Describe = (args: Args) => string;

const MATHS = "Doing the maths";
const PERIODS: Record<string, string> = {
  this_week: "this week",
  last_week: "last week",
  this_month: "this month",
  last_month: "last month",
};

const LABELS: Record<string, Describe> = {
  // Delegation. A tool that wraps an agent carries that agent's own name.
  researcher: (a) => withDetail("Asking the researcher", text(a.question)),
  analyst: (a) => withDetail("Asking the analyst", text(a.question)),
  summarizer: (a) => summarizing(a),
  summariser: (a) => summarizing(a), // the name in turns stored before the rename

  // Reads of the work data. The query a model wrote is for debugging, not for the reader.
  run_sql: () => "Querying the work data",
  hours_by_person: (a) => withDetail("Hours per person", PERIODS[text(a.period)] ?? ""),
  late_items: () => "Checking overdue items",
  open_epics: () => "Checking open epics",
  rag_search: (a) => withDetail("Searching tracked work", text(a.query)),
  find_jira_user: (a) => withDetail("Looking up a person", text(a.name)),
  draft_jira_write: (a) => withDetail("Drafting a Jira change", text(a.issue_key)),
  confirm_jira_write: () => "Writing to Jira",

  // Elsewhere.
  web_search: (a) => withDetail("Searching the web", text(a.query)),
  read_mail: () => "Reading the mailbox",
  read_events: () => "Reading the calendar",
  draft_event: (a) => withDetail("Drafting an event", text(a.summary)),
  confirm_event: () => "Booking the event",

  // Arithmetic. One label for all of them: a reader cannot tell a CAGR from a share of
  // total by name, and does not need to.
  percent_change: () => MATHS,
  absolute_change: () => MATHS,
  percentage: () => MATHS,
  cagr: () => MATHS,
  share_of_total: () => MATHS,
  summary_stats: () => MATHS,

  // The structured answer an agent hands back; its content is the answer itself.
  final_result: () => "Writing up",
};

/**
 * An MCP server carries somebody else's tools under names nobody here chose, so an unknown
 * name is made readable and its input is not shown: `fetch_invoice` reads "Running fetch invoice".
 */
export function labelFor(tool: string, rawArgs = ""): string {
  const describe = LABELS[tool];
  return describe ? describe(parse(rawArgs)) : `Running ${tool.replace(/_/g, " ")}`;
}

/** What a result amounts to, for the open step: a count of rows, or nothing to add. */
export function resultSummary(result: string): string {
  const lines = result.trim().split("\n");
  if (lines.length < 2 || !lines[0]?.includes(" | ")) return "";
  if (lines[1] === "(no rows)") return "Nothing found";
  const keys = [...result.matchAll(/\b[A-Z][A-Z0-9]+-\d+\b/g)].map((m) => m[0]);
  const unique = [...new Set(keys)];
  const rows = lines.length - 1;
  const head = `${rows} row${rows === 1 ? "" : "s"}`;
  if (unique.length === 0) return head;
  const shown = unique.slice(0, 5).join(", ");
  return `${head} · ${shown}${unique.length > 5 ? "…" : ""}`;
}

function summarizing(a: Args): string {
  const project = text(a.project);
  const days = Number(a.days);
  const window = Number.isFinite(days) && days > 0 ? `last ${days} days` : "";
  return withDetail(project ? `Summarizing ${project}` : "Summarizing the project", window);
}

function withDetail(label: string, detail: string): string {
  return detail ? `${label} · ${detail}` : label;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function parse(raw: string): Args {
  try {
    const value: unknown = JSON.parse(raw);
    return value && typeof value === "object" && !Array.isArray(value) ? (value as Args) : {};
  } catch {
    return {};
  }
}
