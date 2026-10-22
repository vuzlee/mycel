/** `useFollow` drops its observer when the conversation unmounts or is replaced. */

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
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

describe("useFollow", () => {
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
