/** Every HTTP call. The stream itself is `EventSource`, in `useJobStream`. */

import type { SequencedEvent } from "./types";

export interface Accepted {
  job_id: string;
  /** The thread this run landed in. Send it back to ask the next question into it. */
  conversation_id: number;
  status: "accepted";
}

/** `conversation_id` and `question` belong to this run, not to its thread: a thread's
 *  title is the question that opened it, which is the wrong caption for every later
 *  turn, and its latest job id is the wrong thread for a link naming an earlier one. */
export interface ChatResult {
  job_id: string;
  status: "running" | "done" | "failed";
  /** Markdown the orchestrator wrote. Null while it is still running. */
  answer: string | null;
  spent_usd: string | null;
  error: string | null;
  conversation_id: number | null;
  question: string | null;
}

export interface User {
  id: number;
  email: string;
}

export interface Thread {
  id: number;
  /** `"chat"` for every thread since batch 033. A string rather than that one literal
   *  because the column exists to grow a second kind, and a literal would make the day
   *  it does a type error instead of a new branch. */
  kind: string;
  title: string;
  created_at: string;
  job_id: string | null;
  status: string | null;
}

/** One run inside a thread, as the page replays it. `answer` is the same markdown
 *  `ChatResult.answer` carries, because it is the same stored text. */
export interface Turn {
  job_id: string;
  question: string;
  status: string;
  answer: string | null;
  spent_usd: string | null;
  error: string | null;
  /** The tool calls that turn made, in the same shape the stream sends — so a finished
   *  turn replays through `buildThread`, not through a second builder. Null for a turn
   *  that ran before the column existed, and for one that failed. */
  steps: SequencedEvent[] | null;
  created_at: string;
}

/** One work item, as the page lists it. Seconds, because days are a display decision
 *  and this is the wire. */
export interface Item {
  issue_key: string;
  /** `"chat"` for every thread since batch 033. A string rather than that one literal
   *  because the column exists to grow a second kind, and a literal would make the day
   *  it does a type error instead of a new branch. */
  kind: string;
  title: string;
  status: string;
  status_category: string;
  /** The site's own word for it, or null where Jira hides the field. Never a rank. */
  priority: string | null;
  assignee_name: string | null;
  original_estimate_seconds: number | null;
  time_spent_seconds: number | null;
  due_at: string | null;
  updated_at: string | null;
}

/** One kind of work in the project, and how much of it is finished. */
export interface Kind {
  kind: string;
  items: number;
  done: number;
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

/** One sprint and how much of it is finished. Newest first; the backlog is not here,
 *  because an item with no sprint was never planned into one. */
export interface Sprint {
  sprint_id: number;
  name: string;
  /** Jira's own word: `"active"`, `"future"` or `"closed"`. */
  state: string;
  items: number;
  done: number;
  percent: number;
}

/** One day of logged effort. The heatmap and the window chart share this shape. */
export interface DayEffort {
  day: string;
  seconds: number;
}

export interface Dashboard {
  project: string;
  since: string;
  until: string;
  /** The project finished, 0-100. Whole project, never the window. */
  percent: number;
  all_totals: Record<string, number>;
  totals: Record<string, number>;
  /** Unfinished items by priority name, whole project. Done work is left out. */
  priorities: Record<string, number>;
  kinds: Kind[];
  /** Every sprint with work in it, newest first. Empty where the site uses none. */
  sprints: Sprint[];
  /** The last items to move, newest first. Whole project, not the window. */
  recent: Item[];
  /** Effort logged per day over the last twelve weeks. Days with none are absent. */
  calendar: DayEffort[];
  overdue: Item[];
  assignees: Assignee[];
  epics: Epic[];
  effort_by_day: DayEffort[];
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

/** 202 whether or not the address has an account, so this call cannot be used to find
 *  out who is registered. 503 means the deployment has no way to send mail. */
export async function forgotPassword(email: string): Promise<void> {
  const res = await fetch("/auth/forgot", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) throw new Error(await detail(res));
}

/** Spend a reset link. Every session of that account ends, this browser included. */
export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch("/auth/reset", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (!res.ok) throw new Error(await detail(res));
}

/** Change it while signed in. Every other session ends; this one survives. */
export async function changePassword(
  current: string,
  next: string,
): Promise<void> {
  const res = await fetch("/auth/password", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ current_password: current, new_password: next }),
  });
  if (!res.ok) throw new Error(await detail(res));
}

// -- members ----------------------------------------------------------------

export interface Member {
  id: number;
  email: string;
}

export const fetchMembers = (project: string): Promise<Member[]> =>
  fetch(`/projects/${encodeURIComponent(project)}/members`).then(
    json<Member[]>,
  );

/** PUT, because granting twice asks for the same end state. */
export async function addMember(project: string, email: string): Promise<void> {
  const res = await fetch(
    `/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(email)}`,
    { method: "PUT" },
  );
  if (!res.ok) throw new Error(await detail(res));
}

export async function removeMember(
  project: string,
  email: string,
): Promise<void> {
  const res = await fetch(
    `/projects/${encodeURIComponent(project)}/members/${encodeURIComponent(email)}`,
    { method: "DELETE" },
  );
  if (!res.ok) throw new Error(await detail(res));
}

// -- work -------------------------------------------------------------------

/** 202, not 200: the server took the work and has not done it.
 *
 *  Without a conversation this opens a thread; with one the question joins that thread
 *  and the server sends its earlier turns to the agent along with it. */
export const askChat = (
  question: string,
  conversationId?: number,
): Promise<Accepted> =>
  post<Accepted>("/chat", {
    question,
    conversation_id: conversationId ?? null,
  });

/** 404 now means genuinely no such run: past its TTL the server reads the kept row. */
export async function fetchChat(jobId: string): Promise<ChatResult | null> {
  const res = await fetch(`/chat/${jobId}`);
  if (res.status === 404) return null;
  return json<ChatResult>(res);
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

export const fetchDashboard = (
  project: string,
  days: number,
): Promise<Dashboard> =>
  fetch(`/dashboard/${project}?days=${days}`).then(json<Dashboard>);
