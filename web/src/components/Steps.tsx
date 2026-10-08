/** A run, as the page shows it: the trail of what it did, then what it wrote. */

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
