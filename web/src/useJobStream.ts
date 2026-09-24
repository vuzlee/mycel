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

    const source = new EventSource(`/chat/${jobId}/events`);

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
 * The view follows the run, until the reader takes it back.
 *
 * A run emits dozens of events over minutes, and text arrives a token at a time. Left
 * alone the page sits where it was while the answer writes itself off the bottom of the
 * screen, and reading means dragging the scrollbar after every paragraph.
 *
 * So the bottom is followed while the reader is at the bottom. Scroll up — by any amount,
 * for any reason — and following stops at once: the step someone went back to read stays
 * where they put it, and nothing yanks them away from it. Come back to within `NEAR` of
 * the bottom and it resumes, because arriving at the end is how you say you want the end.
 *
 * That last part is what makes automatic scrolling bearable rather than hostile, and it
 * is why `stuck` is a ref and not state: it is read inside a scroll handler that fires
 * every frame, and re-rendering the thread on each one would cost more than the scroll.
 *
 * Telling the reader's scrolling apart from our own is the whole difficulty. `scrollTo`
 * fires the same `scroll` event a finger does, so without `pinning` the hook would read
 * its own correction as the reader leaving and switch itself off on the first token.
 *
 * Watched with a `ResizeObserver` as well as on scroll: while following, the content is
 * what changes, not the viewport, and a growing child fires no scroll event at all.
 */

//: How close to the bottom still counts as being at it. A line of text is ~24px, so this
//: is a couple of lines of slack — enough that a trackpad's momentum does not unstick a
//: reader who meant to stay, and small enough that stopping to read does.
const NEAR = 60;

//: What `adrift` lights the jump button for. Larger than NEAR on purpose: between the two
//: the view is not following, but the bottom is close enough that a button pointing at it
//: would be pointing at what is already on screen.
const ADRIFT = 120;

export function useFollow(): Follow {
  const node = useRef<HTMLDivElement | null>(null);
  const [adrift, setAdrift] = useState(false);
  //: Whether the view is currently following the bottom. Starts true: a thread opens at
  //: its newest turn, and a run started from the composer should be followed from its
  //: first token without anyone having to ask.
  const stuck = useRef(true);
  //: Set while we are scrolling the element ourselves, so the resulting `scroll` event is
  //: not mistaken for the reader moving away.
  const pinning = useRef(false);

  const ref = useCallback((element: HTMLDivElement | null) => {
    node.current = element;
    if (!element) return;

    const slack = (): number =>
      element.scrollHeight - element.scrollTop - element.clientHeight;

    const read = (): void => {
      const left = slack();
      setAdrift(left > ADRIFT);
      if (pinning.current) return;
      // Both directions in one line: scrolling up unsticks, arriving at the bottom
      // sticks again. The reader never has to find a control for either.
      stuck.current = left <= NEAR;
    };

    // `auto`, not `smooth`: this runs on every token, and a smooth scroll that has not
    // finished before the next one starts leaves the view permanently a few lines behind
    // the text it is following.
    const keep = (): void => {
      if (!stuck.current) return;
      pinning.current = true;
      element.scrollTop = element.scrollHeight;
      // Cleared after the browser has dispatched the scroll event this caused, which it
      // does before the next frame.
      requestAnimationFrame(() => {
        pinning.current = false;
        setAdrift(slack() > ADRIFT);
      });
    };

    element.addEventListener("scroll", read, { passive: true });
    const grows = new ResizeObserver(() => {
      keep();
      read();
    });
    for (const child of Array.from(element.children)) grows.observe(child);
    grows.observe(element);
    read();
  }, []);

  // The button says "take me to the end", which means the end from now on, not once.
  const toBottom = useCallback(() => {
    stuck.current = true;
    node.current?.scrollTo({ top: node.current.scrollHeight, behavior: "smooth" });
  }, []);

  return { ref, adrift, toBottom };
}
