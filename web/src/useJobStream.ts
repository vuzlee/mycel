/**
 * The only place that touches `EventSource`.
 *
 * Three behaviours the scratch page at `/live` proved, and that must not be lost:
 *
 *  - the browser resends `Last-Event-ID` by itself, so a dropped connection *resumes*
 *    rather than replays. Nothing here reconnects by hand; doing so would break that.
 *  - a jump in `seq` is rendered, not swallowed. A silent gap is worse than an ugly one.
 *  - `run_finished` closes the stream only at the top level: a nested one just means a
 *    sub-agent finished while the parent is still working.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { SequencedEvent, StreamState } from "./types";
import { RUN_FINISHED } from "./types";

export interface Stream {
  events: SequencedEvent[];
  /** seq of an event -> how many were lost immediately before it. */
  gaps: Map<number, number>;
  state: StreamState;
  error: string | null;
}

const EMPTY: Stream = { events: [], gaps: new Map(), state: "idle", error: null };

export function useJobStream(jobId: string | null): Stream {
  const [stream, setStream] = useState<Stream>(EMPTY);
  const lastSeq = useRef(0);

  useEffect(() => {
    if (!jobId) {
      lastSeq.current = 0;
      setStream(EMPTY);
      return;
    }

    lastSeq.current = 0;
    setStream({ ...EMPTY, state: "running", gaps: new Map() });

    const source = new EventSource(`/reports/${jobId}/events`);

    source.onmessage = (message: MessageEvent<string>) => {
      let event: SequencedEvent;
      try {
        event = JSON.parse(message.data) as SequencedEvent;
      } catch {
        return;
      }

      const lost = lastSeq.current && event.seq > lastSeq.current + 1
        ? event.seq - lastSeq.current - 1
        : 0;
      lastSeq.current = event.seq;

      setStream((previous) => {
        const gaps = lost ? new Map(previous.gaps).set(event.seq, lost) : previous.gaps;
        const done = event.type === RUN_FINISHED && !event.parent_tool_call_id;
        return {
          ...previous,
          events: [...previous.events, event],
          gaps,
          state: done ? "done" : previous.state,
          error: previous.error,
        };
      });

      if (event.type === RUN_FINISHED && !event.parent_tool_call_id) source.close();
    };

    // Fired on a dropped connection too, where the browser is already retrying. Only a
    // closed source is terminal.
    source.onerror = () => {
      setStream((previous) =>
        source.readyState === EventSource.CLOSED
          ? { ...previous, state: "error", error: "stream closed" }
          : previous,
      );
    };

    return () => source.close();
  }, [jobId]);

  return stream;
}

export interface Follow {
  ref: (node: HTMLDivElement | null) => void;
  /** True while the bottom is off screen — what the jump button is shown for. */
  adrift: boolean;
  toBottom: () => void;
}

/**
 * Follow the answer, not the work.
 *
 * A run emits dozens of events — reasoning, tool calls, a sub-agent's own loop — and
 * scrolling on each one takes the page away from whatever is being read. So the loop
 * never moves the view. `answered` does: the answer is the thing that was asked for, and
 * it lands once.
 *
 * `adrift` says the bottom is off screen, which is the only honest reason to offer a
 * jump button: with no auto-scroll, new work below the fold is otherwise invisible.
 */
export function useFollow(answered: boolean): Follow {
  const node = useRef<HTMLDivElement | null>(null);
  const [adrift, setAdrift] = useState(false);

  const ref = useCallback((element: HTMLDivElement | null) => {
    node.current = element;
    if (!element) return;
    const read = (): void => {
      const slack = element.scrollHeight - element.scrollTop - element.clientHeight;
      setAdrift(slack > 120);
    };
    element.addEventListener("scroll", read);
    read();
  }, []);

  const toBottom = useCallback(() => {
    node.current?.scrollTo({ top: node.current.scrollHeight, behavior: "smooth" });
  }, []);

  useEffect(() => {
    if (answered) toBottom();
  }, [answered, toBottom]);

  return { ref, adrift, toBottom };
}
