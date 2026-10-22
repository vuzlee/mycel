/** Asking: a chat turn and its result. */

import type { Accepted, ChatResult } from "./types";
import { ACCEPTED, CHAT_RESULT, json, post, shaped } from "./client";

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
  modelRef?: string,
): Promise<Accepted> =>
  post<unknown>("/chat", {
    question,
    conversation_id: conversationId ?? null,
    chips,
    model_ref: modelRef ?? null,
    // The reader's own zone: "now" and a booking mean their clock, not the server's.
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  }).then((v) => shaped<Accepted>(v, ACCEPTED, "accepted run"));

/** 404 now means genuinely no such run: past its TTL the server reads the kept row. */
export async function fetchChat(jobId: string): Promise<ChatResult | null> {
  const res = await fetch(`/chat/${jobId}`);
  if (res.status === 404) return null;
  return shaped<ChatResult>(await json<unknown>(res), CHAT_RESULT, "chat result");
}
