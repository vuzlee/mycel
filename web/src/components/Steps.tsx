/**
 * Everything a run did, as a tree.
 *
 * One renderer for both a live run and a finished one: a kept turn stores its tool calls
 * in the shape the stream sent them (MYC-41), so it builds the same `Item` tree and must
 * read the same way. A second renderer here would be two things to keep in step.
 *
 * A gap marker is rendered wherever `seq` jumped. It is deliberately loud — an event the
 * page never received is exactly what a stream is supposed to make visible. A kept turn
 * has no gaps: its steps were numbered as they were stored.
 */

import type { Item } from "../thread";
import { Markdown } from "./Markdown";
import { ThinkingBlock } from "./ThinkingBlock";
import { ToolCall } from "./ToolCall";

interface Props {
  items: Item[];
  /** seq of an item -> how many events were lost immediately before it. */
  gaps?: Map<number, number>;
  /** The item still being written, so it can show as live. Null for a finished run. */
  liveSeq?: number | null;
}

export function Steps({ items, gaps, liveSeq = null }: Props) {
  const render = (list: Item[]): React.ReactNode =>
    list.map((item) => {
      const lost = gaps?.get(item.seq);
      return (
        <div key={`${item.kind}-${item.seq}`}>
          {lost && <p className="gap">— {lost} event(s) lost —</p>}
          {body(item)}
        </div>
      );
    });

  const body = (item: Item): React.ReactNode => {
    switch (item.kind) {
      case "thinking":
        return <ThinkingBlock body={item.body} live={item.seq === liveSeq} />;
      case "text":
        return (
          <div>
            {item.agent !== "orchestrator" && <div className="agent-tag">{item.agent}</div>}
            <Markdown body={item.body} />
          </div>
        );
      case "tool":
        return <ToolCall item={item} renderChildren={render} />;
      case "mark":
        return <p className="gap">{item.label}</p>;
    }
  };

  return <>{render(items)}</>;
}
