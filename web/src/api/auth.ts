/** Sign-in: methods, Google, emailed code, session. */

import type { User } from "./types";
import { USER, get, json, post, shaped } from "./client";

/** Which ways in this deployment offers. */
export interface SignInMethods {
  google: boolean;
  code: boolean;
}

export const fetchSignInMethods = (): Promise<SignInMethods> => get<SignInMethods>("/auth/methods");

/** A full-page navigation, not a fetch: Google's screens cannot live in an XHR. */
export const googleSignInUrl = (hint: string | null, next: string): string => {
  const query = new URLSearchParams({ next });
  if (hint) query.set("hint", hint);
  return `/auth/google/signin?${query}`;
};

/** 202 whether or not the address may sign in; 503 when the deployment cannot send mail. */
export const requestCode = (email: string): Promise<void> => post<void>("/auth/code", { email });

export const verifyCode = (email: string, code: string): Promise<User> =>
  post<unknown>("/auth/code/verify", { email, code }).then((v) => shaped<User>(v, USER, "user"));

export async function logout(): Promise<void> {
  await fetch("/auth/logout", { method: "POST" });
}

/** Who is signed in, or null. Null rather than throwing: "nobody" is a normal answer
 *  here, and it is the one question in the app where a 401 is not an error. */
export async function me(): Promise<User | null> {
  const res = await fetch("/auth/me");
  if (res.status === 401) return null;
  return shaped<User>(await json<unknown>(res), USER, "user");
}
