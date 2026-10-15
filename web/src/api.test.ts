import { afterEach, describe, expect, it, vi } from "vitest";
import { Unauthorized, deleteDocument, fetchProjects, shaped } from "./api";

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
