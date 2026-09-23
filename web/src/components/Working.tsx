/**
 * What the run is doing right now, while it is still doing it.
 *
 * The stream has no "in progress" event, so the activity is inferred: the deepest tool
 * call still waiting on a result is the innermost thing happening. Failing that the run
 * is between steps, thinking about the next one.
 */

import type { Item, ToolItem } from "../thread";
import { Mycelium } from "./icons";

interface Props {
  items: Item[];
}

export function Working({ items }: Props) {
  const call = deepestPending(items);

  return (
    <p className="working-line">
      <Mycelium className="grow" />
      <span>
        {call ? phrase(call) : "Working through it"}
        <span className="ellipsis" />
      </span>
    </p>
  );
}

/** The agents `tools/delegate.py` exposes. A tool that wraps an agent carries that
 *  agent's own name, so there is no prefix to match on — the list is the only way to
 *  tell one from an ordinary tool. */
const AGENTS = new Set(["analyst", "researcher", "summariser"]);

/**
 * A delegation reads better as the agent it woke up than as a tool being run, so
 * `researcher` becomes "Asking researcher".
 */
function phrase(call: ToolItem): string {
  if (AGENTS.has(call.tool)) return `Asking ${call.tool}`;
  return `Running ${call.tool.replace(/_/g, " ")}`;
}

/** The innermost unfinished call: the outer ones are only waiting on this one. */
function deepestPending(items: Item[]): ToolItem | null {
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item?.kind !== "tool" || item.result !== null) continue;
    return deepestPending(item.children) ?? item;
  }
  return null;
}
