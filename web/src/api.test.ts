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
  it("passes a body with the fields and names the first one missing", () => {
    expect(shaped({ id: 1, email: "a" }, ["id", "email"], "user")).toEqual({ id: 1, email: "a" });
    expect(() => shaped([{ id: 1 }], ["id", "email"], "user")).toThrow("no email");
    expect(() => shaped("<html>", ["id"], "user")).toThrow("unexpected user");
  });
});
