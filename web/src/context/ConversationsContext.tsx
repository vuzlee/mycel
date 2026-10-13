/** The sidebar's history, from the server rather than this browser. */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext } from "react";
import type { ReactNode } from "react";
import type { ConversationSummary } from "../api";
import { fetchConversations, deleteConversation, pinConversation } from "../api";
import { useAuth } from "./auth";

const KEY = ["conversations"] as const;
const NONE: ConversationSummary[] = [];

interface ConversationsValue {
  conversations: ConversationSummary[];
  reload: () => void;
  /** Delete one conversation, and every run under it. */
  forget: (id: number) => Promise<void>;
  /** Keep one conversation above Recent, or let it go back. */
  pin: (id: number, pinned: boolean) => Promise<void>;
}

const Ctx = createContext<ConversationsValue>({
  conversations: [],
  reload: () => {},
  forget: async () => {},
  pin: async () => {},
});

export function ConversationsProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const client = useQueryClient();
  const { data: conversations = NONE } = useQuery({
    queryKey: KEY,
    queryFn: fetchConversations,
    enabled: Boolean(user),
  });
  const setConversations = useCallback(
    (change: (current: ConversationSummary[]) => ConversationSummary[]) =>
      client.setQueryData<ConversationSummary[]>(KEY, (current) => change(current ?? NONE)),
    [client],
  );
  const reload = useCallback(() => {
    void client.invalidateQueries({ queryKey: KEY });
  }, [client]);

  // The row leaves the list before the server confirms. A delete that has to wait for a
  // round-trip feels broken on a slow link, and the failure case is a reload away.
  const forget = useCallback(
    async (id: number): Promise<void> => {
      setConversations((current) => current.filter((conversation) => conversation.id !== id));
      await deleteConversation(id).catch(() => {
        reload();
      });
    },
    [reload, setConversations],
  );

  // Flipped at once, like the delete; the server's order comes back with the reload.
  const pin = useCallback(
    async (id: number, pinned: boolean): Promise<void> => {
      setConversations((current) => current.map((t) => (t.id === id ? { ...t, pinned } : t)));
      await pinConversation(id, pinned).catch(() => {});
      reload();
    },
    [reload, setConversations],
  );

  const shown = user ? conversations : NONE;
  return (
    <Ctx.Provider value={{ conversations: shown, reload, forget, pin }}>{children}</Ctx.Provider>
  );
}

export const useConversations = (): ConversationsValue => useContext(Ctx);
