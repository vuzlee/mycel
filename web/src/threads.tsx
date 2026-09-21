/**
 * The sidebar's history, from the server rather than this browser.
 *
 * It lives in a context because two pages start runs and one page lists them: a new run
 * has to show up in the rail without a reload, and the rail is not a child of either
 * page. `reload()` is what a page calls after queueing work.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Thread } from "./api";
import { Unauthorized, fetchThreads, forgetThread } from "./api";
import { useAuth } from "./auth";

interface ThreadsValue {
  threads: Thread[];
  reload: () => void;
  /** Delete one thread, and every run under it. */
  forget: (id: number) => Promise<void>;
}

const Ctx = createContext<ThreadsValue>({
  threads: [],
  reload: () => {},
  forget: async () => {},
});

export function ThreadsProvider({ children }: { children: ReactNode }) {
  // `forget` is taken below by the thread delete, and the auth one means something else.
  const { user, forget: dropSession } = useAuth();
  const [threads, setThreads] = useState<Thread[]>([]);

  const reload = useCallback(() => {
    if (!user) {
      setThreads([]);
      return;
    }
    void fetchThreads()
      .then(setThreads)
      .catch((error: unknown) => {
        if (error instanceof Unauthorized) dropSession();
      });
  }, [user, dropSession]);

  // The row leaves the list before the server confirms. A delete that has to wait for a
  // round-trip feels broken on a slow link, and the failure case is a reload away.
  const forget = useCallback(async (id: number): Promise<void> => {
    setThreads((current) => current.filter((thread) => thread.id !== id));
    await forgetThread(id).catch(() => {
      reload();
    });
  }, [reload]);

  useEffect(reload, [reload]);

  return <Ctx.Provider value={{ threads, reload, forget }}>{children}</Ctx.Provider>;
}

export const useThreads = (): ThreadsValue => useContext(Ctx);
