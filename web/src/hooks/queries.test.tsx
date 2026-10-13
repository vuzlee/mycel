import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeQueryClient, whenUnauthorized } from "../lib/queryClient";
import { usePastTurns } from "./usePastTurns";
import { useRun } from "./useRun";

class SilentEventSource {
  static CLOSED = 2;
  readyState = 0;
  onmessage: unknown = null;
  onerror: unknown = null;
  addEventListener(): void {}
  close(): void {}
}

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={makeQueryClient()}>{children}</QueryClientProvider>;
}

const ok = (body: unknown): Response => new Response(JSON.stringify(body), { status: 200 });

beforeEach(() => {
  vi.stubGlobal("EventSource", SilentEventSource);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useRun", () => {
  it("polls until the run settles, then stops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const answers = [
      { status: "running" },
      { status: "running" },
      { status: "done", answer: "42", conversation_id: 1 },
    ];
    const fetchMock = vi.fn(async () => ok(answers.shift() ?? { status: "done" }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useRun("job-1"), { wrapper });
    for (let i = 0; i < 4; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
    }

    await waitFor(() => expect(result.current.result?.status).toBe("done"));
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.current.pending).toBe(false);
  });

  it("says when the run does not exist", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 404 })),
    );
    const { result } = renderHook(() => useRun("gone"), { wrapper });
    await waitFor(() => expect(result.current.failure).toMatch(/No such run/));
  });
});

describe("a 401", () => {
  it("drops the session once, through the query cache", async () => {
    const dropped = vi.fn();
    whenUnauthorized(dropped);
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(null, { status: 401 })),
    );

    renderHook(() => usePastTurns(5, null), { wrapper });

    await waitFor(() => expect(dropped).toHaveBeenCalledTimes(1));
  });
});

describe("usePastTurns", () => {
  it("leaves out the run being watched", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ok([{ job_id: "old" }, { job_id: "now" }])),
    );
    const { result } = renderHook(() => usePastTurns(5, "now"), { wrapper });
    await waitFor(() => expect(result.current.pastFor).toBe("now"));
    expect(result.current.past.map((t) => t.job_id)).toEqual(["old"]);
  });
});
