/** Mirrors `events/event.py` and `agents/core/emit.py`. Adding a field there is safe. */

export interface SequencedEvent {
  seq: number;
  agent: string;
  type: string;
  payload: Record<string, unknown>;
  parent_tool_call_id: string | null;
}

/** Each attempt at a job starts with this; anything before it was abandoned. */
export const ATTEMPT_STARTED = "attempt_started";
export const RUN_FINISHED = "run_finished";
export const TEXT = "text";
/** A piece of `TEXT`, arriving while the model writes. Merged into the same bubble. */
export const TEXT_DELTA = "text_delta";
export const THINKING = "thinking";
export const TOOL_CALLED = "tool_called";
export const TOOL_RETURNED = "tool_returned";
/** Something about the run itself, e.g. another model answered than the one picked. */
export const NOTICE = "notice";
/** A chart drawn from a tool's own rows. */
export const CHART = "chart";

/** Connection state of a job's stream, as the composer and the header read it. */
export type StreamState = "idle" | "running" | "done" | "error";

export function text(event: SequencedEvent): string {
  const value = event.payload.text;
  return typeof value === "string" ? value : "";
}

export function toolCallId(event: SequencedEvent): string | null {
  const value = event.payload.tool_call_id;
  return typeof value === "string" ? value : null;
}

export function field(event: SequencedEvent, name: string): string {
  const value = event.payload[name];
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}
