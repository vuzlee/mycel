import { afterEach, describe, expect, it, vi } from "vitest";
import { Unauthorized, deleteDocument, fetchModels, fetchProjects, shaped, toggleModel } from ".";

function answer(status: number, body: string): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(body || null, { status })),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("request", () => {
  it("treats an empty 2xx body as no value", async () => {
    answer(202, "");
    await expect(deleteDocument(1)).resolves.toBeUndefined();
  });

  it("turns a 401 into Unauthorized", async () => {
    answer(401, "");
    await expect(fetchProjects()).rejects.toBeInstanceOf(Unauthorized);
  });

  it("names the server's detail on any other failure", async () => {
    answer(409, JSON.stringify({ detail: "Already uploaded." }));
    await expect(fetchProjects()).rejects.toThrow("Already uploaded.");
  });
});

describe("shaped", () => {
  const user = { id: "number", email: "string", note: "string?", state: ["a", "b"] } as const;

  it("passes a body whose fields have the right kinds", () => {
    const body = { id: 1, email: "a", note: null, state: "a" };
    expect(shaped(body, user, "user")).toBe(body);
  });

  it("names the first field that is missing or of the wrong kind", () => {
    expect(() => shaped([{ id: 1, note: null, state: "a" }], user, "user")).toThrow("bad email");
    expect(() => shaped({ id: "1", email: "a", note: null, state: "a" }, user, "user")).toThrow(
      "bad id",
    );
    expect(() => shaped({ id: 1, email: "a", note: null, state: "c" }, user, "user")).toThrow(
      "bad state",
    );
    expect(() => shaped("<html>", user, "user")).toThrow("not an object");
  });
});

describe("models", () => {
  const list = {
    models: [{ ref: "host:a", label: "A", source: "host", enabled: true }],
    default_ref: "host:a",
  };

  it("reads the list and checks each model", async () => {
    answer(200, JSON.stringify(list));
    await expect(fetchModels()).resolves.toEqual(list);
  });

  it("refuses a model with an unknown source", async () => {
    answer(200, JSON.stringify({ ...list, models: [{ ...list.models[0], source: "x" }] }));
    await expect(fetchModels()).rejects.toThrow("bad source");
  });

  it("says why the last model cannot go off", async () => {
    answer(409, JSON.stringify({ detail: "at least one model must stay on" }));
    await expect(toggleModel("host:a", false)).rejects.toThrow("at least one model");
  });
});
