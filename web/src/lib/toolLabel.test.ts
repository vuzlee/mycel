import { describe, expect, it } from "vitest";
import { labelFor, resultSummary } from "./toolLabel";

describe("labelFor", () => {
  it("says what a summary covers, not its arguments", () => {
    expect(labelFor("summarizer", '{"project": "MYC", "days": 7}')).toBe(
      "Summarizing MYC · last 7 days",
    );
  });

  it("never shows the SQL a model wrote", () => {
    expect(labelFor("run_sql", '{"query": "SELECT * FROM gold.work_item"}')).toBe(
      "Querying the work data",
    );
  });

  it("names the period of a ready-made read", () => {
    expect(labelFor("hours_by_person", '{"period": "this_month"}')).toBe(
      "Hours per person · this month",
    );
  });

  it("lists every query of a batched web search", () => {
    expect(labelFor("web_search", '{"queries": ["ai news", "openai"]}')).toBe(
      "Searching the web · ai news · openai",
    );
  });

  it("still reads a web search stored before batching", () => {
    expect(labelFor("web_search", '{"query": "ai news"}')).toBe("Searching the web · ai news");
  });

  it("hides the structured answer an agent hands back", () => {
    expect(labelFor("final_result", '{"headline": "157 tickets closed"}')).toBe("Writing up");
  });

  it("makes an unknown tool readable and leaves its input out", () => {
    expect(labelFor("fetch_invoice", '{"id": 42}')).toBe("Running fetch invoice");
  });

  it("survives arguments that are not JSON", () => {
    expect(labelFor("summarizer", "{trunc")).toBe("Summarizing the project");
  });
});

describe("resultSummary", () => {
  it("counts rows and names the issues in them", () => {
    const table = "issue_key | title\nMYC-1 | a\nMYC-2 | b";
    expect(resultSummary(table)).toBe("2 rows · MYC-1, MYC-2");
  });

  it("says when nothing came back", () => {
    expect(resultSummary("issue_key | title\n(no rows)")).toBe("Nothing found");
  });

  it("adds nothing for a result that is not a table", () => {
    expect(resultSummary('{"figures": []}')).toBe("");
  });
});
