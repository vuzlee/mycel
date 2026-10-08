/**
 * A run, as the page shows it: the trail of what it did, then what it wrote.
 *
 * One renderer for both a live run and a finished one: a kept turn stores its steps in
 * the shape the stream sent them, so it builds the same `Item` tree and must read
 * the same way.
 *
 * The orchestrator's own text is the answer and stays outside the fold. Everything else —
 * thinking, tool calls, a sub-agent's words — is the trail.
 */

import { hideMarkers } from "../lib/citations";
import type { Item } from "../lib/buildConversation";
import { Markdown } from "./Markdown";
import { Trail } from "./Trail";

interface Props {
  items: Item[];
  /** seq of an item -> how many events were lost immediately before it. */
  gaps?: Map<number, number>;
  /** True while the run is still out. */
  live?: boolean;
}

const isAnswer = (item: Item): boolean => item.kind === "text" && item.agent === "orchestrator";

export function Steps({ items, gaps, live = false }: Props) {
  const answer = items.filter(isAnswer);
  return (
    <>
      <Trail items={items.filter((i) => !isAnswer(i))} live={live} gaps={gaps} />
      {answer.map((item) =>
        item.kind === "text" ? <Markdown key={item.seq} body={hideMarkers(item.body)} /> : null,
      )}
    </>
  );
}
