/** Projects, conversations and the dashboard. */

import type { ConversationSummary, Dashboard, Turn } from "./types";
import { CONVERSATION, TURN, del, get, request, shaped } from "./client";

export const fetchProjects = (): Promise<string[]> => get<string[]>("/projects");

export const fetchConversations = (): Promise<ConversationSummary[]> =>
  get<unknown>("/conversations").then((v) =>
    shaped<ConversationSummary[]>(v, CONVERSATION, "conversation"),
  );

/** Every run in one conversation, oldest first. What a conversation said before this tab opened it. */
export const fetchTurns = (id: number): Promise<Turn[]> =>
  get<unknown>(`/conversations/${id}/turns`).then((v) => shaped<Turn[]>(v, TURN, "turn"));

/** Its runs go with it. */
export const deleteConversation = (id: number): Promise<void> => del(`/conversations/${id}`);

export const editConversation = (
  id: number,
  change: { title?: string; archived?: boolean },
): Promise<void> => request<void>("PATCH", `/conversations/${id}`, change);

export const pinConversation = (id: number, pinned: boolean): Promise<void> =>
  request<void>("PUT", `/conversations/${id}/pin`, { pinned });

export const fetchDashboard = (project: string, days: number): Promise<Dashboard> =>
  get<Dashboard>(`/dashboard/${project}?days=${days}`);
