/** What a tool call says it is doing. */

const LABELS: Record<string, string> = {
  // Delegation. A tool that wraps an agent carries that agent's own name.
  researcher: "Asking the researcher",
  analyst: "Asking the analyst",
  summarizer: "Summarizing the project",
  summariser: "Summarizing the project", // the name in turns stored before the rename

  // Fetching — each one reaches somewhere the model cannot see.
  run_sql: "Analyzing the data",
  web_search: "Searching the web",
  read_mail: "Reading the mailbox",

  // Arithmetic. One label for all of them: a reader cannot tell a CAGR from a share of
  // total by name, and does not need to — it is one step between two fetches, and the
  // open panel says which.
  percent_change: "Doing the maths",
  absolute_change: "Doing the maths",
  percentage: "Doing the maths",
  cagr: "Doing the maths",
  share_of_total: "Doing the maths",
  summary_stats: "Doing the maths",
};

/**
 * An MCP server carries somebody else's tools under names nobody here chose, and the next
 * internal tool is not in the table either, so an unknown name is made readable rather
 * than left raw: `fetch_invoice` reads as "Running fetch invoice".
 */
export function labelFor(tool: string): string {
  return LABELS[tool] ?? `Running ${tool.replace(/_/g, " ")}`;
}
