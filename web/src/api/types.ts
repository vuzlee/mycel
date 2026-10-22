/** Shapes the API answers with. */

import type { SequencedEvent } from "../lib/streamEvents";
import type { SourceRef } from "./documents";

export interface Accepted {
  job_id: string;
  /** The conversation this run landed in. Send it back to ask the next question into it. */
  conversation_id: number;
  status: "accepted";
}

/** `conversation_id` and `question` belong to this run, not to its conversation: a conversation's
 *  title is the question that opened it, which is the wrong caption for every later
 *  turn, and its latest job id is the wrong conversation for a link naming an earlier one. */
/** What a turn used, for the line under its answer. Null on turns from before it was kept. */
export interface TurnUsage {
  model_ref: string | null;
  model_label: string | null;
  tokens_in: number | null;
  tokens_out: number | null;
  duration_ms: number | null;
  spent_usd: string | null;
  created_at: string | null;
}

export interface ChatResult extends TurnUsage {
  job_id: string;
  status: "running" | "done" | "failed";
  /** Markdown the orchestrator wrote. Null while it is still running. */
  answer: string | null;
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
  /** Moved under Archived, out of Recent. */
  archived: boolean;
  job_id: string | null;
  status: string | null;
}

/** One run inside a conversation, as the page replays it. `answer` is the same markdown
 *  `ChatResult.answer` carries, because it is the same stored text. */
export interface Turn extends TurnUsage {
  job_id: string;
  question: string;
  status: string;
  answer: string | null;
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
