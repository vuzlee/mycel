/**
 * The conversation: the question asked, then everything the run did about it.
 *
 * A gap marker is rendered wherever `seq` jumped. It is deliberately loud — an event this
 * page never received is exactly what a stream is supposed to make visible.
 */

import type { Item } from "../thread";
import { ThinkingBlock } from "./ThinkingBlock";
import { ToolCall } from "./ToolCall";
import { Working } from "./Working";

interface Props {
  question: string | null;
  items: Item[];
  gaps: Map<number, number>;
  liveSeq: number | null;
  failure: string | null;
  /** True until an answer or a failure is on screen — not merely until the stream shuts. */
  pending: boolean;
  /** The finished report, which does not come down the stream. */
  children?: React.ReactNode;
  /** Earlier turns of the same thread, already finished. Above the question on screen
   *  because that is the order they were asked in. */
  before?: React.ReactNode;
}

export function Thread({
  question,
  items,
  gaps,
  liveSeq,
  failure,
  pending,
  children,
  before,
}: Props) {
  const render = (list: Item[]): React.ReactNode =>
    list.map((item) => {
      const lost = gaps.get(item.seq);
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
            <div className="prose">{item.body}</div>
          </div>
        );
      case "tool":
        return <ToolCall item={item} renderChildren={render} />;
      case "mark":
        return <p className="gap">{item.label}</p>;
    }
  };

  return (
    <div className="thread">
      {before}
      {question !== null && (
        <div className="turn user">
          <div className="bubble">{question}</div>
        </div>
      )}
      <div className="turn items">{render(items)}</div>
      {pending && <Working items={items} />}
      {children}
      {failure && <p className="failure">{failure}</p>}
    </div>
  );
}
