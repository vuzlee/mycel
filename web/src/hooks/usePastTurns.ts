import { useEffect, useState } from "react";
import type { Turn } from "../api";
import { fetchTurns } from "../api";

/** The conversation's earlier turns, and the job they were loaded for (what the scroll waits on).
 *  A null conversation keeps what is on screen: it is the moment before the run says which one. */
export function usePastTurns(conversationId: number | null, jobId: string | null) {
  const [past, setPast] = useState<Turn[]>([]);
  const [pastFor, setPastFor] = useState<string | null>(null);

  useEffect(() => {
    if (conversationId === null) {
      if (jobId !== null) setPastFor(jobId);
      return;
    }
    let live = true;
    void fetchTurns(conversationId)
      .then((turns) => {
        if (!live) return;
        setPast(turns.filter((turn) => turn.job_id !== jobId));
        setPastFor(jobId);
      })
      .catch(() => {
        // Keep the rows on screen, but settle so the scroll does not wait forever.
        if (live) setPastFor(jobId);
      });
    return () => {
      live = false;
    };
  }, [conversationId, jobId]);

  return { past, setPast, pastFor };
}
