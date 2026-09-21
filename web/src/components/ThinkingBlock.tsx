/**
 * Reasoning, collapsed once the answer starts.
 *
 * Open while it is the newest thing on screen, shut afterwards: a finished run is read for
 * its answer, and a page of raw reasoning above it buries that. `<details>` rather than
 * state, so a reader who opens one keeps it open as more events arrive.
 */

import { Chevron } from "./icons";

interface Props {
  body: string;
  live: boolean;
}

export function ThinkingBlock({ body, live }: Props) {
  const words = body.trim().split(/\s+/).filter(Boolean).length;

  return (
    <details className="thinking" open={live}>
      <summary>
        <Chevron className="chevron" />
        {live ? "Thinking…" : `Thought · ${words} words`}
      </summary>
      <div className="body">{body.trim()}</div>
    </details>
  );
}
