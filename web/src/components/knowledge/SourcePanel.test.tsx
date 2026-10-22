/** A slow answer for an earlier passage never replaces the one now open. */

import { QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeQueryClient } from "../../lib/queryClient";
import { SourcePanel } from "./SourcePanel";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourcePanel", () => {
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
