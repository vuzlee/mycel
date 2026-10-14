import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider } from "../context/auth";
import { makeQueryClient } from "../lib/queryClient";
import { Waiting } from "./Waiting";

afterEach(() => vi.unstubAllGlobals());

function renderWaiting() {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <Waiting />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("Waiting", () => {
  it("offers a retry when the API cannot say who is signed in", async () => {
    const fetchMock = vi.fn(async () => new Response("bad gateway", { status: 502 }));
    vi.stubGlobal("fetch", fetchMock);

    renderWaiting();

    const button = await screen.findByRole("button", { name: "Try again" });
    fireEvent.click(button);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
