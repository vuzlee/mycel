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

  return (
    // Open while the call is out, and open when it delegated: those are the two cases
    // someone watching a run is watching *for*. A finished leaf call folds away.
    <details className="tool" open={pending || item.children.length > 0}>
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
