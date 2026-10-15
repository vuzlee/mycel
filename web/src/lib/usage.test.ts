import { describe, expect, it } from "vitest";
import { clock, compact, duration, money } from "./usage";

describe("the line under an answer", () => {
  it("shortens token counts", () => {
    expect([compact(950), compact(8900), compact(12_400), compact(1_250_000)]).toEqual([
      "950",
      "8.9K",
      "12K",
      "1.3M",
    ]);
  });

  it("writes run time for a reader", () => {
    expect([duration(850), duration(3420), duration(65_000)]).toEqual(["850ms", "3s", "1m 05s"]);
  });

  it("keeps cents visible and never shows a cost as zero digits", () => {
    expect([money("0.0123"), money("0.00004"), money("0")]).toEqual(["$0.0123", "<$0.0001", "$0"]);
  });

  it("adds the date only for another day", () => {
    const now = new Date(2026, 9, 16, 23, 0);
    expect(clock(new Date(2026, 9, 16, 22, 9).toISOString(), now)).toMatch(/^22:09$/);
    expect(clock(new Date(2026, 9, 14, 22, 9).toISOString(), now)).toMatch(/14.*22:09/);
  });
});
