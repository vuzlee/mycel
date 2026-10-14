/** The two batch A fixes a browser run cannot keep watching: listener cleanup and the source race. */

import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, renderHook, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SourcePanel } from "../components/knowledge/SourcePanel";
import { makeQueryClient } from "../lib/queryClient";
import { useFollow } from "./useJobStream";

class CountingObserver {
  static live = 0;
  constructor() {
    CountingObserver.live += 1;
  }
  observe(): void {}
  disconnect(): void {
    CountingObserver.live -= 1;
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
  CountingObserver.live = 0;
});

describe("useFollow (#7)", () => {
  it("keeps one listener and one observer however often the ref is called", () => {
    vi.stubGlobal("ResizeObserver", CountingObserver);
    const element = document.createElement("div");
    const added = vi.spyOn(element, "addEventListener");
    const removed = vi.spyOn(element, "removeEventListener");
    const { result } = renderHook(() => useFollow());

    for (let i = 0; i < 20; i++) act(() => result.current.ref(element));
    expect(added).toHaveBeenCalledTimes(1);
    expect(CountingObserver.live).toBe(1);

    act(() => result.current.ref(null));
    expect(removed).toHaveBeenCalledTimes(1);
    expect(CountingObserver.live).toBe(0);
  });

  it("watches the conversation that replaces the blank page", async () => {
    const watched: Element[] = [];
    class RecordingObserver {
      observe(target: Element): void {
        watched.push(target);
      }
      disconnect(): void {}
    }
    vi.stubGlobal("ResizeObserver", RecordingObserver);
    const element = document.createElement("div");
    const blank = document.createElement("div");
    element.appendChild(blank);
    const { result } = renderHook(() => useFollow());
    act(() => result.current.ref(element));

    const conversation = document.createElement("div");
    element.replaceChild(conversation, blank);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(watched).toContain(conversation);
  });
});

describe("SourcePanel (#8)", () => {
  const source = (chunk: number) => ({
    label: String(chunk),
    chunk_id: chunk,
    document_id: chunk,
    filename: `doc-${chunk}.md`,
    mime: "text/markdown",
    page: null,
    page_end: null,
    section: "",
  });

  it("shows the source clicked last, even when the first answers later", async () => {
    const resolvers: Record<string, (r: Response) => void> = {};
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (path: string) =>
          new Promise<Response>((resolve) => {
            resolvers[path] = resolve;
          }),
      ),
    );
    const client = makeQueryClient();
    const wrap = (node: ReactNode) => (
      <QueryClientProvider client={client}>{node}</QueryClientProvider>
    );
    const { rerender } = render(wrap(<SourcePanel source={source(1)} onClose={() => {}} />));
    rerender(wrap(<SourcePanel source={source(2)} onClose={() => {}} />));

    const answer = (text: string) =>
      new Response(JSON.stringify({ text, chunk_id: 0 }), { status: 200 });
    await act(async () => resolvers["/chunks/2"]!(answer("second passage")));
    await act(async () => resolvers["/chunks/1"]!(answer("first passage")));

    expect(await screen.findByText("second passage")).toBeTruthy();
    expect(screen.queryByText("first passage")).toBeNull();
  });
});
