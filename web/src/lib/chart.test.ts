import { describe, expect, it } from "vitest";
import { parseChart } from "../components/Chart";
import { buildConversation } from "./buildConversation";
import type { SequencedEvent } from "./types";

const spec = { type: "bar", title: "Hours", unit: "h", labels: ["ann", "bob"], values: [7, 3] };

describe("parseChart", () => {
  it("takes the one shape the server sends", () => {
    expect(parseChart(spec)?.values).toEqual([7, 3]);
  });

  it("refuses a chart whose labels and values do not pair up", () => {
    expect(parseChart({ ...spec, values: [7] })).toBeNull();
  });

  it("refuses an unknown type", () => {
    expect(parseChart({ ...spec, type: "pie" })).toBeNull();
  });
});

describe("a chart event", () => {
  it("lands at the top level, not inside the step that drew it", () => {
    const events: SequencedEvent[] = [
      {
        seq: 1,
        agent: "orchestrator",
        type: "tool_called",
        payload: { tool: "analyst", tool_call_id: "a" },
        parent_tool_call_id: null,
      },
      { seq: 2, agent: "chart", type: "chart", payload: { chart: spec }, parent_tool_call_id: "a" },
    ];
    const items = buildConversation(events);
    expect(items.map((i) => i.kind)).toEqual(["tool", "chart"]);
  });
});
