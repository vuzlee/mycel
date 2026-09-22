/**
 * One tool call, with whatever the agent it delegated to did folded inside it.
 *
 * `result === null` means the call is still out. That is also the only honest "working"
 * indicator the stream offers: there is no event for a tool that has started.
 */

import type { Item, ToolItem } from "../thread";
import { Chevron, Spinner } from "./icons";

interface Props {
  item: ToolItem;
  renderChildren: (items: Item[]) => React.ReactNode;
}

export function ToolCall({ item, renderChildren }: Props) {
  const pending = item.result === null;

  // A call is folded, and only the reader unfolds it. It used to open itself while it was
  // out, on the grounds that a sub-agent's work is what someone watching a run is watching
  // for. But opening and folding are the run rewriting the page under the reader: a call
  // that folds above the viewport deletes its own height, the document gets shorter, and
  // the view lands at the bottom without anything having scrolled. And it bought nothing —
  // the summary row carries its own spinner, and the working line below the thread already
  // says which call is out. So `<details>` is left to itself: the run never touches it, and
  // no state here can contradict what the reader clicked.
  return (
    <details className="tool">
      <summary>
        <Chevron className="chevron" />
        <span className="name">{item.tool}</span>
        <span className="peek">{item.args || "{}"}</span>
        {pending && (
          <span className="working">
            <Spinner className="spin" size={11} />
            running
          </span>
        )}
      </summary>
      <div className="detail">
        <span className="label">Arguments</span>
        <pre>{item.args || "{}"}</pre>
        {item.result !== null && (
          <>
            <span className="label">Result</span>
            <pre>{item.result}</pre>
          </>
        )}
        {item.children.length > 0 && <div className="nested">{renderChildren(item.children)}</div>}
      </div>
    </details>
  );
}
