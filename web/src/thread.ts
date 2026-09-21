/**
 * Turns a flat event list into the tree the thread renders.
 *
 * Nesting is by `parent_tool_call_id`, never by arrival time. `next-slice.html` §05 is
 * explicit about why: ordering holds within one agent and never across two running in
 * parallel, so a flat timeline of a delegating run is a lie that reads as noise.
 *
 * Consecutive `text` and `thinking` events from the same agent are merged: a model streams
 * prose in pieces, and one bubble per piece is unreadable.
 */

import type { SequencedEvent } from "./types";
import { TEXT, THINKING, TOOL_CALLED, TOOL_RETURNED, field, text, toolCallId } from "./types";

/**
 * pydantic-ai's name for "here is my structured output". It is how a run returns, not
 * work it did, and its args are the answer the `Answer` component already renders from
 * the result endpoint. Showing it would print the conclusion twice, once as JSON.
 */
const OUTPUT_TOOL = "final_result";

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

export function buildThread(events: SequencedEvent[]): Item[] {
  const root: Item[] = [];
  const byToolCall = new Map<string, ToolItem>();

  const append = (event: SequencedEvent, item: Item): void => {
    const parent = event.parent_tool_call_id
      ? byToolCall.get(event.parent_tool_call_id)
      : undefined;
    (parent ? parent.children : root).push(item);
  };

  for (const event of events) {
    if (event.type === TEXT || event.type === THINKING) {
      const kind = event.type === TEXT ? "text" : "thinking";
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
      if (field(event, "tool") === OUTPUT_TOOL) continue;
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

    // run_started / run_finished at the top level are the thread's own boundaries and the
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

/** The assistant's answer so far: top-level prose only, sub-agent chatter excluded. */
export function answerText(items: Item[]): string {
  return items
    .filter((item): item is ProseItem => item.kind === "text")
    .map((item) => item.body)
    .join("\n\n");
}
