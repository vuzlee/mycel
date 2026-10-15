import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeQueryClient } from "../../lib/queryClient";
import { OwnModels } from "./OwnModels";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const MODEL = {
  id: 3,
  ref: "own:3",
  label: "My Gemini",
  model_id: "gemini-2.5-flash",
  api_base: "https://generativelanguage.googleapis.com/v1beta/openai",
  key_hints: ["…0001"],
};
const PRESETS = { presets: { Gemini: MODEL.api_base }, max_models: 10, max_keys: 5 };

function serve(routes: Record<string, unknown>) {
  const sent: { method: string; path: string; body: unknown }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = String(url);
      const method = init?.method ?? "GET";
      sent.push({ method, path, body: init?.body ? JSON.parse(String(init.body)) : null });
      const found = routes[`${method} ${path}`];
      return new Response(JSON.stringify(found ?? {}), { status: found === undefined ? 404 : 200 });
    }),
  );
  return sent;
}

function show() {
  const client = makeQueryClient();
  client.setDefaultOptions({ queries: { retry: false } });
  render(
    <QueryClientProvider client={client}>
      <OwnModels onChange={() => undefined} />
    </QueryClientProvider>,
  );
}

describe("OwnModels", () => {
  it("lists a model with its key count, never a key", async () => {
    serve({ "GET /models/own": [MODEL], "GET /models/own/presets": PRESETS });
    show();
    expect(await screen.findByText("My Gemini")).toBeTruthy();
    expect(screen.getByText(/1 key$/)).toBeTruthy();
  });

  it("an edit without new keys sends no keys, so the stored ones are kept", async () => {
    const sent = serve({
      "GET /models/own": [MODEL],
      "GET /models/own/presets": PRESETS,
      "PATCH /models/own/3": MODEL,
    });
    show();
    fireEvent.click(await screen.findByText("Edit"));
    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => expect(sent.some((s) => s.method === "PATCH")).toBe(true));
    const patch = sent.find((s) => s.method === "PATCH");
    expect(patch?.body).not.toHaveProperty("keys");
  });

  it("a preset fills the base URL", async () => {
    serve({ "GET /models/own": [], "GET /models/own/presets": PRESETS });
    show();
    fireEvent.click(await screen.findByText("Add a model"));
    fireEvent.click(screen.getByText("Gemini"));
    expect((screen.getByPlaceholderText("https://…/v1") as HTMLInputElement).value).toBe(
      MODEL.api_base,
    );
  });

  it("shows what each key's test found", async () => {
    serve({
      "GET /models/own": [MODEL],
      "GET /models/own/presets": PRESETS,
      "POST /models/own/3/test": { job_id: "j", status: "running", checks: [] },
      "GET /models/own/tests/j": {
        job_id: "j",
        status: "done",
        checks: [{ hint: "…0001", ok: false, kind: "quota", detail: "x" }],
      },
    });
    show();
    fireEvent.click(await screen.findByText("Test keys"));
    expect(await screen.findByText("…0001 · out of quota")).toBeTruthy();
  });
});
