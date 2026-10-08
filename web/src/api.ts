/** Every HTTP call. The stream itself is `EventSource`, in `useJobStream`. */

import type { SequencedEvent } from "./lib/types";

export interface Accepted {
  job_id: string;
  /** The conversation this run landed in. Send it back to ask the next question into it. */
  conversation_id: number;
  status: "accepted";
}

/** `conversation_id` and `question` belong to this run, not to its conversation: a conversation's
 *  title is the question that opened it, which is the wrong caption for every later
 *  turn, and its latest job id is the wrong conversation for a link naming an earlier one. */
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

export interface ConversationSummary {
  id: number;
  /** `"chat"` for every conversation. A string rather than that one literal
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

/** One run inside a conversation, as the page replays it. `answer` is the same markdown
 *  `ChatResult.answer` carries, because it is the same stored text. */
export interface Turn {
  job_id: string;
  question: string;
  status: string;
  answer: string | null;
  spent_usd: string | null;
  error: string | null;
  /** The tool calls that turn made, in the same shape the stream sends — so a finished
   *  turn replays through `buildConversation`, not through a second builder. Null for a turn
   *  that ran before the column existed, and for one that failed. */
  steps: SequencedEvent[] | null;
  created_at: string;
}

/** One work item, as the page lists it. Seconds, because days are a display decision
 *  and this is the wire. */
export interface WorkItem {
  issue_key: string;
  /** `"chat"` for every conversation. A string rather than that one literal
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
  recent: WorkItem[];
  /** Effort logged per day over the last twelve weeks. Days with none are absent. */
  calendar: DayEffort[];
  overdue: WorkItem[];
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

/** One call to the API: JSON in, JSON out; a 401 is `Unauthorized`, any other failure throws. */
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.headers = { "content-type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 204) {
    if (!res.ok) throw new Error(await detail(res));
    return undefined as T;
  }
  return json<T>(res);
}

const get = <T>(path: string): Promise<T> => request<T>("GET", path);
const post = <T>(path: string, body?: unknown): Promise<T> => request<T>("POST", path, body);
const del = (path: string): Promise<void> => request<void>("DELETE", path);

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
export const forgotPassword = (email: string): Promise<void> =>
  post<void>("/auth/forgot", { email });

/** Spend a reset link. Every session of that account ends, this browser included. */
export const resetPassword = (token: string, newPassword: string): Promise<void> =>
  post<void>("/auth/reset", { token, new_password: newPassword });

/** Change it while signed in. Every other session ends; this one survives. */
export const changePassword = (current: string, next: string): Promise<void> =>
  post<void>("/auth/password", { current_password: current, new_password: next });

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

export const fetchGoogle = (): Promise<GoogleStatus> => get<GoogleStatus>("/auth/google");

/** Connecting is a navigation, not a call: consent happens on Google's own screen, so the
 *  browser has to actually go there. The server answers `/auth/google/start` with a
 *  redirect, and comes back to `/app/home` with the outcome in the query string. */
export function connectGoogle(): void {
  window.location.href = "/auth/google/start";
}

export const disconnectGoogle = (): Promise<void> => del("/auth/google");

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

export const fetchJira = (): Promise<JiraStatus> => get<JiraStatus>("/auth/jira");

/** A navigation, not a call: consent happens on Atlassian's own screen. */
export function connectJira(): void {
  window.location.href = "/auth/jira/start";
}

export const disconnectJira = (): Promise<void> => del("/auth/jira");

// -- work -------------------------------------------------------------------

/** The sources a person can pick for one turn. No chip means no tools at all. */
export type Chip = "knowledge" | "web" | "jira" | "calendar" | "mail";

/** 202, not 200: the server took the work and has not done it.
 *
 *  Without a conversation this opens a conversation; with one the question joins that conversation
 *  and the server sends its earlier turns to the agent along with it. */
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

export const fetchProjects = (): Promise<string[]> => get<string[]>("/projects");

export const fetchConversations = (): Promise<ConversationSummary[]> =>
  get<ConversationSummary[]>("/conversations");

/** Every run in one conversation, oldest first. What a conversation said before this tab opened it. */
export const fetchTurns = (id: number): Promise<Turn[]> =>
  get<Turn[]>(`/conversations/${id}/turns`);

/** Its runs go with it. */
export const deleteConversation = (id: number): Promise<void> => del(`/conversations/${id}`);

export const pinConversation = (id: number, pinned: boolean): Promise<void> =>
  request<void>("PUT", `/conversations/${id}/pin`, { pinned });

export const fetchDashboard = (project: string, days: number): Promise<Dashboard> =>
  get<Dashboard>(`/dashboard/${project}?days=${days}`);

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

/** What GET /documents/status sends on every change: the whole list, and whether
 *  anything is still being processed. */
export interface DocumentStatus {
  busy: boolean;
  documents: DocumentRow[];
}

export function uploadDocument(file: File): Promise<DocumentRow> {
  const body = new FormData();
  body.append("file", file);
  return post<DocumentRow>("/documents", body);
}

export const updateDocument = (
  id: number,
  patch: { enabled?: boolean; filename?: string },
): Promise<DocumentRow> => request<DocumentRow>("PATCH", `/documents/${id}`, patch);

export const deleteDocument = (id: number): Promise<void> => del(`/documents/${id}`);

export const fetchSourceUrl = (documentId: number): Promise<string> =>
  get<{ url: string }>(`/documents/${documentId}/source`).then((found) => found.url);

export const fetchPassage = (chunkId: number): Promise<Passage> =>
  get<Passage>(`/chunks/${chunkId}`);
