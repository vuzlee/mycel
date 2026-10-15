import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { TurnUsage } from "../api";
import { AnswerMeta } from "./AnswerMeta";

const used: TurnUsage = {
  model_ref: "host:claude-sonnet-5",
  model_label: "Claude Sonnet 5",
  tokens_in: 7100,
  tokens_out: 1800,
  duration_ms: 3420,
  spent_usd: "0.0123",
  created_at: new Date().toISOString(),
};

afterEach(cleanup);

describe("AnswerMeta", () => {
  it("shows model, tokens, run time and cost", () => {
    render(<AnswerMeta answer="hi" usage={used} />);
    expect(screen.getByText("Claude Sonnet 5")).toBeTruthy();
    expect(screen.getByText("8.9K tok")).toBeTruthy();
    expect(screen.getByText("3s")).toBeTruthy();
    expect(screen.getByText("$0.0123")).toBeTruthy();
  });

  it("marks an own key's cost as an estimate", () => {
    render(<AnswerMeta answer="hi" usage={{ ...used, model_ref: "own:3" }} />);
    expect(screen.getByText("~$0.0123")).toBeTruthy();
  });

  it("says when a model has no price rather than showing $0", () => {
    render(<AnswerMeta answer="hi" usage={{ ...used, spent_usd: "0" }} />);
    expect(screen.getByText("no price")).toBeTruthy();
  });

  it("leaves out what an older turn did not keep", () => {
    const old = {
      ...used,
      model_label: null,
      tokens_in: null,
      tokens_out: null,
      duration_ms: null,
    };
    render(<AnswerMeta answer="hi" usage={old} />);
    expect(screen.queryByText(/tok$/)).toBeNull();
    expect(screen.getByLabelText("Copy answer")).toBeTruthy();
  });
});
