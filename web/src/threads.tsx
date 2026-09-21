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
import { Unauthorized, fetchThreads } from "./api";
import { useAuth } from "./auth";

interface ThreadsValue {
  threads: Thread[];
  reload: () => void;
}

const Ctx = createContext<ThreadsValue>({ threads: [], reload: () => {} });

export function ThreadsProvider({ children }: { children: ReactNode }) {
  const { user, forget } = useAuth();
  const [threads, setThreads] = useState<Thread[]>([]);

  const reload = useCallback(() => {
    if (!user) {
      setThreads([]);
      return;
    }
    void fetchThreads()
      .then(setThreads)
      .catch((error: unknown) => {
        if (error instanceof Unauthorized) forget();
      });
  }, [user, forget]);

  useEffect(reload, [reload]);

  return <Ctx.Provider value={{ threads, reload }}>{children}</Ctx.Provider>;
}

export const useThreads = (): ThreadsValue => useContext(Ctx);
