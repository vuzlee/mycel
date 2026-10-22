/** The HTTP client: one `request`, a 401 handled once, and field-shape checks. */

/** A 401 from any call means the session is gone, and every page reacts the same way. */
export class Unauthorized extends Error {
  constructor() {
    super("not signed in");
  }
}

let onUnauthorized: () => void = () => {};

/** Set by the auth provider: what a dead session means for the page. */
export function whenUnauthorized(handler: () => void): void {
  onUnauthorized = handler;
}

/** Every 401, reads and writes alike, drops the session here before it throws. */
function unauthorized(): Unauthorized {
  onUnauthorized();
  return new Unauthorized();
}

export async function json<T>(res: Response): Promise<T> {
  if (res.status === 401) throw unauthorized();
  if (!res.ok) throw new Error(await detail(res));
  return (await res.json()) as T;
}

/** The sentence the API wrote, if it wrote one. Every handler in `api/app.py` answers
 *  with `{error, detail, request_id}`; anything else is shown as the status and body. */
async function detail(res: Response): Promise<string> {
  const body = await res.text();
  try {
    const parsed: unknown = JSON.parse(body);
    if (parsed && typeof parsed === "object" && "detail" in parsed) {
      const found = (parsed as { detail: unknown }).detail;
      if (typeof found === "string") return found;
    }
  } catch {
    // Not JSON — a proxy error page, most likely.
  }
  return `${res.status} ${body.slice(0, 300)}`;
}

/** One call to the API: JSON in, JSON out; a 401 is `Unauthorized`, any other failure throws. */
export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.headers = { "content-type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 401) throw unauthorized();
  if (!res.ok) throw new Error(await detail(res));
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** What a field must be: a `typeof` name, `?` suffix for nullable, or a list of literals. */
type FieldKind =
  "string" | "number" | "boolean" | "string?" | "number?" | "array" | readonly string[];
export type Shape = Record<string, FieldKind>;

function fits(value: unknown, kind: FieldKind): boolean {
  if (Array.isArray(kind)) return kind.includes(value as string);
  if (kind === "array") return Array.isArray(value);
  if (typeof kind === "string" && kind.endsWith("?"))
    return value === null || typeof value === kind.slice(0, -1);
  return typeof value === kind;
}

/** The body checked against the fields the page reads, so a wrong shape fails here, by
 *  name, instead of as `undefined` deep in a component. An array checks each item. */
export function shaped<T>(value: unknown, shape: Shape, what: string): T {
  for (const item of Array.isArray(value) ? value : [value]) {
    if (!item || typeof item !== "object")
      throw new Error(`the server sent an unexpected ${what}: not an object`);
    for (const [key, kind] of Object.entries(shape)) {
      const field = (item as Record<string, unknown>)[key];
      if (!fits(field, kind))
        throw new Error(
          `the server sent an unexpected ${what}: bad ${key} (${JSON.stringify(field)})`,
        );
    }
  }
  return value as T;
}

export const STATUS = ["running", "done", "failed"] as const;
export const USER: Shape = { id: "number", email: "string" };
export const ACCEPTED: Shape = { job_id: "string", conversation_id: "number" };
export const USAGE: Shape = {
  model_label: "string?",
  tokens_in: "number?",
  tokens_out: "number?",
  duration_ms: "number?",
  spent_usd: "string?",
};
export const CHAT_RESULT: Shape = {
  ...USAGE,
  job_id: "string",
  status: STATUS,
  answer: "string?",
  conversation_id: "number?",
  question: "string?",
};
export const CONVERSATION: Shape = { id: "number", title: "string", pinned: "boolean" };
export const TURN: Shape = {
  ...USAGE,
  job_id: "string",
  question: "string",
  status: "string",
  answer: "string?",
};

export const get = <T>(path: string): Promise<T> => request<T>("GET", path);
export const post = <T>(path: string, body?: unknown): Promise<T> => request<T>("POST", path, body);
export const del = (path: string): Promise<void> => request<void>("DELETE", path);
