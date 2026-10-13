/** One run, watched two ways at once. */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import type { ChatResult } from "../api";
import { Unauthorized, fetchChat } from "../api";
import { buildConversation } from "../lib/buildConversation";
import type { Item } from "../lib/buildConversation";
import type { Follow } from "./useJobStream";
import { useFollow, useJobStream } from "./useJobStream";

const POLL_MS = 3000;

export interface Run {
  items: Item[];
  gaps: Map<number, number>;
  failure: string | null;
  result: ChatResult | null;
  busy: boolean;
  /** True until an answer or a failure is on screen, not merely until the stream shuts. */
  pending: boolean;
  /** Where the view is, and how to send it to the bottom. Only the reader ever does. */
  follow: Follow;
}

export function useRun(jobId: string | null): Run {
  const stream = useJobStream(jobId);
  const items = useMemo(() => buildConversation(stream.events), [stream.events]);

  // Polled until the run settles; a 401 is handled once, by the query cache.
  const polled = useQuery({
    queryKey: ["chat", jobId],
    queryFn: () => fetchChat(jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query) => {
      if (query.state.error instanceof Unauthorized) return false;
      const data = query.state.data;
      return data === undefined || data?.status === "running" ? POLL_MS : false;
    },
    // Anything but a 401 is transient while the run is live: keep polling.
    retry: false,
  });

  const result: ChatResult | null = polled.data ?? null;
  const failure =
    polled.data === null
      ? "No such run — it was never queued, or it was removed."
      : result?.status === "failed"
        ? (result.error ?? "The run failed.")
        : null;

  const busy = stream.state === "running";
  // Only measures the distance to the bottom and offers the jump. Asking scrolls the new
  // question to the top, once, in `Ask`; nothing follows the text after that.
  const follow = useFollow();

  return {
    items,
    gaps: stream.gaps,
    failure,
    result,
    busy,
    pending: jobId !== null && failure === null && result?.status !== "done",
    follow,
  };
}
