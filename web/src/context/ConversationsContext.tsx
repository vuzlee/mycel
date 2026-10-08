/** The sidebar's history, from the server rather than this browser. */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { ConversationSummary } from "../api";
import { Unauthorized, fetchConversations, deleteConversation, pinConversation } from "../api";
import { useAuth } from "./auth";

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
  // `forget` is taken below by the conversation delete, and the auth one means something else.
  const { user, forget: dropSession } = useAuth();
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);

  const reload = useCallback(() => {
    if (!user) {
      setConversations([]);
      return;
    }
    void fetchConversations()
      .then(setConversations)
      .catch((error: unknown) => {
        if (error instanceof Unauthorized) dropSession();
      });
  }, [user, dropSession]);

  // The row leaves the list before the server confirms. A delete that has to wait for a
  // round-trip feels broken on a slow link, and the failure case is a reload away.
  const forget = useCallback(
    async (id: number): Promise<void> => {
      setConversations((current) => current.filter((conversation) => conversation.id !== id));
      await deleteConversation(id).catch(() => {
        reload();
      });
    },
    [reload],
  );

  // Flipped at once, like the delete; the server's order comes back with the reload.
  const pin = useCallback(
    async (id: number, pinned: boolean): Promise<void> => {
      setConversations((current) => current.map((t) => (t.id === id ? { ...t, pinned } : t)));
      await pinConversation(id, pinned).catch(() => {});
      reload();
    },
    [reload],
  );

  useEffect(reload, [reload]);

  return <Ctx.Provider value={{ conversations, reload, forget, pin }}>{children}</Ctx.Provider>;
}

export const useConversations = (): ConversationsValue => useContext(Ctx);
