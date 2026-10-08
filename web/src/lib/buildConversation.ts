/** Turns a flat event list into the tree the conversation renders. */

import type { SequencedEvent } from "./types";
import {
  TEXT,
  TEXT_DELTA,
  THINKING,
  TOOL_CALLED,
  TOOL_RETURNED,
  field,
  text,
  toolCallId,
} from "./types";

export interface ProseItem {
  kind: "text" | "thinking";
  seq: number;
  agent: string;
  body: string;
}

export interface ToolItem {
  kind: "tool";
  seq: number;
  agent: string;
  tool: string;
  toolCallId: string | null;
  args: string;
  result: string | null;
  /** Events from the agent this tool call delegated to. */
  children: Item[];
}

export interface RunMarkItem {
  kind: "mark";
  seq: number;
  agent: string;
  label: string;
}

export type Item = ProseItem | ToolItem | RunMarkItem;

export function buildConversation(events: SequencedEvent[]): Item[] {
  const root: Item[] = [];
  const byToolCall = new Map<string, ToolItem>();

  const append = (event: SequencedEvent, item: Item): void => {
    const parent = event.parent_tool_call_id
      ? byToolCall.get(event.parent_tool_call_id)
      : undefined;
    (parent ? parent.children : root).push(item);
  };

  for (const event of events) {
    if (event.type === TEXT || event.type === TEXT_DELTA || event.type === THINKING) {
      // A delta is a piece of the same bubble a whole `text` would have filled, so both
      // land in one item and the reader cannot tell which model wrote in pieces.
      const kind = event.type === THINKING ? "thinking" : "text";
      const siblings = siblingsFor(event, byToolCall, root);
      const last = siblings[siblings.length - 1];
      if (last && last.kind === kind && last.agent === event.agent) {
        last.body += text(event);
        continue;
      }
      append(event, { kind, seq: event.seq, agent: event.agent, body: text(event) });
      continue;
    }

    if (event.type === TOOL_CALLED) {
      const item: ToolItem = {
        kind: "tool",
        seq: event.seq,
        agent: event.agent,
        tool: field(event, "tool"),
        toolCallId: toolCallId(event),
        args: field(event, "args"),
        result: null,
        children: [],
      };
      append(event, item);
      if (item.toolCallId) byToolCall.set(item.toolCallId, item);
      continue;
    }

    if (event.type === TOOL_RETURNED) {
      const id = toolCallId(event);
      const call = id ? byToolCall.get(id) : undefined;
      if (call) call.result = field(event, "result");
      continue;
    }

    // run_started / run_finished at the top level are the conversation's own boundaries and the
    // header shows them. Nested ones say a sub-agent began or ended, which the tool call
    // already shows. Anything else is a type this build predates — skipped, not crashed.
  }

  return root;
}

function siblingsFor(
  event: SequencedEvent,
  byToolCall: Map<string, ToolItem>,
  root: Item[],
): Item[] {
  const parent = event.parent_tool_call_id ? byToolCall.get(event.parent_tool_call_id) : undefined;
  return parent ? parent.children : root;
}
