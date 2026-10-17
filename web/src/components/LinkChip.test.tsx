import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Markdown } from "./Markdown";

afterEach(cleanup);

const EVENT = "https://www.google.com/calendar/event?eid=abc";

describe("a link in an answer", () => {
  it("is a chip that names a calendar event instead of printing its url", () => {
    render(<Markdown body={`Booked: ${EVENT}`} />);
    const link = screen.getByRole("link");
    expect(link.className).toBe("link-chip");
    expect(link.textContent).toBe("Open in calendar");
    expect(link.getAttribute("href")).toBe(EVENT);
  });

  it("keeps the words a link was written with", () => {
    render(<Markdown body={`[Team meeting](${EVENT})`} />);
    expect(screen.getByRole("link").textContent).toBe("Team meeting");
  });

  it("names any other bare url by its domain", () => {
    render(<Markdown body="See https://www.example.com/page" />);
    expect(screen.getByRole("link").textContent).toBe("example.com");
  });
});
