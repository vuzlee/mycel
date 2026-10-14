import { describe, expect, it } from "vitest";
import { buildConversation } from "./buildConversation";
import type { SequencedEvent } from "./types";

const event = (
  seq: number,
  type: string,
  payload: Record<string, unknown> = {},
): SequencedEvent => ({
  seq,
  agent: "orchestrator",
  type,
  payload,
  parent_tool_call_id: null,
});

describe("buildConversation", () => {
  it("drops the partial answer of an abandoned attempt", () => {
    const items = buildConversation([
      event(1, "attempt_started"),
      event(2, "text_delta", { text: "The first try got as far as" }),
      event(3, "attempt_started"),
      event(4, "text_delta", { text: "The whole answer." }),
    ]);

    expect(items).toEqual([
      { kind: "text", seq: 4, agent: "orchestrator", body: "The whole answer." },
    ]);
  });
});
