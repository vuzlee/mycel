/**
 * Turns a flat event list into the tree the thread renders.
 *
 * Nesting is by `parent_tool_call_id`, never by arrival time. `next-slice.html` §05 is
 * explicit about why: ordering holds within one agent and never across two running in
 * parallel, so a flat timeline of a delegating run is a lie that reads as noise.
 *
 * Consecutive `text` and `thinking` events from the same agent are merged: a model streams
 * prose in pieces, and one bubble per piece is unreadable.
 *
 * Nothing is filtered out any more. Until batch 033 the orchestrator returned through
 * pydantic-ai's `final_result` tool, and that one call had to be hidden — its args were
 * the answer, and showing them printed the conclusion twice, once as JSON. A free-text
 * answer arrives as `text` events instead, so every tool call left is work the run did.
 */

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

/** The assistant's answer so far: top-level prose only, sub-agent chatter excluded.
 *
 *  The main path since batch 033 — the answer is the prose, and there is no structured
 *  output to read it off instead. */
export function answerText(items: Item[]): string {
  return items
    .filter((item): item is ProseItem => item.kind === "text")
    .map((item) => item.body)
    .join("\n\n");
}
