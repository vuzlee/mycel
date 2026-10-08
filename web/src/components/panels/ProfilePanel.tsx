import { useState } from "react";
import type { ConversationSummary } from "../../api";
import { changePassword } from "../../api";
import { useAuth } from "../../context/auth";
import { Spinner } from "../icons";

/** The account, as the server knows it. The address cannot be changed — it is the
 *  identity — and the password can, which is why one of the two has a form. */
export function ProfilePanel({ conversations }: { conversations: ConversationSummary[] }) {
  const { user } = useAuth();
  if (!user) return null;

  return (
    <>
      <div className="identity">
        <span className="avatar big" aria-hidden>
          {user.email.charAt(0).toUpperCase()}
        </span>
        <div>
          <b>{user.email}</b>
          <span className="muted">Account #{user.id}</span>
        </div>
      </div>

      <dl className="facts">
        <div>
          <dt>Runs kept</dt>
          <dd>{conversations.length}</dd>
        </div>
        <div>
          <dt>Sign-in</dt>
          <dd>Password</dd>
        </div>
      </dl>

      <p className="muted">
        Your runs are kept under this account, so signing in on another machine brings them with
        you. The address is the identity here and cannot be changed.
      </p>

      <PasswordForm />
    </>
  );
}

/** Changing the password needs the current one even though a valid cookie is already in
 *  hand: a borrowed laptop is exactly the case that protects against. Every other session
 *  ends, and this one does not — you stay in the tab you are typing in. */
function PasswordForm() {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = async (): Promise<void> => {
    setBusy(true);
    setFailure(null);
    setDone(false);
    try {
      await changePassword(current, next);
      setCurrent("");
      setNext("");
      setDone(true);
    } catch (error) {
      setFailure(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <h3 className="label">Change password</h3>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label>
          <span className="label">Current password</span>
          <input
            type="password"
            autoComplete="current-password"
            required
            value={current}
            onChange={(event) => setCurrent(event.target.value)}
          />
        </label>

        <label>
          <span className="label">New password</span>
          <input
            type="password"
            autoComplete="new-password"
            required
            minLength={8}
            value={next}
            onChange={(event) => setNext(event.target.value)}
          />
          <span className="hint">At least 8 characters.</span>
        </label>

        {failure && <p className="failure">{failure}</p>}
        {done && <p className="notice">Changed. Every other browser has been signed out.</p>}

        <button className="primary" type="submit" disabled={busy}>
          {busy && <Spinner className="spin" size={14} />}
          Change it
        </button>
      </form>
    </section>
  );
}
