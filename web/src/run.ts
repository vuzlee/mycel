/**
 * One run, watched two ways at once.
 *
 * The stream says what the agent is doing; the result endpoint says what it produced.
 * Neither alone is enough — a run reopened after its stream expired has no events at all,
 * and a run that crashes leaves the stream silent, which looks exactly like a slow one.
 * The spend is only ever on the result, never on the stream.
 */

import { useEffect, useMemo, useState } from "react";
import type { ChatResult } from "./api";
import { Unauthorized, fetchChat } from "./api";
import { useAuth } from "./auth";
import { buildThread } from "./thread";
import type { Item } from "./thread";
import type { Follow } from "./useJobStream";
import { useFollow, useJobStream } from "./useJobStream";

const POLL_MS = 3000;

export interface Run {
  items: Item[];
  gaps: Map<number, number>;
  liveSeq: number | null;
  failure: string | null;
  result: ChatResult | null;
  busy: boolean;
  /** True until an answer or a failure is on screen, not merely until the stream shuts. */
  pending: boolean;
  /** Where the view is, and how to send it to the bottom. Only the reader ever does. */
  follow: Follow;
}

export function useRun(jobId: string | null): Run {
  const { forget } = useAuth();
  const [failure, setFailure] = useState<string | null>(null);
  const [result, setResult] = useState<ChatResult | null>(null);

  const stream = useJobStream(jobId);
  const items = useMemo(() => buildThread(stream.events), [stream.events]);


  useEffect(() => {
    setFailure(null);
    setResult(null);
    if (!jobId) return;

    let live = true;
    let timer = 0;

    const check = async (): Promise<void> => {
      try {
        const fetched = await fetchChat(jobId);
        if (!live) return;
        if (fetched === null) {
          setFailure("No such run — it was never queued, or it was removed.");
          window.clearInterval(timer);
          return;
        }
        setResult(fetched);
        if (fetched.status === "failed") setFailure(fetched.error ?? "The run failed.");
        if (fetched.status !== "running") window.clearInterval(timer);
      } catch (error) {
        // A dead session must stop the loop; anything else is transient and retried.
        if (error instanceof Unauthorized) {
          window.clearInterval(timer);
          forget();
        }
      }
    };

    void check();
    timer = window.setInterval(check, POLL_MS);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [jobId, forget]);

  const busy = stream.state === "running";
  // Nothing here moves the view, not even the answer: it arrives while the reader is
  // looking at the step that produced it. The jump button is the whole mechanism.
  const follow = useFollow();

  return {
    items,
    gaps: stream.gaps,
    liveSeq: busy ? (stream.events[stream.events.length - 1]?.seq ?? null) : null,
    failure,
    result,
    busy,
    pending: jobId !== null && failure === null && result?.status !== "done",
    follow,
  };
}
