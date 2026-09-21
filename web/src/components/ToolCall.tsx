/**
 * One tool call, with whatever the agent it delegated to did folded inside it.
 *
 * `result === null` means the call is still out. That is also the only honest "working"
 * indicator the stream offers: there is no event for a tool that has started.
 */

import { useEffect, useRef, useState } from "react";
import type { Item, ToolItem } from "../thread";
import { Chevron, Spinner } from "./icons";

interface Props {
  item: ToolItem;
  renderChildren: (items: Item[]) => React.ReactNode;
}

export function ToolCall({ item, renderChildren }: Props) {
  const pending = item.result === null;

  // A call is open while it is out and folds itself when it answers. It used to stay open
  // for good once it had delegated, on the grounds that a sub-agent's work is what someone
  // watching a run is watching for — true while it runs, and wrong the moment it is over:
  // a finished thread was a wall of arguments and JSON with the answer somewhere below.
  //
  // Until the reader touches it. Then it is theirs, and the run stops moving it.
  const [open, setOpen] = useState(pending);
  const touched = useRef(false);

  useEffect(() => {
    if (!touched.current) setOpen(pending);
  }, [pending]);

  return (
    <details
      className="tool"
      open={open}
      onToggle={(event) => {
        touched.current = true;
        setOpen(event.currentTarget.open);
      }}
    >
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
