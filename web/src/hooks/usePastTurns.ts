import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import type { Turn } from "../api";
import { fetchTurns } from "../api";

const NONE: Turn[] = [];

/** The conversation's earlier turns, and the job they were loaded for (what the scroll waits on).
 *  A null conversation keeps what is on screen: it is the moment before the run says which one. */
export function usePastTurns(conversationId: number | null, jobId: string | null) {
  // Cleared by "new conversation" until the next conversation id arrives.
  const [cleared, setCleared] = useState(false);
  const query = useQuery({
    // Per job: the turn before it was still queued when the last run's list was fetched.
    queryKey: ["turns", conversationId, jobId],
    queryFn: () => fetchTurns(conversationId as number),
    enabled: conversationId !== null,
    placeholderData: keepPreviousData,
  });

  const loaded = conversationId === null || query.isFetched || query.isError;
  const past =
    cleared && conversationId === null
      ? NONE
      : (query.data ?? NONE).filter((turn) => turn.job_id !== jobId);
  // Failed loads settle too, so the scroll does not wait forever.
  const pastFor = loaded && !query.isPlaceholderData ? jobId : null;

  const setPast = useCallback((next: Turn[]) => setCleared(next.length === 0), []);
  if (cleared && conversationId !== null) setCleared(false);

  return { past, setPast, pastFor };
}
