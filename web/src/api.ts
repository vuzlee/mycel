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
  /** The passages a Knowledge answer cites. Empty for every other turn. */
  sources: SourceRef[];
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
  /** Kept at the top of the sidebar, above Recent. */
  pinned: boolean;
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

// -- google -----------------------------------------------------------------

/** Whether a Google account is attached, and which one.
 *
 *  `configured` is about the deployment, not the person: a machine with no OAuth client
 *  cannot connect anything, and the panel says so rather than offering a button that
 *  leads to an error. */
export interface GoogleStatus {
  configured: boolean;
  email: string | null;
  connected_at: string | null;
}

export const fetchGoogle = (): Promise<GoogleStatus> =>
  fetch("/auth/google").then(json<GoogleStatus>);

/** Connecting is a navigation, not a call: consent happens on Google's own screen, so the
 *  browser has to actually go there. The server answers `/auth/google/start` with a
 *  redirect, and comes back to `/app/home` with the outcome in the query string. */
export function connectGoogle(): void {
  window.location.href = "/auth/google/start";
}

export async function disconnectGoogle(): Promise<void> {
  const res = await fetch("/auth/google", { method: "DELETE" });
  if (!res.ok) throw new Error(await detail(res));
}

// -- jira -------------------------------------------------------------------

/** Whether a Jira account is attached, and whether it is the one the sync runs on.
 *
 *  `configured` is about the deployment, as the Google one is. `projects` is what Jira
 *  said this person may browse, which is exactly what Mycel shows them. */
export interface JiraStatus {
  configured: boolean;
  display_name: string | null;
  connected_at: string | null;
  projects: string[];
}

export const fetchJira = (): Promise<JiraStatus> =>
  fetch("/auth/jira").then(json<JiraStatus>);

/** A navigation, not a call: consent happens on Atlassian's own screen. */
export function connectJira(): void {
  window.location.href = "/auth/jira/start";
}

export async function disconnectJira(): Promise<void> {
  const res = await fetch("/auth/jira", { method: "DELETE" });
  if (!res.ok) throw new Error(await detail(res));
}

// -- work -------------------------------------------------------------------

/** 202, not 200: the server took the work and has not done it.
 *
 *  Without a conversation this opens a thread; with one the question joins that thread
 *  and the server sends its earlier turns to the agent along with it. */
/** The sources a person can pick for one turn. No chip means no tools at all. */
export type Chip = "knowledge" | "web" | "jira" | "calendar" | "mail";

export const askChat = (
  question: string,
  conversationId?: number,
  chips: Chip[] = [],
): Promise<Accepted> =>
  post<Accepted>("/chat", {
    question,
    conversation_id: conversationId ?? null,
    chips,
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

export async function pinThread(id: number, pinned: boolean): Promise<void> {
  const res = await fetch(`/conversations/${id}/pin`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pinned }),
  });
  if (!res.ok) throw new Error(await detail(res));
}

export const fetchDashboard = (
  project: string,
  days: number,
): Promise<Dashboard> =>
  fetch(`/dashboard/${project}?days=${days}`).then(json<Dashboard>);

// -- documents (the Knowledge chip) -------------------------------------------

/** `uploaded` and `parsing` lock the knowledge base against questions. */
export type DocumentState = "uploaded" | "parsing" | "ready" | "failed";

export interface DocumentRow {
  id: number;
  filename: string;
  mime: string;
  size: number;
  status: DocumentState;
  fail_reason: string | null;
  enabled: boolean;
  pages: number | null;
}

/** One passage an answer cites. `page` is null for DOCX and Markdown. */
export interface SourceRef {
  label: string;
  chunk_id: number;
  document_id: number;
  filename: string;
  mime: string;
  page: number | null;
  /** The last page the passage runs onto; the quote may sit there rather than on `page`. */
  page_end?: number | null;
  section: string;
  /** The words the answer cited, checked to occur in the passage. */
  quote?: string;
}

export interface Passage {
  id: number;
  document_id: number;
  filename: string;
  text: string;
  section_path: string;
  page_start: number | null;
}

export const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;

export const fetchDocuments = (): Promise<DocumentRow[]> =>
  fetch("/documents").then(json<DocumentRow[]>);

/** What GET /documents/status sends on every change: the whole list, and whether
 *  anything is still being processed. */
export interface DocumentStatus {
  busy: boolean;
  documents: DocumentRow[];
}

export async function uploadDocument(file: File): Promise<DocumentRow> {
  const body = new FormData();
  body.append("file", file);
  return fetch("/documents", { method: "POST", body }).then(
    json<DocumentRow>,
  );
}

export async function setDocumentEnabled(id: number, enabled: boolean): Promise<DocumentRow> {
  return fetch(`/documents/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ enabled }),
  }).then(json<DocumentRow>);
}

export async function renameDocument(id: number, filename: string): Promise<DocumentRow> {
  return fetch(`/documents/${id}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ filename }),
  }).then(json<DocumentRow>);
}

export async function deleteDocument(id: number): Promise<void> {
  const res = await fetch(`/documents/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await detail(res));
}

export const fetchSourceUrl = (documentId: number): Promise<string> =>
  fetch(`/documents/${documentId}/source`)
    .then(json<{ url: string }>)
    .then((found) => found.url);

export const fetchPassage = (chunkId: number): Promise<Passage> =>
  fetch(`/chunks/${chunkId}`).then(json<Passage>);
