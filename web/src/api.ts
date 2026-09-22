/** Every HTTP call. The stream itself is `EventSource`, in `useJobStream`. */

export interface Accepted {
  job_id: string;
  /** The thread this run landed in. Send it back to ask the next question into it. */
  conversation_id: number;
  status: "accepted";
}

/** The orchestrator's shape. */
export interface Report {
  findings: { statement: string; sources: string[] }[];
  gaps: string[];
  /** Questions this answer made worth asking, written by the run that answered. Empty
   *  when it closed the subject — the page shows nothing rather than a generic menu. */
  follow_ups?: string[];
}

/** The window's verdict, as the model judged it. */
export type Health = "on_track" | "at_risk" | "off_track";

/** One ticket as a row. Columns rather than a sentence, so the page can align them
 *  instead of parsing the model's prose back apart. */
export interface WorkLine {
  key: string;
  title: string;
  who: string;
  epic: string;
  /** Copied off the row with its unit. Empty when the ticket carries none. */
  estimated: string;
  spent: string;
  /** The due date as the data gives it. Empty when the ticket has none. */
  due: string;
  /** Why the row matters, when it does. Empty on most shipped and in-flight rows. */
  note: string;
}

/** One person's estimated against spent, already in man-days and already computed. */
export interface LoadLine {
  person: string;
  items: number;
  done: number;
  estimated: string;
  spent: string;
  note: string;
}

/** The summariser's shape. The structure arrives with the data, so these rows are the
 *  model's judgement about it rather than its guess at what a hashtag meant. */
export interface ProgressSummary {
  period: string;
  /** The whole window in one sentence, written to be read on its own. */
  headline: string;
  health: Health;
  shipped: WorkLine[];
  in_flight: WorkLine[];
  at_risk: WorkLine[];
  load: LoadLine[];
  notes?: string[];
}

export interface ReportResult {
  job_id: string;
  status: "running" | "done" | "failed";
  report: (Partial<Report> & Partial<ProgressSummary>) | null;
  spent_usd: string | null;
  error: string | null;
}

export interface User {
  id: number;
  email: string;
}



export interface Thread {
  id: number;
  kind: "chat" | "report";
  title: string;
  created_at: string;
  job_id: string | null;
  status: string | null;
}

/** One run inside a thread, as the page replays it. `body` is the same shape
 *  `ReportResult.report` carries, because it is the same stored JSONB. */
export interface Turn {
  job_id: string;
  question: string;
  status: string;
  body: (Partial<Report> & Partial<ProgressSummary>) | null;
  spent_usd: string | null;
  error: string | null;
  created_at: string;
}

/** One work item, as the page lists it. Seconds, because days are a display decision
 *  and this is the wire. */
export interface Item {
  issue_key: string;
  kind: string;
  title: string;
  status: string;
  status_category: string;
  assignee_name: string | null;
  original_estimate_seconds: number | null;
  time_spent_seconds: number | null;
  due_at: string | null;
}

/** One person's load. `gap_seconds` is spent minus estimated: positive means over. */
export interface Assignee {
  account_id: string | null;
  name: string;
  items: number;
  done: number;
  estimated_seconds: number;
  spent_seconds: number;
  gap_seconds: number;
}

export interface Epic {
  issue_key: string;
  title: string;
  status_category: string;
  /** The epic's whole size and how much of it is finished — what `percent` is drawn from. */
  items: number;
  done: number;
  percent: number;
  /** The same epic in the chosen window. Zero means nobody touched it lately. */
  moved: number;
  moved_done: number;
}

export interface Dashboard {
  project: string;
  since: string;
  until: string;
  /** The project finished, 0-100. Whole project, never the window. */
  percent: number;
  all_totals: Record<string, number>;
  totals: Record<string, number>;
  overdue: Item[];
  assignees: Assignee[];
  epics: Epic[];
  effort_by_day: { day: string; seconds: number }[];
}

/** A 401 from any call means the session is gone, and every page reacts the same way. */
export class Unauthorized extends Error {
  constructor() {
    super("not signed in");
  }
}

async function json<T>(res: Response): Promise<T> {
  if (res.status === 401) throw new Unauthorized();
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as T;
}

/** The sentence the API wrote, if it wrote one. Every handler in `api/app.py` answers
 *  with `{error, detail, request_id}`; anything else is shown as the status and body. */
async function detail(res: Response): Promise<string> {
  const body = await res.text();
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const found = (parsed as { detail: unknown }).detail;
      if (typeof found === "string") return found;
    }
  } catch {
    // Not JSON — a proxy error page, most likely.
  }
  return `${res.status} ${body.slice(0, 300)}`;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return fetch(path, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  }).then(json<T>);
}

// -- auth -------------------------------------------------------------------

export const register = (email: string, password: string): Promise<User> =>
  post<User>("/auth/register", { email, password });

export const login = (email: string, password: string): Promise<User> =>
  post<User>("/auth/login", { email, password });

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { method: "POST" });
}

/** Who is signed in, or null. Null rather than throwing: "nobody" is a normal answer
 *  here, and it is the one question in the app where a 401 is not an error. */
export async function me(): Promise<User | null> {
  const res = await fetch("/auth/me");
  if (res.status === 401) return null;
  return json<User>(res);
}

// -- work -------------------------------------------------------------------

/** 202, not 200: the server took the work and has not done it.
 *
 *  Without a conversation this opens a thread; with one the question joins that thread
 *  and the server sends its earlier turns to the agent along with it. */
export const askReport = (question: string, conversationId?: number): Promise<Accepted> =>
  post<Accepted>("/reports", { question, conversation_id: conversationId ?? null });

export const askSummary = (project: string, days: number): Promise<Accepted> =>
  post<Accepted>("/reports/summary", { project, days });

/** 404 now means genuinely no such run: past its TTL the server reads the kept row. */
export async function fetchReport(jobId: string): Promise<ReportResult | null> {
  const res = await fetch(`/reports/${jobId}`);
  if (res.status === 404) return null;
  return json<ReportResult>(res);
}

// -- lists ------------------------------------------------------------------

export const fetchProjects = (): Promise<string[]> =>
  fetch("/projects").then(json<string[]>);

export const fetchThreads = (): Promise<Thread[]> =>
  fetch("/conversations").then(json<Thread[]>);

/** Every run in one thread, oldest first. What a thread said before this tab opened it. */
export const fetchTurns = (id: number): Promise<Turn[]> =>
  fetch(`/conversations/${id}/turns`).then(json<Turn[]>);

/** 204, no body. The runs under the thread go with it, in the database. */
export async function forgetThread(id: number): Promise<void> {
  const res = await fetch(`/conversations/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await detail(res));
}

export const fetchDashboard = (project: string, days: number): Promise<Dashboard> =>
  fetch(`/dashboard/${project}?days=${days}`).then(json<Dashboard>);
