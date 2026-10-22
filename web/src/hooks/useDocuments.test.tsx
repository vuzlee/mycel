import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../context/AuthContext";
import { makeQueryClient } from "../lib/queryClient";
import { useDocuments } from "./useDocuments";

/** A stream the test opens, refuses and feeds by hand. */
class FakeEventSource {
  static CLOSED = 2;
  static opened: FakeEventSource[] = [];
  readyState = 0;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    FakeEventSource.opened.push(this);
  }
  close(): void {
    this.readyState = FakeEventSource.CLOSED;
  }
  refuse(): void {
    this.readyState = FakeEventSource.CLOSED;
    this.onerror?.();
  }
  send(data: string): void {
    this.onmessage?.({ data } as MessageEvent<string>);
  }
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={makeQueryClient()}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

const stream = (i: number): FakeEventSource => {
  const found = FakeEventSource.opened[i];
  if (!found) throw new Error(`stream ${i} was never opened`);
  return found;
};

const signedIn = (): Response => new Response(JSON.stringify({ id: 1, email: "a@b.c" }));

beforeEach(() => {
  FakeEventSource.opened = [];
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => signedIn()),
  );
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useDocuments", () => {
  it("reopens a stream the proxy refused, and recovers on the next list", async () => {
    const { result } = renderHook(() => useDocuments(), { wrapper });
    expect(FakeEventSource.opened).toHaveLength(1);

    await act(async () => {
      stream(0).refuse();
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(FakeEventSource.opened).toHaveLength(2);
    act(() => stream(1).send(JSON.stringify({ documents: [], busy: false })));
    expect(result.current.error).toBeNull();
  });

  it("skips a malformed frame instead of throwing", () => {
    const { result } = renderHook(() => useDocuments(), { wrapper });

    act(() => stream(0).send("{not json"));

    expect(result.current.loading).toBe(true);
  });
});
