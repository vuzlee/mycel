/**
 * The email-and-password form, shared by signing in and signing up.
 *
 * The two pages differ in what submitting means and in what happens afterwards, not in
 * what they ask for — so the fields live here and the outcome lives with each page. Two
 * separately written forms is how the two drift apart.
 */

import { useState } from "react";
import { Spinner } from "./icons";

interface Props {
  /** What the button says, and what this form is for. */
  verb: string;
  /** Tells the browser's password manager which of the two this is. */
  isNew?: boolean;
  /** Resolves when the work is done; rejecting leaves the message on screen. */
  onSubmit: (email: string, password: string) => Promise<void>;
  /** The sentence the API wrote, if the page kept one from a previous attempt. */
  failure: string | null;
  onFailure: (failure: string | null) => void;
}

export function Credentials({ verb, isNew = false, onSubmit, failure, onFailure }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (): Promise<void> => {
    setBusy(true);
    onFailure(null);
    try {
      await onSubmit(email, password);
      setPassword("");
    } catch (error) {
      onFailure(readable(error, verb));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label>
        <span className="label">Email</span>
        <input
          type="email"
          autoComplete="username"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </label>

      <label>
        <span className="label">Password</span>
        <input
          type="password"
          autoComplete={isNew ? "new-password" : "current-password"}
          required
          minLength={8}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
        {isNew && <span className="hint">At least 8 characters.</span>}
      </label>

      {failure && <p className="failure">{failure}</p>}

      <button className="primary" type="submit" disabled={busy}>
        {busy && <Spinner className="spin" size={14} />}
        {verb}
      </button>
    </form>
  );
}

/** `services/auth.py` already writes a sentence a person can read, and it is deliberately
 *  vague about which half of a credential pair failed. Pass it through rather than
 *  guessing at it from a status code. */
function readable(error: unknown, verb: string): string {
  const message = error instanceof Error ? error.message : String(error);
  if (/password|email|registered/i.test(message)) return sentence(message);
  return `${verb} failed: ${message}`;
}

const sentence = (text: string): string => text.charAt(0).toUpperCase() + text.slice(1) + ".";
